"""Evaluate → Optimize models (services/model_routing.py): the search engine on a scripted
pipeline, per-node model overrides, the gateway's cost meter, and a whole study run through the
API and the eval runner with the OpenAI backend stubbed (the gateway still prices each call)."""
import asyncio
import json

import pytest

import llm
from services import model_routing as mr
from services.pipeline_runner import _build_llm_request, _build_master_request, model_overrides

# ── The engine, on a scripted two-slot pipeline ───────────────────────────────

UP, DOWN = "app:up", "app:down"
SLOTS = [mr.Slot(key=UP, app_id="app", node_id="up", node_type="llm", label="Upstream", source="this pipeline",
                 provider="openai", model="big"),
         mr.Slot(key=DOWN, app_id="app", node_id="down", node_type="llm", label="Downstream",
                 source="this pipeline", provider="openai", model="big")]
CASES = [{"prompt": f"q{i}"} for i in range(10)]


def scripted(per_case_cost, passes):
    """evaluate() whose cost and pass count follow the assignment; records every run."""
    runs = []

    async def evaluate(assignment, subset, tick):
        up = assignment.get(UP, {}).get("model", "big")  # (scripted runs don't tick)
        down = assignment.get(DOWN, {}).get("model", "big")
        runs.append((up, down, len(subset)))
        cost, ok = per_case_cost(up, down), passes(up, down)
        return mr.summarize(assignment, "", [
            mr.CaseOutcome(score=1.0 if i < ok * len(subset) else 0.0, passed=i < ok * len(subset),
                           cost_usd=cost, latency_ms=100) for i in range(len(subset))])
    return evaluate, runs


def cand(*models):
    return [{"provider": "openai", "model": m} for m in models]


def test_pipeline_cost_beats_per_call_cost():
    # "tiny" upstream is the cheapest call, but its terse output makes the downstream node work
    # three times as hard — end to end it costs more than "small", which is what gets picked.
    def cost(up, down):
        up_cost = {"big": 10, "small": 4, "tiny": 1}[up]
        down_cost = {"big": 10, "small": 5}[down] * (3 if up == "tiny" else 1)
        return up_cost + down_cost

    evaluate, _ = scripted(cost, lambda up, down: 1.0)
    result = asyncio.run(mr.search(SLOTS, {UP: cand("small", "tiny"), DOWN: cand("small")}, CASES, evaluate))
    assert result["best"]["assignment"] == {UP: {"provider": "openai", "model": "small"},
                                            DOWN: {"provider": "openai", "model": "small"}}
    assert result["best"]["cost_per_case_usd"] == 9
    assert result["baseline"]["cost_per_case_usd"] == 20
    assert [r["phase"] for r in result["tried"]] == ["baseline", "single", "single", "single", "combined"]
    assert result["done"] and not result["truncated"]


def test_swaps_that_lose_quality_are_rejected():
    evaluate, _ = scripted(lambda up, down: 1 if up == "tiny" else 10, lambda up, down: 0.6 if up == "tiny" else 0.9)
    result = asyncio.run(mr.search(SLOTS, {UP: cand("tiny")}, CASES, evaluate, tolerance=0.1))
    assert result["best"]["assignment"] == {}          # stays on the saved models
    assert result["tried"][1]["meets_target"] is False

    # with enough tolerance the cheap model is accepted
    result = asyncio.run(mr.search(SLOTS, {UP: cand("tiny")}, CASES, evaluate, tolerance=0.3))
    assert result["best"]["assignment"] == {UP: {"provider": "openai", "model": "tiny"}}


def test_combination_is_measured_not_assumed():
    # each swap alone is fine, together they break the pipeline: the combination is rejected
    evaluate, _ = scripted(lambda up, down: {"big": 10, "small": 5}[up] + {"big": 10, "small": 4}[down],
                           lambda up, down: 0.5 if (up, down) == ("small", "small") else 1.0)
    result = asyncio.run(mr.search(SLOTS, {UP: cand("small"), DOWN: cand("small")}, CASES, evaluate))
    assert result["best"]["assignment"] == {DOWN: {"provider": "openai", "model": "small"}}
    assert result["tried"][-1]["phase"] == "combined" and result["tried"][-1]["meets_target"] is False


def test_screening_skips_full_runs_for_bad_swaps():
    evaluate, runs = scripted(lambda up, down: 1 if up == "tiny" else 10, lambda up, down: 0.2 if up == "tiny" else 1.0)
    result = asyncio.run(mr.search(SLOTS, {UP: cand("tiny")}, CASES, evaluate, screen_cases=3))
    assert runs == [("big", "big", 10), ("tiny", "big", 3)]      # never ran "tiny" on all 10 cases
    assert result["best"]["assignment"] == {}


