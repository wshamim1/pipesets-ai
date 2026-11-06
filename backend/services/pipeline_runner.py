"""
pipeline_runner.py — run a *published* app (pipeline) as a child of a Master Agent.

The Build canvas resolves wiring (which tools / skills / memory / cache / retriever
are attached to the LLM node) in the browser.  This module ports that resolution
to the backend so a saved flow can be executed server-side:

* flow with an LLM node    -> single streamed LLM run (RAG, tools, skills, memory, cache)
* flow with a master agent -> nested master/child run (children may be LLM, external
                              or pipeline kinds, so pipelines can nest)

Safety
------
* Only apps with ``status == 'published'`` run (a published app cannot be edited
  until someone clicks Edit, which flips it back to draft).
* Tenant / project scope comes from the calling request, and the caller needs
  ``apps:read`` access.
* Cycles (A -> B -> A) and runaway nesting (> MAX_DEPTH) are rejected.
"""

import asyncio
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Set, Tuple

from db import get_db_connection
from models import PromptRunRequest
from services.acl import has_access
from services import secret_store
from services.request_context import RequestContext

logger = logging.getLogger("pipesets-ai-backend")

MAX_DEPTH = 3
ERROR_PREFIX = "[Error from pipeline agent"

DB_MCP_TOOLS = {"mcp_postgres", "mcp_database"}
CONN_TYPE_TO_DB = {"postgres": "postgres", "postgresql": "postgres", "mysql": "mysql",
                   "mariadb": "mysql", "sqlite": "sqlite"}


@dataclass(frozen=True)
class RunScope:
    tenant_id: str
    project_id: str
    user_id: str
    chain: Tuple[str, ...] = ()   # app ids currently executing (cycle detection)
    caller: str = ""              # who started the run, e.g. "key:<id>" on /v1 (rate limits); "" = user_id
    # provider -> API key, forwarded by the browser (saved flows don't store global keys)
    provider_keys: Dict[str, str] = None  # type: ignore[assignment]
    # who long-term memory is about: the signed-in user on interactive runs, the /v1 caller's
    # ``user`` field on API runs, "" (no long-term memory) when there is no person, e.g. schedules
    end_user: str = ""
    # the batch run this run is a row of (services/batches.py): Structured Extract files its fields in
    # the review queue under the batch's name when its node names no batch of its own
    batch: str = ""


current_scope: ContextVar[Optional[RunScope]] = ContextVar("pipeline_run_scope", default=None)

# slot_key(app id, node id) -> {"provider", "model"}: the model a node uses instead of its saved one,
# for this run and any pipeline it calls (Evaluate → Optimize models tries assignments this way)
model_overrides: ContextVar[Dict[str, Dict[str, str]]] = ContextVar("pipeline_model_overrides", default={})


def slot_key(run_key: str, node_id: str) -> str:
    return f"{run_key}:{node_id}"


def _with_model(run_key: str, node: Dict[str, Any]) -> Dict[str, Any]:
    """The node's data with its override applied. A different provider drops the node's own key
    and base URL, so the run uses the caller's or the project's key for the new provider."""
    d = node.get("data", {}) or {}
    o = model_overrides.get().get(slot_key(run_key, node.get("id", "")))
    if not o:
        return d
    d = {**d, "model": o["model"]}
    if (o["provider"] or "").lower() != str(d.get("provider") or "").lower():
        d.update(provider=o["provider"], api_key="", base_url=None)
    return d


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_published_app(app_id: str, scope: RunScope, version: int = 0) -> Dict[str, Any]:
    """Load a published app. ``version`` > 0 pins an immutable snapshot; 0 means the current one."""
    ctx = RequestContext(tenant_id=scope.tenant_id, project_id=scope.project_id, user_id=scope.user_id)
    if not has_access(ctx, "apps", "read"):
        raise PermissionError("No read access to apps")

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, name, flow_data, status, version FROM apps "
            "WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (app_id, scope.tenant_id, scope.project_id),
        ).fetchone()
        snap = conn.execute(
            "SELECT flow_data FROM app_versions WHERE app_id = ? AND version = ? AND tenant_id = ? AND project_id = ?",
            (app_id, version, scope.tenant_id, scope.project_id),
        ).fetchone() if row and version > 0 else None
    finally:
        conn.close()

    if not row:
        raise LookupError(f"Pipeline '{app_id}' not found")
    if version > 0:
        if not snap:
            raise LookupError(f"Pipeline '{row['name']}' v{version} is not available — pick another version")
        raw = snap["flow_data"]
    else:
        if row["status"] != "published":
            raise ValueError(f"Pipeline '{row['name']}' is not published (status: {row['status']})")
        raw = row["flow_data"]
        version = row["version"] or 0
    try:
        flow = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Pipeline '{row['name']}' has corrupt flow data") from e
    return {"id": row["id"], "name": row["name"], "version": version, "flow": flow}


