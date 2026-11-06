"""
model_routing.py — Evaluate → Optimize models: choose a model for every LLM node of a pipeline so
the whole pipeline costs least (or answers fastest) while its eval pass rate stays within a
tolerance of what the saved models score.

A per-call router picks a model for one call in isolation. Here every candidate assignment is
judged by running the *whole* pipeline — nested pipelines included — on the eval dataset, so a
cheaper model upstream that makes downstream nodes work harder (longer context, more Master Agent
turns, retries, fallbacks) is charged for that in the cost it's ranked by.

Slots are the nodes whose model a run uses: the LLM node a single-LLM flow runs, or a Master
Agent and its LLM children, in this pipeline and every published pipeline it calls (at their
pinned versions). A slot's key is ``<app id>:<node id>``; overrides reach nested pipelines through
``pipeline_runner.model_overrides`` without touching any saved flow.

Search — a *config* is one assignment of models to slots, run on the dataset:

1. **Baseline**: the saved models, every case. Target pass rate = baseline − ``tolerance``.
2. **Single swaps**: each slot × each candidate, every other slot at baseline. With
   ``screen_cases`` set, a swap runs on the first N cases first and only goes on to the full
   dataset if it keeps the target there (against the baseline's own pass rate on those cases).
3. **Combination**: the swaps that met the target and beat the baseline, biggest saving first,
   are added one at a time to the best config so far. Each combination runs on the full dataset
   and is kept only if it still meets the target and beats the best — so interactions between
   slots are measured, not assumed.

At most ``max_configs`` configs run (screens count); the result says when the budget cut the
search short. ``slot_keys`` limits the search to some nodes (the rest keep their saved models), and
``parallel`` runs that many cases of a config at once. A study can be cancelled while queued or
running; it keeps the configs measured so far. The engine (``search``) is independent of how a config is run; ``run_study`` wires
it to the eval runner and stores progress in ``model_optimizations`` as it goes.

Model outputs vary run to run: a tolerance of 0 on a small dataset can reject a swap on noise.
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from db import get_db_connection
from services import jobs, secret_store
from services.pipeline_runner import (
    RunScope, _neighbours, _resolve_key, current_scope, model_overrides, selected_llm_node, slot_key, walk_flows,
)

logger = logging.getLogger("pipesets-ai-backend")

JOB_KIND = "eval.optimize_models"
OBJECTIVES = ("cost", "latency")
MAX_PARALLEL = 16
KEYLESS_PROVIDERS = {"local", "ollama", "llamacpp", "jan", "huggingface"}

Assignment = Dict[str, Dict[str, str]]          # slot key -> {"provider", "model"}


@dataclass
class Slot:
    key: str
    app_id: str
    node_id: str
    node_type: str          # llm | master_agent | child_agent
    label: str
    source: str             # "this pipeline" or "<name> v<version>"
    provider: str
    model: str


@dataclass
class CaseOutcome:
    score: float
    passed: bool
    cost_usd: float
    latency_ms: int
    error: Optional[str] = None


@dataclass
class ConfigResult:
    assignment: Assignment
    phase: str              # baseline | screen | single | combined
    cases: int
    pass_rate: float
    mean_score: float
    cost_per_case_usd: float
    avg_latency_ms: float
    errors: int
    first_error: Optional[str] = None
    meets_target: Optional[bool] = None
    outcomes: List[CaseOutcome] = field(default_factory=list, repr=False)

    def objective(self, objective: str) -> float:
        return self.cost_per_case_usd if objective == "cost" else self.avg_latency_ms

    def public(self) -> Dict[str, Any]:
        out = asdict(self)
        out.pop("outcomes")
        return out


# evaluate(assignment, cases, tick): run ``cases`` with ``assignment``; await ``tick(outcome)`` after each case
Tick = Callable[[CaseOutcome], Awaitable[None]]
Evaluate = Callable[[Assignment, List[Any], Tick], Awaitable[ConfigResult]]


def summarize(assignment: Assignment, phase: str, outcomes: List[CaseOutcome]) -> ConfigResult:
    n = len(outcomes) or 1
    return ConfigResult(
        assignment=assignment, phase=phase, cases=len(outcomes),
        pass_rate=round(sum(o.passed for o in outcomes) / n, 4),
        mean_score=round(sum(o.score for o in outcomes) / n, 4),
        cost_per_case_usd=round(sum(o.cost_usd for o in outcomes) / n, 8),
        avg_latency_ms=round(sum(o.latency_ms for o in outcomes) / n, 1),
        errors=sum(1 for o in outcomes if o.error),
        first_error=next((o.error for o in outcomes if o.error), None),
        outcomes=outcomes,
    )


# ── Slots ─────────────────────────────────────────────────────────────────────

def discover_slots(app_id: str, flow: Dict[str, Any], scope: RunScope) -> Tuple[List[Slot], List[str]]:
    """Every node whose model a run of ``flow`` uses, nested pipelines included."""
    visited, errors = walk_flows(flow, scope, app_id)
    slots: Dict[str, Slot] = {}

    def add(run_key: str, source: str, node: Dict[str, Any]) -> None:
        d = node.get("data", {}) or {}
        key = slot_key(run_key, node["id"])
        if key not in slots:
            slots[key] = Slot(key=key, app_id=run_key, node_id=node["id"], node_type=node.get("type", ""),
                              label=str(d.get("label") or d.get("role") or node.get("type") or node["id"]),
                              source=source, provider=str(d.get("provider") or ""), model=str(d.get("model") or ""))

    for v in visited:
        run_key = v.get("app_id") or app_id
        nodes, edges = v["flow"].get("nodes", []), v["flow"].get("edges", [])
        master = next((n for n in nodes if n.get("type") == "master_agent"), None)
        if master:
            add(run_key, v["source"], master)
            linked = _neighbours(master["id"], edges)
            for n in nodes:
                if (n.get("type") == "child_agent" and n.get("id") in linked
                        and ((n.get("data") or {}).get("kind") or "llm") == "llm"):
                    add(run_key, v["source"], n)
            continue
        llm_node = selected_llm_node(nodes)
        if llm_node:
            add(run_key, v["source"], llm_node)
    return list(slots.values()), errors


def has_key(provider: str, provider_keys: Dict[str, str]) -> bool:
    """A real call to ``provider`` can be made (without a key the runner simulates the answer)."""
    p = (provider or "").lower()
    return p in KEYLESS_PROVIDERS or bool(_resolve_key(p, "", provider_keys))


def candidates_for(slots: List[Slot], candidates: List[Dict[str, str]],
                   per_slot: Dict[str, List[Dict[str, str]]], provider_keys: Dict[str, str],
                   ) -> Tuple[Dict[str, List[Dict[str, str]]], List[str]]:
    """Each slot's models to try, minus its own and those that can't really run. Returns
    (slot key -> candidates, warnings)."""
    warnings: List[str] = []
    out: Dict[str, List[Dict[str, str]]] = {}
    unusable = set()
    for s in slots:
        tried = set()
        out[s.key] = []
        for c in per_slot.get(s.key) or candidates:
            p, m = str(c.get("provider") or "").lower(), str(c.get("model") or "")
            if not p or not m or (p, m) in tried or (p == s.provider.lower() and m == s.model):
                continue
            tried.add((p, m))
            if p == "mock":
                unusable.add(f"{p}/{m} (simulated answers)")
                continue
            if not has_key(p, provider_keys):
                unusable.add(f"{p}/{m} (no API key)")
                continue
            out[s.key].append({"provider": p, "model": m})
    if unusable:
        warnings.append("Skipped: " + ", ".join(sorted(unusable)))
    return out, warnings


# ── Search ────────────────────────────────────────────────────────────────────

class Budget:
    def __init__(self, max_configs: int):
        self.left = max_configs
        self.truncated = False

    def take(self) -> bool:
        if self.left <= 0:
            self.truncated = True
            return False
        self.left -= 1
        return True


async def search(
    slots: List[Slot], candidates: Dict[str, List[Dict[str, str]]], cases: List[Any], evaluate: Evaluate,
    *, objective: str = "cost", tolerance: float = 0.0, screen_cases: int = 0, max_configs: int = 40,
    on_progress: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    """Find the assignment with the lowest ``objective`` whose pass rate stays ≥ baseline − tolerance."""
    if objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {', '.join(OBJECTIVES)}")
    budget = Budget(max_configs)
    tried: List[ConfigResult] = []
    screen = cases[:screen_cases] if 0 < screen_cases < len(cases) else []
    best: Optional[ConfigResult] = None
    # the config being run right now, for the progress shown while the study runs
    current: Dict[str, Any] = {}
    # upper bound, for the progress bar: baseline + every swap (+ its screen) + one combination per extra slot
    swaps = sum(len(candidates.get(s.key, [])) for s in slots)
    planned = min(max_configs, 1 + swaps * (2 if screen else 1) + max(0, len(slots) - 1))

    def state(best: Optional[ConfigResult], done: bool) -> Dict[str, Any]:
        return {
            "objective": objective, "tolerance": tolerance, "done": done,
            "configs_run": len(tried), "max_configs": max_configs, "planned_configs": planned,
            "current": None if done or not current else dict(current), "truncated": budget.truncated,
            "slots": [asdict(s) for s in slots],
            "baseline": tried[0].public() if tried else None,
            "best": best.public() if best else None,
            "tried": [r.public() for r in tried],
        }

    async def run(assignment: Assignment, phase: str, subset: List[Any]) -> Optional[ConfigResult]:
        if not budget.take():
            return None
        current.clear()
        current.update(assignment=assignment, phase=phase, index=len(tried), cases_done=0, cases_total=len(subset),
                       passed=0, cost_usd=0.0, latency_ms=0)

        async def tick(outcome: CaseOutcome) -> None:
            current["cases_done"] += 1
            current["passed"] += int(outcome.passed)
            current["cost_usd"] += outcome.cost_usd
            current["latency_ms"] += outcome.latency_ms
            if on_progress:
                await on_progress(state(best, False))

        r = await evaluate(assignment, subset, tick)
        current.clear()
        r.phase = phase
        tried.append(r)
        return r

    baseline = await run({}, "baseline", cases)
    if baseline is None:
        return state(None, True)
    if baseline.cases and baseline.errors == baseline.cases:
        raise ValueError(f"Every case failed on the saved models, so there is nothing to compare against: "
                         f"{baseline.first_error}")
    if baseline.cases and baseline.pass_rate == 0:
        raise ValueError("The saved models pass none of the cases, so pass rate can't tell models apart and any model "
                         "would 'keep' it. Check the expected outputs, or use the LLM Judge scorer when they describe "
                         "the answer rather than quote it.")
    target = baseline.pass_rate - tolerance - 1e-9     # 0.9 - 0.3 must admit 0.6
    baseline.meets_target = True
    if screen:
        screen_target = summarize({}, "screen", baseline.outcomes[:len(screen)]).pass_rate - tolerance - 1e-9
    best = baseline
    if on_progress:
        await on_progress(state(best, False))

    # 2. single swaps
    viable: List[ConfigResult] = []
    for s in slots:
        for c in candidates.get(s.key, []):
            assignment = {s.key: c}
            if screen:
                r = await run(assignment, "screen", screen)
                if r is None:
                    break
                r.meets_target = r.pass_rate >= screen_target
                if not r.meets_target:
                    if on_progress:
                        await on_progress(state(best, False))
                    continue
            r = await run(assignment, "single", cases)
            if r is None:
                break
            r.meets_target = r.pass_rate >= target
            if r.meets_target and r.objective(objective) < baseline.objective(objective):
                viable.append(r)
            if on_progress:
                await on_progress(state(best, False))

    # 3. combine, biggest saving first; one model per slot
    viable.sort(key=lambda r: r.objective(objective))
    if viable:
        best = viable[0]
    for r in viable[1:]:
        (key, model), = r.assignment.items()
        if key in best.assignment:
            continue
        combined = await run({**best.assignment, key: model}, "combined", cases)
        if combined is None:
            break
        combined.meets_target = combined.pass_rate >= target
        if combined.meets_target and combined.objective(objective) < best.objective(objective):
            best = combined
        if on_progress:
            await on_progress(state(best, False))

    return state(best, True)


# ── Studies (the job and its row) ─────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat()


def _update(study_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn = get_db_connection()
    try:
        conn.execute(f"UPDATE model_optimizations SET {sets} WHERE id = ?", (*fields.values(), study_id))
        conn.commit()
    finally:
        conn.close()


def create_study(scope: RunScope, body: Dict[str, Any]) -> Dict[str, Any]:
    """Store the study and queue its job. Browser keys are sealed before they reach the DB; vault
    refs ("secret://…") and sealed values stay as they are — sealing a ref would send the ref itself
    to the provider as the key."""
    import uuid
    request = {**body, "provider_keys": {
        p.lower(): v if secret_store.is_protected(v) else secret_store.seal(v)
        for p, v in (body.get("provider_keys") or {}).items() if v}}
    study_id = f"opt_{uuid.uuid4().hex}"
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO model_optimizations (id, tenant_id, project_id, user_id, app_id, app_version, dataset_id, "
            "status, request, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
            (study_id, scope.tenant_id, scope.project_id, scope.user_id, body["app_id"], int(body.get("app_version") or 0),
             body["dataset_id"], json.dumps(request), now, now),
        )
        job_id = jobs.enqueue(JOB_KIND, {"study_id": study_id}, tenant_id=scope.tenant_id,
                              project_id=scope.project_id, max_attempts=1, conn=conn)
        conn.execute("UPDATE model_optimizations SET job_id = ? WHERE id = ?", (job_id, study_id))
        conn.commit()
    finally:
        conn.close()
    jobs.wake_workers()
    return get_study(study_id, scope.tenant_id, scope.project_id)


def _row(study_id: str, tenant_id: Optional[str] = None, project_id: Optional[str] = None):
    sql, params = "SELECT * FROM model_optimizations WHERE id = ?", [study_id]
    if tenant_id is not None:
        sql += " AND tenant_id = ? AND project_id = ?"
        params += [tenant_id, project_id]
    conn = get_db_connection()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def _public(row) -> Dict[str, Any]:
    request = json.loads(row["request"] or "{}")
    request.pop("provider_keys", None)
    return {
        "id": row["id"], "app_id": row["app_id"], "app_version": row["app_version"], "dataset_id": row["dataset_id"],
        "status": row["status"], "request": request, "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"], "job_id": row["job_id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def get_study(study_id: str, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    row = _row(study_id, tenant_id, project_id)
    return _public(row) if row else None


def list_studies(tenant_id: str, project_id: str, app_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM model_optimizations WHERE tenant_id = ? AND project_id = ?"
    params: List[Any] = [tenant_id, project_id]
    if app_id:
        sql += " AND app_id = ?"
        params.append(app_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    conn = get_db_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [_public(r) for r in rows]


def apply_best(study: Dict[str, Any], tenant_id: str, project_id: str) -> Dict[str, Any]:
    """Write the study's best models into its pipeline's draft — a published pipeline goes back
    to draft first, as Edit does. Slots in pipelines it calls are listed, not changed: those run
    at a pinned published version, so they're changed by editing and re-publishing that pipeline."""
    result = study.get("result") or {}
    assignment: Assignment = (result.get("best") or {}).get("assignment") or {}
    slots = {s["key"]: s for s in result.get("slots") or []}
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT status, flow_data FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (study["app_id"], tenant_id, project_id)).fetchone()
        if not row:
            raise LookupError("Pipeline not found")
        flow = json.loads(row["flow_data"] or "{}")
        by_id = {n.get("id"): n for n in flow.get("nodes", [])}
        applied, skipped = [], []
        for key, choice in assignment.items():
            slot = slots.get(key) or {}
            label = slot.get("label") or key
            if slot.get("app_id") != study["app_id"]:
                skipped.append({"key": key, "label": label, "reason": f"in {slot.get('source') or 'a called pipeline'}"})
                continue
            node = by_id.get(slot.get("node_id"))
            if node is None:
                skipped.append({"key": key, "label": label, "reason": "no longer in the draft"})
                continue
            d = node.setdefault("data", {})
            if str(d.get("provider") or "").lower() != choice["provider"]:
                d.pop("api_key", None)
                d.pop("base_url", None)
            d.update(provider=choice["provider"], model=choice["model"])
            applied.append({"key": key, "label": label, **choice})
        if applied:
            conn.execute("UPDATE apps SET flow_data = ?, status = 'draft', updated_at = ? "
                         "WHERE id = ? AND tenant_id = ? AND project_id = ?",
                         (json.dumps(flow), _now(), study["app_id"], tenant_id, project_id))
            conn.commit()
    finally:
        conn.close()
    return {"applied": applied, "skipped": skipped}