def test_budget_truncates_the_search():
    evaluate, runs = scripted(lambda up, down: 1, lambda up, down: 1.0)
    result = asyncio.run(mr.search(SLOTS, {UP: cand("a", "b", "c")}, CASES, evaluate, max_configs=2))
    assert len(runs) == 2 and result["truncated"]


def test_latency_objective_and_bad_objective():
    evaluate, _ = scripted(lambda up, down: 1, lambda up, down: 1.0)
    result = asyncio.run(mr.search(SLOTS, {}, CASES, evaluate, objective="latency"))
    assert result["best"]["phase"] == "baseline"
    with pytest.raises(ValueError):
        asyncio.run(mr.search(SLOTS, {}, CASES, evaluate, objective="vibes"))


# ── Overrides and the cost meter ──────────────────────────────────────────────

def test_override_swaps_the_model_and_drops_a_foreign_key():
    nodes = [{"id": "n1", "type": "llm", "data": {"provider": "openai", "model": "gpt-4o", "api_key": "sk-node",
                                                  "base_url": "https://proxy.example"}}]
    token = model_overrides.set({"app1:n1": {"provider": "openai", "model": "gpt-4o-mini"}})
    try:
        req = _build_llm_request("hi", "app1", nodes, [], {})
        assert (req.config.model, req.config.api_key) == ("gpt-4o-mini", "sk-node")
        model_overrides.set({"app1:n1": {"provider": "anthropic", "model": "claude-haiku-5-5"}})
        req = _build_llm_request("hi", "app1", nodes, [], {"anthropic": "sk-ant"})
        assert (req.config.provider, req.config.api_key) == ("anthropic", "sk-ant")
        assert not req.config.base_url
        assert _build_llm_request("hi", "other-app", nodes, [], {}).config.model == "gpt-4o"
    finally:
        model_overrides.reset(token)


def test_override_reaches_master_and_children():
    nodes = [{"id": "m", "type": "master_agent", "data": {"provider": "openai", "model": "gpt-4o"}},
             {"id": "c", "type": "child_agent", "data": {"kind": "llm", "role": "writer", "provider": "openai",
                                                         "model": "gpt-4o"}}]
    edges = [{"source": "m", "target": "c"}]
    token = model_overrides.set({"app1:m": {"provider": "openai", "model": "o4-mini"},
                                 "app1:c": {"provider": "openai", "model": "gpt-4o-mini"}})
    try:
        req = _build_master_request("goal", nodes, edges, {}, "app1")
    finally:
        model_overrides.reset(token)
    assert req.model == "o4-mini" and req.children[0].model == "gpt-4o-mini"


class FakeStream:
    def __init__(self, text, usage):
        self._text, self.usage = text, None
        self._final = usage

    async def __aiter__(self):
        yield llm.Chunk(text=self._text)
        self.usage = self._final
        yield llm.Chunk(finish_reason="stop", usage=self._final)


def test_meter_adds_up_completes_and_streams(env):
    usage = llm.Usage(prompt_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000)
    backend = llm.backend_for("openai")

    async def complete(req):
        return llm.LLMResponse(text="ok", usage=usage)

    async def stream(req):
        return FakeStream("ok", usage)

    env.setattr(backend, "complete", complete)
    env.setattr(backend, "stream", stream)
    price = llm.pricing.price_for("openai", "gpt-4o")["in"]

    async def go():
        req = llm.LLMRequest(provider="openai", model="gpt-4o", messages=[], api_key="sk-test")
        with llm.metered() as outer:
            await llm.complete(req)
            with llm.metered() as inner:
                s = await llm.stream(req)
                async for _ in s:
                    pass
        return outer, inner

    outer, inner = asyncio.run(go())
    assert inner.usd == pytest.approx(price) and inner.calls == 1
    assert outer.usd == pytest.approx(2 * price) and outer.calls == 2


# ── A whole study through the API ─────────────────────────────────────────────

keys_used = set()
ANSWERS = {"gpt-4o": "Paris", "gpt-4o-mini": "It is Paris.", "gpt-4.1": "London"}


@pytest.fixture(scope="module")
def stub_openai(env):
    seen = []

    async def stream(req):
        if req.api_key == "sk-revoked":
            raise llm.LLMError("openai returned HTTP 401: Incorrect API key provided", provider="openai", status=401)
        seen.append(req.model)
        keys_used.add(req.api_key)
        return FakeStream(ANSWERS[req.model], llm.Usage(prompt_tokens=1000, completion_tokens=100, total_tokens=1100))

    env.setattr(llm.backend_for("openai"), "stream", stream)
    return seen