def _neighbours(node_id: str, edges: List[Dict[str, Any]]) -> Set[str]:
    out: Set[str] = set()
    for e in edges:
        if e.get("source") == node_id:
            out.add(e.get("target"))
        elif e.get("target") == node_id:
            out.add(e.get("source"))
    return out


def _pipeline_children_in_order(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pipeline child nodes ordered by walking edges from the Start node (unreached ones last)."""
    children = [n for n in nodes if n.get("type") == "child_agent" and n.get("data", {}).get("kind") == "pipeline"]
    if not children:
        return []
    out_edges: Dict[str, List[str]] = {}
    for e in edges:
        out_edges.setdefault(e.get("source"), []).append(e.get("target"))
    rank: Dict[str, int] = {}
    queue = [n["id"] for n in nodes if n.get("type") == "start"]
    seen = set(queue)
    while queue:
        nid = queue.pop(0)
        rank.setdefault(nid, len(rank))
        for t in out_edges.get(nid, []):
            if t not in seen:
                seen.add(t)
                queue.append(t)
    return sorted(children, key=lambda n: rank.get(n["id"], len(nodes)))


async def _run_pipeline_chain(
    children: List[Dict[str, Any]], task: str, context: str, timeout_ms: int, telemetry: Dict[str, Any],
) -> str:
    """Run pipeline children one after another; each sees the previous output as context."""
    output = ""
    for n in children:
        d = n.get("data", {})
        output, t = await run_published_pipeline(
            str(d.get("app_id") or ""), task, context, int(d.get("timeout_ms") or timeout_ms),
            int(d.get("app_version") or 0),
        )
        telemetry["effective_model"] = t.get("effective_model", telemetry.get("effective_model"))
        if output.startswith(ERROR_PREFIX):
            return output
        context = output
    return output


def _resolve_key(provider: str, node_key: str, provider_keys: Dict[str, str]) -> str:
    """Node key, else the caller's key for the provider, else the project's default key from
    the secrets vault (as a "secret://" ref — decrypted only at the LLM call)."""
    if node_key and node_key.strip():
        return node_key.strip()
    p = (provider or "").lower()
    if p == "azure":
        p = "openai"
    return provider_keys.get(p, "") or secret_store.default_ref(p)


def _merge_connection(tool: Dict[str, Any], nodes: List[Dict[str, Any]], linked: Set[str]) -> Dict[str, Any]:
    """Credentials for DB-backed MCP tools come only from the linked connection node."""
    if tool.get("toolId") not in DB_MCP_TOOLS:
        return tool
    conn_node = next((n for n in nodes if n.get("type") == "connection" and n.get("id") in linked), None)
    if not conn_node:
        return tool
    cd = conn_node.get("data", {})
    c = cd.get("config") or {}
    ctype = cd.get("connection_type", "")
    base_cfg = tool.get("config") or {}
    return {**tool, "config": {
        "transport": base_cfg.get("transport", "native"),
        "read_only": base_cfg.get("read_only", True),
        "db_type": CONN_TYPE_TO_DB.get(ctype, ctype),
        "connection_type": ctype,
        "host": c.get("host"), "port": c.get("port"), "database": c.get("database"),
        "user": c.get("user"), "password": c.get("password"),
    }}


def _middleware_configs(
    node_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
) -> Optional[List[Dict[str, Any]]]:
    """Middleware nodes wired to node_id, in the backend's middleware_configs shape."""
    linked = _neighbours(node_id, edges)
    configs = [
        {"type": d.get("middleware_type"), "config": d.get("config") or {}, "enabled": d.get("enabled", True) is not False}
        for d in (n.get("data", {}) for n in nodes if n.get("type") == "middleware" and n.get("id") in linked)
    ]
    return configs or None


def _human_gate(
    node_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """The human_gate node wired to node_id, if any (first one wins)."""
    linked = _neighbours(node_id, edges)
    gate = next((n for n in nodes if n.get("type") == "human_gate" and n.get("id") in linked), None)
    return dict(gate.get("data", {})) if gate else None


def _checkpointer(
    node_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Config of the Checkpointer node wired to node_id, else of any on the canvas (it applies to
    the whole run), in the shape of ``checkpoint`` on run requests. None: the defaults."""
    linked = _neighbours(node_id, edges)
    cps = [n for n in nodes if n.get("type") == "checkpointer"]
    node = next((n for n in cps if n.get("id") in linked), cps[0] if cps else None)
    if not node:
        return None
    d = node.get("data", {}) or {}
    return {"save_steps": d.get("save_steps", True) is not False,
            "restore_on_resume": d.get("restore_on_resume", True) is not False}


def _clean(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != ""}


def _attached(
    node_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(tools, skills) wired to an LLM node or child agent: Tool nodes (with their Connection
    node's credentials), Toolkit nodes, and Skill nodes."""
    linked = _neighbours(node_id, edges)
    tools: List[Dict[str, Any]] = []
    for n in nodes:
        if n.get("id") not in linked:
            continue
        if n.get("type") == "tool":
            tools.append(_merge_connection(n.get("data", {}), nodes, _neighbours(n["id"], edges)))
        elif n.get("type") == "toolkit":
            tools.append(n.get("data", {}))
    skills = [n.get("data", {}) for n in nodes if n.get("type") == "skill" and n.get("id") in linked]
    return tools, skills


def selected_llm_node(nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The LLM node a single-LLM flow runs: the selected one, else the first."""
    llm_nodes = [n for n in nodes if n.get("type") == "llm"]
    if not llm_nodes:
        return None
    return next((n for n in llm_nodes if n.get("data", {}).get("isSelected")), llm_nodes[0])


def _build_llm_request(
    prompt: str, app_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
    provider_keys: Dict[str, str], retrieval_query: Optional[str] = None,
) -> Optional[PromptRunRequest]:
    llm = selected_llm_node(nodes)
    if llm is None:
        return None
    d = _with_model(app_id, llm)
    linked = _neighbours(llm["id"], edges)

    def connected(kind: str) -> Optional[Dict[str, Any]]:
        return next((n for n in nodes if n.get("type") == kind and n.get("id") in linked), None)

    tools, skills = _attached(llm["id"], nodes, edges)

    mem = (connected("memory") or {}).get("data")
    cache = (connected("cache") or {}).get("data")
    parser = (connected("output_parser") or next((n for n in nodes if n.get("type") == "output_parser"), None) or {}).get("data")
    retriever = next((n for n in nodes if n.get("type") == "retriever"), None)

    provider = d.get("provider", "openai")
    fb_provider = d.get("fallback_provider") or ""
    config = _clean({
        "provider": provider, "model": d.get("model"),
        "temperature": d.get("temperature"), "max_tokens": d.get("max_tokens"), "top_p": d.get("top_p"),
        "api_key": _resolve_key(provider, d.get("api_key", ""), provider_keys),
        "system_prompt": d.get("system_prompt"), "base_url": d.get("base_url"),
        "timeout_ms": d.get("timeout_ms"), "max_retries": d.get("max_retries"),
        "retry_backoff_ms": d.get("retry_backoff_ms"),
        "fallback_provider": fb_provider, "fallback_model": d.get("fallback_model"),
        "fallback_api_key": _resolve_key(fb_provider, d.get("fallback_api_key", ""), provider_keys) if fb_provider else "",
        "fallback_base_url": d.get("fallback_base_url"),
    })

    retriever_config = None
    if retriever:
        r = retriever.get("data", {})
        retriever_config = {
            "collection_name": r.get("collection_name"), "top_k": r.get("top_k", 5),
            "score_threshold": r.get("score_threshold", 0), "search_type": r.get("search_type"),
            "rerank": r.get("rerank", False),
            "embedding_provider": r.get("embedding_provider", "local"),
            "embedding_model": r.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2"),
            "embedding_api_key": _resolve_key(r.get("embedding_provider", ""), r.get("embedding_api_key", ""), provider_keys),
        }

    return PromptRunRequest(
        prompt=prompt, retrieval_query=retrieval_query, app_id=app_id, node_id=llm["id"], config=config,
        attached_tools=tools, attached_skills=skills,
        skill_mode=d.get("skill_mode") if d.get("skill_mode") in ("on_demand", "always") else None,
        max_active_skills=d.get("max_active_skills") if isinstance(d.get("max_active_skills"), int)
        and 1 <= d["max_active_skills"] <= 10 else None,
        session_id=(mem or {}).get("session_id"),
        memory_config=({"strategy": mem.get("strategy"), "token_budget": mem.get("token_budget"),
                        "session_ttl_hours": mem.get("session_ttl_hours"), "long_term": bool(mem.get("long_term")),
                        "recall_k": mem.get("recall_k"), "extract": mem.get("extract_facts", True)} if mem else None),
        cache_config=({"scope": cache.get("scope"), "ttl_seconds": cache.get("ttl_seconds"),
                       "max_size": cache.get("max_size")} if cache else None),
        middleware_configs=_middleware_configs(llm["id"], nodes, edges),
        retriever_config=retriever_config,
        output_parser=({"parser_type": parser.get("parser_type"), "schema_json": parser.get("schema_json"),
                        "strict": parser.get("strict")} if parser else None),
        checkpoint=_checkpointer(llm["id"], nodes, edges),
    )


async def _consume_stream(req: PromptRunRequest) -> Tuple[str, Optional[str], Dict[str, Any]]:
    from services.llm_runner import run_stream  # lazy: llm_runner imports routers

    text: List[str] = []
    error: Optional[str] = None
    meta: Dict[str, Any] = {}
    async for chunk in run_stream(req):
        if not chunk.startswith("data: "):
            continue
        try:
            ev = json.loads(chunk[6:])
        except json.JSONDecodeError:
            continue
        kind = ev.get("type")
        if kind == "token":
            text.append(ev.get("text", ""))
        elif kind == "error":
            error = ev.get("message") or "Unknown error"
            if ev.get("retract"):   # response guardrail blocked what already streamed
                text.clear()
        elif kind == "meta":
            meta = ev
    return "".join(text), error, meta


def _build_master_request(
    goal: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], provider_keys: Dict[str, str],
    run_key: str = "",
):
    from routers.agents import ChildAgentConfig, MasterAgentRunRequest  # lazy: avoids circular import

    master = next(n for n in nodes if n.get("type") == "master_agent")
    md = _with_model(run_key, master)
    linked = _neighbours(master["id"], edges)
    child_fields = set(ChildAgentConfig.model_fields)

    children = []
    for n in nodes:
        if n.get("type") != "child_agent" or n.get("id") not in linked:
            continue
        cd = {k: v for k, v in _with_model(run_key, n).items() if k in child_fields and v is not None}
        cd["agent_id"] = n["id"]
        cd["api_key"] = _resolve_key(cd.get("provider", ""), cd.get("api_key", ""), provider_keys)
        cd["middleware_configs"] = _middleware_configs(n["id"], nodes, edges)
        cd["human_gate"] = _human_gate(n["id"], nodes, edges)
        cd["attached_tools"], cd["attached_skills"] = _attached(n["id"], nodes, edges)
        children.append(ChildAgentConfig(**cd))

    mp = md.get("provider", "openai")
    master_fields = set(MasterAgentRunRequest.model_fields)
    kwargs = {k: v for k, v in md.items() if k in master_fields and v is not None and k not in ("goal", "children")}
    kwargs["api_key"] = _resolve_key(mp, md.get("api_key", ""), provider_keys)
    kwargs["middleware_configs"] = _middleware_configs(master["id"], nodes, edges)
    kwargs["human_gate"] = _human_gate(master["id"], nodes, edges)
    kwargs["checkpoint"] = _checkpointer(master["id"], nodes, edges)
    return MasterAgentRunRequest(goal=goal, children=children, **kwargs)


def master_resume_request(run_id: str, goal: str, app_id: str, scope: RunScope):
    """The request that resumes Master Agent run ``run_id`` of published app ``app_id``, with
    ``scope``'s provider keys. Returns (app, request); raises LookupError / ValueError /
    PermissionError when the app can't run."""
    app = _load_published_app(app_id, scope)
    nodes, edges = app["flow"].get("nodes", []), app["flow"].get("edges", [])
    sub = _build_master_request(goal, nodes, edges, scope.provider_keys or {}, app_id)
    sub.provider_keys = scope.provider_keys or {}
    sub.resume_from = run_id
    return app, sub


def llm_rerun_request(run: Dict[str, Any], scope: RunScope) -> PromptRunRequest:
    """The request that re-runs single-LLM run ``run`` (an agent_runs row) from a step, built from
    its app's current flow — draft or published, so a fix made on the canvas since applies. It
    writes nothing to the run's memory session or the cache: a re-run is an experiment, and the
    history it starts from is the one saved with the run. Raises LookupError / PermissionError /
    ValueError when the app can't run."""
    ctx = RequestContext(tenant_id=scope.tenant_id, project_id=scope.project_id, user_id=scope.user_id)
    if not has_access(ctx, "apps", "read"):
        raise PermissionError("No read access to apps")
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT name, flow_data FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (run["app_id"], scope.tenant_id, scope.project_id)).fetchone()
    finally:
        conn.close()
    if not row:
        raise LookupError(f"Pipeline '{run['app_id']}' not found")
    try:
        flow = json.loads(row["flow_data"] or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Pipeline '{row['name']}' has corrupt flow data") from e
    req = _build_llm_request(run["goal"], run["app_id"], flow.get("nodes", []), flow.get("edges", []),
                             scope.provider_keys or {}, retrieval_query=run["goal"])
    if req is None:
        raise ValueError(f"Pipeline '{row['name']}' no longer has an LLM node")
    req.session_id, req.memory_config, req.cache_config = None, None, None
    return req


# ── Public entry point ────────────────────────────────────────────────────────

async def run_published_pipeline(
    app_id: str, task: str, context: str, timeout_ms: int, version: int = 0,
) -> Tuple[str, Dict[str, Any]]:
    """Execute a published app (a pinned ``version``, or the current one when 0).
    Never raises; errors come back as text."""
    scope = current_scope.get()
    telemetry: Dict[str, Any] = {
        "attempt_count": 1, "used_fallback": False,
        "effective_provider": "pipeline", "effective_model": app_id,
    }
    if scope is None:
        return f"{ERROR_PREFIX}]: no run scope available", telemetry

    try:
        if not app_id:
            raise ValueError("No pipeline selected")
        if app_id in scope.chain:
            raise ValueError(f"Circular pipeline reference: {' -> '.join(scope.chain + (app_id,))}")
        if len(scope.chain) >= MAX_DEPTH:
            raise ValueError(f"Pipelines nested deeper than {MAX_DEPTH} levels")
        app = _load_published_app(app_id, scope, version)
    except Exception as e:
        logger.warning(f"Pipeline child failed [{app_id}]: {e}")
        return f"{ERROR_PREFIX}]: {e}", telemetry

    telemetry["effective_model"] = f"{app['name']} v{app['version']}"
    return await run_flow(app_id, app["name"], app["flow"], task, context, timeout_ms, telemetry)


def walk_flows(
    flow: Dict[str, Any], scope: RunScope, run_key: str = "",
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """``flow`` plus every published pipeline it calls, followed recursively at their pinned
    versions. Returns ([{source, flow, app_id, name, version, depth, called_from}], errors);
    the first entry is ``flow`` itself (source "this pipeline"). Never raises."""
    visited: List[Dict[str, Any]] = []
    errors: List[str] = []

    def walk(fl: Dict[str, Any], source: str, chain: Tuple[str, ...], meta: Dict[str, Any]) -> None:
        visited.append({"source": source, "flow": fl, **meta})
        for n in fl.get("nodes", []):
            d = n.get("data", {}) or {}
            if n.get("type") != "child_agent" or d.get("kind") != "pipeline" or not d.get("app_id"):
                continue
            app_id, version = str(d["app_id"]), int(d.get("app_version") or 0)
            label = d.get("app_name") or d.get("label") or app_id
            if app_id in chain:
                errors.append(f"Circular reference to '{label}'")
                continue
            if len(chain) > MAX_DEPTH:
                errors.append(f"'{label}' is nested deeper than {MAX_DEPTH} levels")
                continue
            try:
                app = _load_published_app(app_id, scope, version)
            except Exception as e:
                errors.append(str(e))
                continue
            walk(app["flow"], f"{app['name']} v{app['version']}", chain + (app_id,), {
                "app_id": app_id, "name": app["name"], "version": app["version"],
                "depth": len(chain), "called_from": source,
            })

    walk(flow, "this pipeline", (run_key,) if run_key else (), {})
    return visited, errors


def summarize_flow(flow: Dict[str, Any], scope: RunScope, run_key: str = "") -> Dict[str, Any]:
    """What a run of ``flow`` will use, including every pipeline it calls (at their pinned
    versions, recursively): models, tools, memory/cache, and the called pipelines.
    Never raises; unreachable pipelines are reported in ``errors``."""
    models: Dict[str, Dict[str, Any]] = {}
    tools: List[Dict[str, Any]] = []
    flags = {"memory": False, "cache": False}

    def add_model(provider: str, model: str, source: str) -> None:
        if not (provider or model):
            return
        entry = models.setdefault(f"{provider}/{model}", {"provider": provider, "model": model, "sources": []})
        if source not in entry["sources"]:
            entry["sources"].append(source)

    visited, errors = walk_flows(flow, scope, run_key)
    for v in visited:
        source = v["source"]
        for n in v["flow"].get("nodes", []):
            t, d = n.get("type"), n.get("data", {}) or {}
            if t in ("llm", "master_agent") or (t == "child_agent" and (d.get("kind") or "llm") == "llm"):
                add_model(str(d.get("provider") or ""), str(d.get("model") or ""), source)
            elif t == "tool":
                tools.append({"name": d.get("label") or d.get("toolId") or "tool", "source": source})
            elif t == "toolkit":
                subs = d.get("subTools") or []
                names = [st.get("label") or st.get("name") or st.get("id") for st in subs if isinstance(st, dict)]
                for name in names or [d.get("label") or "toolkit"]:
                    tools.append({"name": name, "source": source})
            elif t == "memory":
                flags["memory"] = True
            elif t == "cache":
                flags["cache"] = True

    return {
        "models": list(models.values()),
        "tools": tools,
        "memory": flags["memory"],
        "cache": flags["cache"],
        "pipelines": [
            {k: v[k] for k in ("app_id", "name", "version", "depth", "called_from")} for v in visited[1:]
        ],
        "errors": errors,
    }


async def run_flow(
    run_key: str, name: str, flow: Dict[str, Any], task: str, context: str, timeout_ms: int,
    telemetry: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Execute a flow definition under the current RunScope. ``run_key`` identifies the run
    for cycle detection, caches and traces (an app id, or e.g. a marketplace listing id).
    Never raises; errors come back as text."""
    scope = current_scope.get()
    telemetry = telemetry if telemetry is not None else {
        "attempt_count": 1, "used_fallback": False, "effective_provider": "pipeline", "effective_model": name,
    }
    if scope is None:
        return f"{ERROR_PREFIX}]: no run scope available", telemetry

    try:
        nodes: List[Dict[str, Any]] = flow.get("nodes", [])
        edges: List[Dict[str, Any]] = flow.get("edges", [])
        prompt = f"Context from previous steps:\n{context}\n\nYour task:\n{task}" if context else task

        provider_keys = scope.provider_keys or {}
        # Children of a nested master must see this run in the cycle chain.
        token = current_scope.set(replace(scope, chain=scope.chain + (run_key,)))
        try:
            timeout_s = max(1000, int(timeout_ms or 45000)) / 1000.0
            if any(n.get("type") == "master_agent" for n in nodes):
                from routers.agents import _execute_master  # lazy: avoids circular import
                sub = _build_master_request(prompt, nodes, edges, provider_keys, run_key)
                final, steps = await asyncio.wait_for(_execute_master(sub), timeout=timeout_s)
                telemetry["attempt_count"] = max([s.attempt_count for s in steps] or [1])
                return final, telemetry

            # No LLM of its own — the flow only delegates to published pipelines.
            chain = _pipeline_children_in_order(nodes, edges)
            if chain and not any(n.get("type") == "llm" for n in nodes):
                return await asyncio.wait_for(
                    _run_pipeline_chain(chain, task, context, timeout_ms, telemetry), timeout=timeout_s,
                ), telemetry

            # Retrieve with the bare task: the prior-step context would swamp the embedding.
            req = _build_llm_request(prompt, run_key, nodes, edges, provider_keys, retrieval_query=task)
            if req is None:
                raise ValueError(f"Pipeline '{name}' has no LLM, Master Agent or Pipeline node to run")
            text, error, meta = await asyncio.wait_for(_consume_stream(req), timeout=timeout_s)
            if meta.get("model"):
                telemetry["effective_provider"] = f"pipeline:{meta.get('provider', '')}"
            if error and not text:
                return f"{ERROR_PREFIX}]: {error}", telemetry
            return text, telemetry
        finally:
            current_scope.reset(token)
    except asyncio.TimeoutError:
        return f"{ERROR_PREFIX}]: timed out after {timeout_ms} ms", telemetry
    except Exception as e:
        logger.warning(f"Pipeline child failed [{run_key}]: {e}")
        return f"{ERROR_PREFIX}]: {e}", telemetry