def _record_case(study_id: str, index: int, case: Any, output: str, o: CaseOutcome) -> None:
    import uuid
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO model_optimization_cases (id, study_id, config_index, case_id, prompt, expected_output, "
            "output, score, passed, cost_usd, latency_ms, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, study_id, index, case["id"], case["prompt"], case["expected_output"] or "",
             (output or "")[:2000], o.score, int(o.passed), o.cost_usd, o.latency_ms, o.error, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def get_cases(study_id: str, tenant_id: str, project_id: str, config_index: int) -> Optional[List[Dict[str, Any]]]:
    """The cases run so far for one config of a study, in run order; None when the study isn't found."""
    if _row(study_id, tenant_id, project_id) is None:
        return None
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT case_id, prompt, expected_output, output, score, passed, cost_usd, latency_ms, error "
            "FROM model_optimization_cases WHERE study_id = ? AND config_index = ? ORDER BY created_at, id",
            (study_id, config_index),
        ).fetchall()
    finally:
        conn.close()
    return [{**dict(r), "passed": bool(r["passed"])} for r in rows]


async def run_study(study_id: str) -> None:
    from routers.eval import _load_app_flow, _score, run_pipeline_case   # lazy: routers import services
    from routers.v1 import _provider_keys
    from services.flow_summary import pick_generator_llm

    row = await asyncio.to_thread(_row, study_id)
    if row is None or row["status"] in ("done", "failed", "cancelled"):
        return
    req = json.loads(row["request"])
    tenant = (row["tenant_id"], row["project_id"])
    keys = _provider_keys(req.get("provider_keys") or {}, tenant)
    scope = RunScope(tenant_id=row["tenant_id"], project_id=row["project_id"], user_id=row["user_id"],
                     provider_keys=keys, caller=f"optimize:{study_id}")
    await asyncio.to_thread(_update, study_id, status="running")

    token = current_scope.set(scope)   # vault lookups below run in this project
    try:
        app = await asyncio.to_thread(_load_app_flow, row["app_id"], row["app_version"], scope)
        conn = get_db_connection()
        try:
            cases = conn.execute("SELECT * FROM eval_cases WHERE dataset_id = ? ORDER BY created_at ASC",
                                 (row["dataset_id"],)).fetchall()
        finally:
            conn.close()
        if not cases:
            raise ValueError("The dataset has no cases")
        slots, walk_errors = discover_slots(row["app_id"], app["flow"], scope)
        if not slots:
            raise ValueError("The pipeline has no LLM, Master Agent or LLM child node to optimize")
        no_key = [f"{s.label} ({s.provider}/{s.model})" for s in slots if not has_key(s.provider, keys)]
        if no_key:
            raise ValueError("These nodes would run simulated, not on their model, because there is no API key "
                             f"for their provider: {', '.join(no_key)}")
        if req.get("slot_keys"):
            wanted = set(req["slot_keys"])
            slots = [s for s in slots if s.key in wanted]
            if not slots:
                raise ValueError("None of the chosen nodes is in the pipeline any more")
        cands, warnings = candidates_for(slots, req.get("candidates") or [], req.get("slot_candidates") or {}, keys)
        if not any(cands.values()):
            raise ValueError("No candidate model can run: " + ("; ".join(warnings) or "none given"))
        visited, _ = walk_flows(app["flow"], scope, row["app_id"])
        judge = pick_generator_llm(visited, keys)
        pipeline = {"app": app, "scope": scope}
        scorer = req.get("scorer") or "contains"
        timeout_ms = int(req.get("timeout_ms") or 120000)
        parallel = max(1, min(MAX_PARALLEL, int(req.get("parallel") or 1)))
    except Exception as e:
        await asyncio.to_thread(_update, study_id, status="failed", error=str(e))
        return
    finally:
        current_scope.reset(token)

    configs = 0   # evaluate is called once per config, in the order they're added to ``tried``

    gate = asyncio.Semaphore(parallel)
    writes = asyncio.Lock()   # cases finish together; one DB write at a time

    async def evaluate(assignment: Assignment, subset: List[Any], tick: Tick) -> ConfigResult:
        nonlocal configs
        index, configs = configs, configs + 1

        async def one(case: Any) -> CaseOutcome:
            async with gate:
                t0 = time.monotonic()
                actual, error, cost = await run_pipeline_case(row["app_id"], pipeline, case["prompt"], timeout_ms)
                latency = int((time.monotonic() - t0) * 1000)
                score = await _score(scorer, case["prompt"], actual, case["expected_output"] or "", judge)
            outcome = CaseOutcome(score=score, passed=score >= 0.5, cost_usd=cost, latency_ms=latency, error=error)
            async with writes:
                await asyncio.to_thread(_record_case, study_id, index, case, actual, outcome)
            await tick(outcome)
            return outcome

        override = model_overrides.set(assignment)   # the case tasks inherit it
        try:
            outcomes = list(await asyncio.gather(*(one(c) for c in subset)))
        finally:
            model_overrides.reset(override)
        return summarize(assignment, "", outcomes)

    async def progress(state: Dict[str, Any]) -> None:
        async with writes:
            await asyncio.to_thread(_update, study_id, result=json.dumps({**state, "warnings": warnings + walk_errors}))

    try:
        result = await search(
            slots, cands, cases, evaluate,
            objective=req.get("objective") or "cost", tolerance=float(req.get("tolerance") or 0.0),
            screen_cases=int(req.get("screen_cases") or 0), max_configs=int(req.get("max_configs") or 40),
            on_progress=progress,
        )
    except Exception as e:
        logger.exception("Model optimization %s failed", study_id)
        await asyncio.to_thread(_update, study_id, status="failed", error=str(e))
        return
    await asyncio.to_thread(_update, study_id, status="done",
                            result=json.dumps({**result, "warnings": warnings + walk_errors}))