def test_study_end_to_end(client, stub_openai):
    flow = {"nodes": [{"id": "a", "type": "llm", "data": {"label": "Answerer", "provider": "openai",
                                                          "model": "gpt-4o"}}], "edges": []}
    app_id = client.post("/api/apps", json={"name": "Capitals", "description": "", "flow_data": flow}).json()["id"]
    ds = client.post("/api/eval/datasets", json={"name": "capitals", "app_id": app_id}).json()
    for _ in range(3):
        client.post(f"/api/eval/datasets/{ds['id']}/cases", json={"prompt": "Capital of France?",
                                                                  "expected_output": "paris"})

    slots = client.post("/api/eval/optimize-models/slots", json={"app_id": app_id}).json()["slots"]
    assert [(s["key"], s["model"]) for s in slots] == [(f"{app_id}:a", "gpt-4o")]

    assert client.post("/api/eval/optimize-models", json={"app_id": app_id, "dataset_id": ds["id"]}).status_code == 422
    r = client.post("/api/eval/optimize-models", json={
        "app_id": app_id, "dataset_id": ds["id"], "provider_keys": {"openai": "sk-browser"},
        "candidates": [{"provider": "openai", "model": "gpt-4o-mini"}, {"provider": "openai", "model": "gpt-4.1"},
                       {"provider": "mock", "model": "mock-gpt-4"}],
    })
    assert r.status_code == 200, r.text
    study = r.json()
    assert study["status"] == "queued" and "provider_keys" not in study["request"]
    from tests.helpers import run_row
    assert "sk-browser" not in run_row("model_optimizations", study["id"])["request"]   # sealed at rest

    asyncio.run(mr.run_study(study["id"]))
    study = client.get(f"/api/eval/optimizations/{study['id']}").json()
    assert study["status"] == "done", study["error"]
    result = study["result"]
    assert result["best"]["assignment"] == {f"{app_id}:a": {"provider": "openai", "model": "gpt-4o-mini"}}
    assert result["best"]["cost_per_case_usd"] < result["baseline"]["cost_per_case_usd"]
    assert result["baseline"]["cost_per_case_usd"] > 0          # pipeline evals are priced now
    gpt41 = next(t for t in result["tried"] if t["assignment"].get(f"{app_id}:a", {}).get("model") == "gpt-4.1")
    assert gpt41["pass_rate"] == 0 and gpt41["meets_target"] is False
    assert any("mock/mock-gpt-4" in w for w in result["warnings"])
    assert set(stub_openai) == {"gpt-4o", "gpt-4o-mini", "gpt-4.1"}

    cases = client.get(f"/api/eval/optimizations/{study['id']}/cases?config={result['tried'].index(gpt41)}").json()
    assert [(c["output"], c["passed"]) for c in cases] == [("London", False)] * 3
    assert client.get(f"/api/eval/optimizations/{study['id']}/cases?config=0").json()[0]["prompt"] == "Capital of France?"
    assert client.get("/api/eval/optimizations/opt_nope/cases").status_code == 404

    listed = client.get(f"/api/eval/optimizations?app_id={app_id}").json()
    assert [s["id"] for s in listed] == [study["id"]]
    flow_after = json.loads(run_row("apps", app_id)["flow_data"])
    assert flow_after["nodes"][0]["data"]["model"] == "gpt-4o"   # the saved flow is never touched


def test_study_fails_when_a_node_would_run_simulated(client):
    flow = {"nodes": [{"id": "a", "type": "llm", "data": {"provider": "anthropic", "model": "claude-haiku-5-5"}}],
            "edges": []}
    app_id = client.post("/api/apps", json={"name": "No key", "description": "", "flow_data": flow}).json()["id"]
    ds = client.post("/api/eval/datasets", json={"name": "d"}).json()
    client.post(f"/api/eval/datasets/{ds['id']}/cases", json={"prompt": "hi"})
    study = client.post("/api/eval/optimize-models", json={
        "app_id": app_id, "dataset_id": ds["id"], "candidates": [{"provider": "openai", "model": "gpt-4o"}]}).json()
    asyncio.run(mr.run_study(study["id"]))
    study = client.get(f"/api/eval/optimizations/{study['id']}").json()
    assert study["status"] == "failed" and "simulated" in study["error"]


def test_apply_writes_the_best_models_to_the_draft(client, stub_openai):
    app_id = client.post("/api/apps", json={"name": "Apply me", "description": "", "flow_data": {"nodes": [
        {"id": "a", "type": "llm", "data": {"provider": "openai", "model": "gpt-4o"}}], "edges": []}}).json()["id"]
    client.post(f"/api/apps/{app_id}/publish")
    ds = client.post("/api/eval/datasets", json={"name": "apply"}).json()
    client.post(f"/api/eval/datasets/{ds['id']}/cases", json={"prompt": "Capital?", "expected_output": "paris"})
    study = client.post("/api/eval/optimize-models", json={
        "app_id": app_id, "app_version": 1, "dataset_id": ds["id"], "provider_keys": {"openai": "sk-browser"},
        "candidates": [{"provider": "openai", "model": "gpt-4o-mini"}]}).json()
    assert client.post(f"/api/eval/optimizations/{study['id']}/apply").status_code == 409   # not run yet
    asyncio.run(mr.run_study(study["id"]))

    r = client.post(f"/api/eval/optimizations/{study['id']}/apply")
    assert r.status_code == 200, r.text
    assert r.json() == {"applied": [{"key": f"{app_id}:a", "label": "llm", "provider": "openai",
                                     "model": "gpt-4o-mini"}], "skipped": []}
    from tests.helpers import run_row
    row = run_row("apps", app_id)
    assert row["status"] == "draft"
    assert json.loads(row["flow_data"])["nodes"][0]["data"]["model"] == "gpt-4o-mini"


def _capitals_study(client, provider_keys):
    app_id = client.post("/api/apps", json={"name": "Keys", "description": "", "flow_data": {"nodes": [
        {"id": "a", "type": "llm", "data": {"provider": "openai", "model": "gpt-4o"}}], "edges": []}}).json()["id"]
    ds = client.post("/api/eval/datasets", json={"name": "keys"}).json()
    client.post(f"/api/eval/datasets/{ds['id']}/cases", json={"prompt": "Capital?", "expected_output": "paris"})
    study = client.post("/api/eval/optimize-models", json={
        "app_id": app_id, "dataset_id": ds["id"], "provider_keys": provider_keys,
        "candidates": [{"provider": "openai", "model": "gpt-4o-mini"}]}).json()
    asyncio.run(mr.run_study(study["id"]))
    return client.get(f"/api/eval/optimizations/{study['id']}").json()


def test_vault_key_refs_reach_the_provider_as_the_key(client, stub_openai):
    # Settings → keys in the vault: the browser sends a "secret://" ref, not the key
    from services import secret_store
    from tests.helpers import hdr
    secret = secret_store.create_secret(hdr()["x-tenant-id"], hdr()["x-project-id"], "user_admin",
                                        "openai", "sk-from-vault", kind="llm")
    keys_used.clear()
    study = _capitals_study(client, {"openai": f"secret://{secret['id']}"})
    assert study["status"] == "done", study["error"]
    assert keys_used == {"sk-from-vault"}


def test_study_fails_with_the_error_when_every_baseline_case_fails(client, stub_openai):
    study = _capitals_study(client, {"openai": "sk-revoked"})
    assert study["status"] == "failed"
    assert "Every case failed on the saved models" in study["error"] and "401" in study["error"]


def test_zero_baseline_pass_rate_fails_instead_of_picking_the_cheapest():
    evaluate, runs = scripted(lambda up, down: 1 if up == "tiny" else 10, lambda up, down: 0.0)
    with pytest.raises(ValueError, match="pass none of the cases"):
        asyncio.run(mr.search(SLOTS, {UP: cand("tiny")}, CASES, evaluate))
    assert len(runs) == 1      # stopped after the baseline, no money spent on swaps


def test_progress_reports_the_config_and_case_being_run():
    seen = []

    async def evaluate(assignment, subset, tick):
        outcomes = [mr.CaseOutcome(1.0, i != 1, 1.0, 10) for i in range(len(subset))]
        for o in outcomes:
            await tick(o)
        return mr.summarize(assignment, "", outcomes)

    async def progress(state):
        cur = state["current"] or {}
        seen.append((cur.get("cases_done"), cur.get("passed"), cur.get("index")))
        assert state["planned_configs"] == 3      # baseline + 1 swap + room for 1 combination

    result = asyncio.run(mr.search(SLOTS, {UP: cand("small")}, CASES[:3], evaluate, on_progress=progress))
    assert seen[:3] == [(1, 1, 0), (2, 1, 0), (3, 2, 0)] and result["current"] is None