CANCELLED = "Cancelled"


async def cancel_study(study_id: str, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    """Stop a queued or running study; None when it isn't found, ValueError when it has finished.
    It's marked cancelled at once; a running one stops within a few seconds (its worker checks the
    job's cancel flag) and keeps the configs it measured."""
    row = await asyncio.to_thread(_row, study_id, tenant_id, project_id)
    if row is None:
        return None
    if row["status"] not in ("queued", "running"):
        raise ValueError(f"The optimization is {row['status']}")
    await asyncio.to_thread(_update, study_id, status="cancelled", error=CANCELLED)
    try:
        job = await asyncio.to_thread(jobs.cancel, row["job_id"], tenant_id, project_id, CANCELLED)
        if job:
            await jobs.bury_cancelled(job, CANCELLED)
    except LookupError:
        pass   # its job already ended
    return get_study(study_id, tenant_id, project_id)


async def _on_dead(payload: Dict[str, Any], job: jobs.Job, error: str) -> None:
    cancelled = error.startswith(CANCELLED)
    await asyncio.to_thread(_update, payload["study_id"], status="cancelled" if cancelled else "failed",
                            error=CANCELLED if cancelled else error)


@jobs.handler(JOB_KIND, max_attempts=1, on_dead=_on_dead)
async def _study_job(payload: Dict[str, Any], job: jobs.Job) -> None:
    await run_study(payload["study_id"])