def _study(client, flow, dataset_cases, **extra):
    app_id = client.post("/api/apps", json={"name": extra.pop("name", "S"), "description": "",
                                            "flow_data": flow}).json()["id"]
    ds = client.post("/api/eval/datasets", json={"name": "d"}).json()
    for prompt in dataset_cases:
        client.post(f"/api/eval/datasets/{ds['id']}/cases", json={"prompt": prompt, "expected_output": "paris"})
    body = {"app_id": app_id, "dataset_id": ds["id"], "provider_keys": {"openai": "sk-browser"},
            "candidates": [{"provider": "openai", "model": "gpt-4o-mini"}], **extra}
    r = client.post("/api/eval/optimize-models", json=body)
    assert r.status_code == 200, r.text
    return app_id, r.json()


def test_only_the_chosen_nodes_are_optimized(client, env):
    async def complete(req):
        return llm.LLMResponse(text="Paris", usage=llm.Usage(prompt_tokens=100, completion_tokens=10, total_tokens=110))
    env.setattr(llm.backend_for("openai"), "complete", complete)
    flow = {"nodes": [
        {"id": "m", "type": "master_agent", "data": {"provider": "openai", "model": "gpt-4o", "strategy": "sequential"}},
        {"id": "w", "type": "child_agent", "data": {"kind": "llm", "role": "Writer", "provider": "openai", "model": "gpt-4o"}},
    ], "edges": [{"source": "m", "target": "w"}]}
    app_id, study = _study(client, flow, ["Capital?"], name="Crew", slot_keys=["gone:node"])
    asyncio.run(mr.run_study(study["id"]))
    assert "None of the chosen nodes" in client.get(f"/api/eval/optimizations/{study['id']}").json()["error"]

    r = client.post("/api/eval/optimize-models", json={**study["request"], "app_id": app_id,
                                                       "dataset_id": study["dataset_id"], "slot_keys": [f"{app_id}:w"],
                                                       "provider_keys": {"openai": "sk-browser"}})
    asyncio.run(mr.run_study(r.json()["id"]))
    done = client.get(f"/api/eval/optimizations/{r.json()['id']}").json()
    assert done["status"] == "done", done["error"]
    result = done["result"]
    assert [s["key"] for s in result["slots"]] == [f"{app_id}:w"]          # the master keeps its model
    assert [list(t["assignment"]) for t in result["tried"]] == [[], [f"{app_id}:w"]]


def test_cases_of_a_config_run_in_parallel(client, env):
    live = {"now": 0, "max": 0}

    async def stream(req):
        live["now"] += 1
        live["max"] = max(live["max"], live["now"])
        await asyncio.sleep(0.05)
        live["now"] -= 1
        return FakeStream("Paris", llm.Usage(prompt_tokens=10, completion_tokens=2, total_tokens=12))
    env.setattr(llm.backend_for("openai"), "stream", stream)
    flow = {"nodes": [{"id": "a", "type": "llm", "data": {"provider": "openai", "model": "gpt-4o"}}], "edges": []}
    _, study = _study(client, flow, [f"q{i}" for i in range(6)], name="Par", parallel=3)
    asyncio.run(mr.run_study(study["id"]))
    study = client.get(f"/api/eval/optimizations/{study['id']}").json()
    assert study["status"] == "done", study["error"]
    assert live["max"] == 3
    assert len(client.get(f"/api/eval/optimizations/{study['id']}/cases?config=0").json()) == 6


def test_cancel_a_queued_study(client):
    flow = {"nodes": [{"id": "a", "type": "llm", "data": {"provider": "openai", "model": "gpt-4o"}}], "edges": []}
    _, study = _study(client, flow, ["q"], name="Cancel me")
    r = client.post(f"/api/eval/optimizations/{study['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    from tests.helpers import run_row
    assert run_row("jobs", study["job_id"])["status"] == "dead"
    asyncio.run(mr.run_study(study["id"]))                  # a worker that picks it up anyway does nothing
    assert client.get(f"/api/eval/optimizations/{study['id']}").json()["status"] == "cancelled"
    assert client.post(f"/api/eval/optimizations/{study['id']}/cancel").status_code == 409
    assert client.post("/api/eval/optimizations/opt_nope/cancel").status_code == 404


def test_a_running_study_stopped_by_cancel_is_cancelled_and_one_that_crashed_failed(client):
    flow = {"nodes": [{"id": "a", "type": "llm", "data": {"provider": "openai", "model": "gpt-4o"}}], "edges": []}
    for reason, status in (("Cancelled", "cancelled"), ("worker died", "failed")):
        _, study = _study(client, flow, ["q"], name=f"Dead {status}")
        asyncio.run(mr._on_dead({"study_id": study["id"]}, None, reason))
        assert client.get(f"/api/eval/optimizations/{study['id']}").json()["status"] == status
