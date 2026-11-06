"""
LLM runner service — streaming model calls (through the llm gateway), ReAct loop, tool
resolution, SSE formatting, memory/cache persistence, and trace writing.

Exposed API:
    run_stream(req)  →  AsyncIterator[str]  (SSE chunks)
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

import llm
from db import get_db_connection
from models import LLMConfig, PromptRunRequest
from services import llm_checkpoint
from services.checkpoint import Checkpointer
from services import debug_run, skills_runtime
from routers.cache import make_cache_key, cache_get, cache_set
from routers.memory import trim_to_budget, rough_token_count
from routers.middleware import (
    DEFAULT_EMPTY_MESSAGE, GROUNDING_EMPTY_INSTRUCTION, GROUNDING_INSTRUCTION,
    check_prompt_middleware, check_response_middleware, get_grounding_config, is_empty_tool_output,
    redact_pii,
)
from services.guardrail_judge import check_custom_rules
from routers.run import get_current_config
from routers.tools import execute_tool_real
from routers.traces import write_trace
from services import long_term_memory as ltm
from services.tool_signature import LEGACY_SCHEMA
from services.budget import check_budget

logger = logging.getLogger("pipesets-ai-backend")

MAX_AGENT_STEPS = 8

# Providers with native function-calling
TOOL_CALL_PROVIDERS = {"openai", "anthropic", "groq", "gemini", "bedrock", "azure", "cohere", "mistral",
                       "together", "fireworks", "deepseek", "xai", "cerebras", "nvidia", "watsonx"}

# Providers that need pre-execution tool injection (no native function-calling)
INJECT_PROVIDERS = {"ollama", "llamacpp", "jan", "huggingface", "mock"}


# ── SSE helper ────────────────────────────────────────────────────────────────


def _trace_event(span: Dict[str, Any]) -> Dict[str, Any]:
    """A finished LLM / tool call as a stream event, for live per-step timings:
    {"type": "trace", "span": "llm" | "tool", "name", "step", "start_ms", "duration_ms"}."""
    return {"type": "trace", "span": span["span_type"], "name": span["name"], "step": span["step"],
            "start_ms": span["start_ms"], "duration_ms": span["latency_ms"]}

def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# ── Mock streamer ─────────────────────────────────────────────────────────────

async def _mock_stream(text: str, chunk: int = 4, delay: float = 0.018) -> AsyncIterator[str]:
    for i in range(0, len(text), chunk):
        yield _sse({"type": "token", "text": text[i: i + chunk]})
        await asyncio.sleep(delay)


def _provider_needs_key(provider: str) -> bool:
    p = provider.lower()
    return p not in {"mock", "local", "ollama", "llamacpp", "jan", "huggingface"}


def _iter_policy_configs(cfg: LLMConfig) -> List[Tuple[LLMConfig, bool]]:
    items: List[Tuple[LLMConfig, bool]] = [(cfg, False)]
    fallback_provider = (cfg.fallback_provider or "").strip()
    fallback_model = (cfg.fallback_model or "").strip()
    if fallback_provider == "mock":
        return items
    if fallback_provider and fallback_model:
        fallback_cfg = cfg.model_copy(update={
            "provider": fallback_provider,
            "model": fallback_model,
            "api_key": (cfg.fallback_api_key or cfg.api_key or "").strip(),
            "base_url": cfg.fallback_base_url or cfg.base_url,
        })
        if fallback_cfg.provider != cfg.provider or fallback_cfg.model != cfg.model:
            items.append((fallback_cfg, True))
    return items


def _can_attempt_real_call(cfg: LLMConfig) -> bool:
    for item, _ in _iter_policy_configs(cfg):
        if not _provider_needs_key(item.provider):
            return True
        if (item.api_key or "").strip():
            return True
    return False


async def _start_stream_with_policy(
    cfg: LLMConfig,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
):
    retries = max(0, int(cfg.max_retries or 0))
    backoff_ms = max(0, int(cfg.retry_backoff_ms or 0))
    timeout_s = max(1000, int(cfg.timeout_ms or 45000)) / 1000.0
    last_error: Optional[Exception] = None

    for active_cfg, used_fallback in _iter_policy_configs(cfg):
        req = llm.request_from_config(
            active_cfg, messages,
            temperature=active_cfg.temperature, max_tokens=active_cfg.max_tokens, top_p=active_cfg.top_p,
            tools=tools or None, tool_choice=tool_choice or None,
        )

        for attempt in range(1, retries + 2):
            try:
                response = await asyncio.wait_for(llm.stream(req), timeout=timeout_s)
                return response, active_cfg, attempt, used_fallback
            except Exception as e:
                last_error = e
                if attempt <= retries and backoff_ms > 0:
                    await asyncio.sleep((backoff_ms * attempt) / 1000.0)

    raise last_error or RuntimeError("Streaming completion failed")


# ── Tool schema helpers ───────────────────────────────────────────────────────

def _flatten_tools(attached_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for t in attached_tools:
        if "subTools" in t:
            for st in t.get("subTools", []):
                flat.append({
                    "toolId": st.get("toolId", "unknown"),
                    "toolType": st.get("toolType", "tool"),
                    "label": st.get("label", st.get("toolId", "tool")),
                    "description": st.get("description", ""),
                    "config": st.get("config", {}),
                })
        else:
            flat.append(t)
    return flat


def _tool_func_name(t: Dict[str, Any]) -> str:
    """
    Derive a stable, LLM-safe function name for a tool.
    Prefer the human label (e.g. "concat_strings") over the raw toolId UUID slug.
    OpenAI function names must match ^[a-zA-Z0-9_-]{1,64}$.
    """
    import re
    label = t.get("label", "")
    if label:
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", label.strip())
        safe = re.sub(r"_+", "_", safe).strip("_")[:64]
        if safe:
            return safe
    tid = t.get("toolId", t.get("tool_type", "tool"))
    return re.sub(r"[^a-zA-Z0-9_]", "_", tid)[:64]


def _typed_tools(attached_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Function name -> signature for each attached tool with typed parameters: built-ins whose spec
    declares them, and custom tools (looked up in the run's tenant / project, at their pinned
    version). The model calls those with real arguments."""
    import tools as tool_registry
    from services import tool_store
    from services.tool_signature import ToolSignature

    typed: Dict[str, Any] = {}
    for t in _flatten_tools(attached_tools):
        tid = t.get("toolId", "")
        spec = tool_registry.get_spec(tid)
        if spec is not None and spec.parameters:
            typed[_tool_func_name(t)] = ToolSignature(entrypoint=tid, legacy=False, parameters=spec.parameters,
                                                      description=spec.description, name=spec.name)
            continue
        if not tid.startswith("custom_") or tid.startswith("custom_mcp_"):
            continue
        version = (t.get("config") or {}).get("tool_version")
        tool = tool_store.for_run(tid[len("custom_"):], version if version not in ("", "latest") else None)
        sig = tool_store.run_signature(tool) if tool else None
        if sig and not sig.legacy:
            typed[_tool_func_name(t)] = sig
    return typed


def _mcp_schema(schema: Any) -> Dict[str, Any]:
    """An MCP tool's inputSchema as a function's parameters (always an object schema)."""
    out = dict(schema) if isinstance(schema, dict) else {}
    out.pop("$schema", None)
    out.setdefault("type", "object")
    out.setdefault("properties", {})
    return out


def _mcp_functions(attached_tools: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Function name -> {tool_id, tool_name, description, parameters} for each MCP tool an attached
    MCP server node offers: the ones stored in its config (``mcp_tools``, from Discover tools), or a
    custom server's discovered tools when the node hasn't picked one with ``tool_name``."""
    import re

    out: Dict[str, Dict[str, Any]] = {}
    for t in _flatten_tools(attached_tools):
        tid = t.get("toolId", "")
        if not (tid.startswith("mcp_") or tid.startswith("custom_mcp_")):
            continue
        cfg = t.get("config") or {}
        listed = cfg.get("mcp_tools")
        if listed is None and tid.startswith("custom_mcp_") and not cfg.get("tool_name"):
            from routers.custom_mcp import _get_server
            from services.secret_store import current_scope_ids
            scope = current_scope_ids()
            server = _get_server(tid, *scope) if scope else None
            listed = (server or {}).get("tools_cache") or []
        base = _tool_func_name(t)
        for mt in listed or []:
            if not isinstance(mt, dict) or not mt.get("name"):
                continue
            name = f"{base}__{re.sub(r'[^a-zA-Z0-9_-]', '_', mt['name'])}"[:64]
            out[name] = {"tool_id": tid, "tool_name": mt["name"], "description": mt.get("description") or mt["name"],
                         "parameters": _mcp_schema(mt.get("inputSchema"))}
    return out


def _tool_schemas(attached_tools: List[Dict[str, Any]], typed: Optional[Dict[str, Any]] = None,
                  mcp: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    schemas = []
    mcp_nodes = {f["tool_id"] for f in (mcp or {}).values()}
    for name, f in (mcp or {}).items():
        schemas.append({"type": "function", "function": {"name": name, "description": f["description"],
                                                         "parameters": f["parameters"]}})
    for t in _flatten_tools(attached_tools):
        if t.get("toolId") in mcp_nodes:
            continue   # offered tool by tool above
        name = _tool_func_name(t)
        sig = (typed or {}).get(name)
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": t.get("description") or (sig.description if sig else "") or f"Execute {name}",
                "parameters": sig.parameters if sig else LEGACY_SCHEMA,
            },
        })
    return schemas


def _tool_id_for_name(func_name: str, attached_tools: List[Dict[str, Any]]) -> Optional[str]:
    for t in _flatten_tools(attached_tools):
        if _tool_func_name(t) == func_name:
            return t.get("toolId", t.get("tool_type", func_name))
    # fallback: match by raw toolId slug
    for t in _flatten_tools(attached_tools):
        tid = t.get("toolId", t.get("tool_type", "tool"))
        if tid.replace("-", "_") == func_name:
            return tid
    return func_name


def _tool_config_for_id(tool_id: str, attached_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    for t in _flatten_tools(attached_tools):
        if t.get("toolId", t.get("tool_type", "tool")) == tool_id:
            return t.get("config", {})
    return {}


# ── Core stream generator ─────────────────────────────────────────────────────

async def _fetch_rag_context(prompt: str, retriever_config: Dict[str, Any],
                             timing: Optional[Dict[str, float]] = None) -> Tuple[str, List[Dict[str, Any]]]:
    """Query the retrieval endpoint and return (joined chunk text, list of retrieved source chunk dicts).
    ``timing`` gets the query embedding's monotonic ``embed_start`` / ``embed_end``, for its trace span."""
    from routers.retrieval import embed_texts
    from services.vector_store import store_for
    collection = retriever_config.get("collection_name", "default")
    top_k = int(retriever_config.get("top_k", 5))
    score_threshold = float(retriever_config.get("score_threshold", 0.0))
    emb_provider = retriever_config.get("embedding_provider", "local")
    emb_model = retriever_config.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
    emb_api_key = retriever_config.get("embedding_api_key", "")

    store = store_for(collection)
    if not store.count(collection):
        return "", []

    if timing is not None:
        timing["embed_start"] = time.monotonic()
    query_emb = (await embed_texts([prompt], emb_provider, emb_model, emb_api_key))[0]
    if timing is not None:
        timing["embed_end"] = time.monotonic()
    # Backends skip chunks whose dimension differs from the query (another embedding model).
    stored = store.search(collection, query_emb, top_k)
    if not stored:
        return "", []

    top_chunks = [ch for ch in stored if ch["_sim"] >= score_threshold] or stored
    
    sources = [
        {
            "chunk_id": ch.get("chunk_id", ""),
            "source": ch.get("source", "Document"),
            "content": ch.get("content", ""),
            "score": round(float(ch.get("_sim", 0.0)), 4),
            "collection": collection,
        }
        for ch in top_chunks
    ]
    return "\n\n".join(ch["content"] for ch in top_chunks), sources


async def run_stream(req: PromptRunRequest, cp: Optional[Checkpointer] = None) -> AsyncIterator[str]:
    """Run one LLM node and stream SSE chunks. With ``req.run_id`` / ``req.resume_from`` the run is
    checkpointed (services/llm_checkpoint.py); ``cp`` is a resume the caller already claimed, so it
    could answer a refused one with a real HTTP error."""
    if cp is None and (req.run_id or req.resume_from):
        try:
            cp = llm_checkpoint.claim(req) if req.resume_from else llm_checkpoint.start(req)
        except llm_checkpoint.NotResumable as e:
            yield _sse({"type": "error", "message": str(e)})
            yield _sse({"type": "done"})
            return
    if cp is None:
        async for chunk in _run(req, None):
            yield chunk
        return
    async for chunk in llm_checkpoint.drive(cp, _run(req, cp)):
        yield chunk


async def _step(cp: Optional[Checkpointer], key: str, fn: Callable[[], Awaitable[Any]]) -> Any:
    """``fn()``, saved under ``key`` on a checkpointed run (and not called again on a resume)."""
    return await cp.value(key, fn) if cp else await fn()


async def _value(v: Any) -> Any:
    return v


async def _no_chunks() -> AsyncIterator[Any]:
    return
    yield


class _Replayed:
    """Stands in for a finished model stream restored from a checkpoint."""
    usage = None

    def __init__(self, turn: Dict[str, Any]):
        self.cost_usd, self.backend = turn["cost_usd"], turn["backend"]


def _turn(response: Any, active_cfg: LLMConfig, attempt_count: int, used_fallback: bool, **fields: Any) -> Dict[str, Any]:
    """A finished model turn as saved in the checkpoint: its output plus what served and priced it."""
    return {"provider": active_cfg.provider, "model": active_cfg.model, "attempt_count": attempt_count,
            "used_fallback": used_fallback, "cost_usd": response.cost_usd, "backend": response.backend, **fields}


def _replay(turn: Dict[str, Any], cfg: LLMConfig) -> Tuple[_Replayed, LLMConfig, int, bool]:
    """The (response, active config, attempts, used fallback) of a saved turn, as from
    _start_stream_with_policy. Its cost counts again: the run's trace shows what the run spent."""
    active = cfg.model_copy(update={"provider": turn["provider"], "model": turn["model"]})
    return _Replayed(turn), active, turn["attempt_count"], turn["used_fallback"]


async def _run(req: PromptRunRequest, cp: Optional[Checkpointer]) -> AsyncIterator[str]:  # noqa: C901
    cfg: LLMConfig = req.config or get_current_config()
    prompt = req.prompt.strip()
    attached_tools = req.attached_tools or []
    run_id = cp.run_id if cp else str(uuid.uuid4())
    t_start = time.monotonic()
    # Step-through debugging from the editor: breakpoints, edited inputs, pinned outputs. A debug run
    # neither reads nor fills the cache (a hit would skip every breakpoint, a pin isn't an answer)
    dbg = debug_run.Debugger(req.debug, cp)
    if req.debug:
        req = req.model_copy(update={"cache_config": None})
    # Time spent outside model and tool calls (middleware, retrieval, embedding), as trace spans
    # put ahead of each path's own spans when the run writes its trace
    phase_spans: List[Dict[str, Any]] = []

    def _phase(span_type: str, name: str, t0: float, t1: float, **extra: Any) -> None:
        phase_spans.append({"span_type": span_type, "name": name, "start_ms": int((t0 - t_start) * 1000),
                            "latency_ms": int((t1 - t0) * 1000), "status": "success", **extra})

    def _with_phases(spans: List[Dict[str, Any]]) -> Optional[str]:
        all_spans = phase_spans + spans
        return json.dumps(all_spans) if all_spans else None

    if not prompt:
        yield _sse({"type": "error", "message": "Prompt cannot be empty."})
        yield _sse({"type": "done"})
        return

    # ── Middleware pre-flight (rate limiter + content moderation) ─────────────
    # Runs before RAG, tools, cache and the LLM so a blocked prompt never
    # reaches any of them. Mirrors the check in routers/run.py.
    mw_t0 = time.monotonic()
    blocked, _, flags = check_prompt_middleware(req.middleware_configs, prompt, req.session_id)
    if req.middleware_configs:
        _phase("middleware", "prompt checks", mw_t0, time.monotonic(),
               **({"status": "error", "error": blocked} if blocked else {}))
    for f in flags:
        yield _sse({"type": "thought", "text": f"⚠ {f}"})
    if blocked:
        write_trace(
            run_id=run_id, app_id=req.app_id, node_id=req.node_id, node_type="llm",
            provider=cfg.provider, model=cfg.model,
            latency_ms=int((time.monotonic() - t_start) * 1000),
            status="error", error=blocked, spans_json=_with_phases([]),
            # A refused prompt stays refused: don't keep its PII in the trace either
            prompt_preview=redact_pii(prompt[:4000]),
        )
        yield _sse({"type": "error", "message": blocked})
        yield _sse({"type": "done"})
        return
    if cp:
        await asyncio.to_thread(llm_checkpoint.record_prompt, cp, prompt)
        if cp.resumed_count():
            yield _sse({"type": "thought", "text": f"↻ Resuming from checkpoint — {cp.resumed_count()} finished step(s) reused"})

    # ── RAG: fetch context and substitute {{context}} in system prompt ─────────
    system_prompt = cfg.system_prompt or ""

    # ── Skills (services/skills_runtime.py): listed for use_skill on demand, or every body in the
    # prompt ("always" — also for the mock provider and local servers, which can't call tools)
    can_call_tools = (cfg.provider != "mock" and _can_attempt_real_call(cfg)
                      and cfg.provider not in ("ollama", "llamacpp", "jan"))
    skillset = await asyncio.to_thread(skills_runtime.SkillSet, req.attached_skills, req.skill_mode,
                                       req.max_active_skills, can_call_tools)
    if (skill_section := skillset.prompt_section()):
        system_prompt = f"{system_prompt}{skill_section}"
        cfg = cfg.model_copy(update={"system_prompt": system_prompt})

    retrieved_sources: List[Dict[str, Any]] = []
    if req.retriever_config:
        from services.vector_store import VectorStoreError
        collection = req.retriever_config.get("collection_name", "default")
        rag_timing: Dict[str, float] = {}
        rag_t0 = time.monotonic()
        ret_node = req.retriever_config.get("node_id")
        rag_query = str(dbg.override("rag").get("query") or (req.retrieval_query or prompt)).strip()
        if (paused := dbg.pause("rag", ret_node, "retriever", collection, {"query": rag_query})):
            yield _sse(paused)
            yield _sse({"type": "done"})
            return
        rag_pin = dbg.pin(ret_node)

        async def _retrieve() -> Tuple[str, List[Dict[str, Any]]]:
            if rag_pin is not None:   # pinned: the chunks the builder chose, no embedding or search
                return rag_pin, []
            return await _fetch_rag_context(rag_query, req.retriever_config, rag_timing)

        try:
            # Saved, so a resumed run answers from the same chunks its earlier steps saw
            rag_context, retrieved_sources = await _step(cp, "rag", _retrieve)
        except VectorStoreError as e:
            yield _sse({"type": "error", "message": f"Retrieval failed: {e}"})
            return
        _phase("retrieval", collection, rag_t0, time.monotonic(), collection=collection, chunks=len(retrieved_sources))
        if "embed_start" in rag_timing:   # not on a resume (saved chunks) or an empty collection
            _phase("embedding", req.retriever_config.get("embedding_model") or "embedding",
                   rag_timing["embed_start"], rag_timing["embed_end"],
                   provider=req.retriever_config.get("embedding_provider", "local"),
                   model=req.retriever_config.get("embedding_model"))
        if rag_context:
            if "{{context}}" in system_prompt:
                system_prompt = system_prompt.replace("{{context}}", rag_context)
            else:
                system_prompt = (
                    f"{system_prompt}\n\n## Retrieved Knowledge / Database Context:\n{rag_context}\n\n"
                    f"Answer the user prompt based on the retrieved context above."
                ).strip()
            cfg = cfg.model_copy(update={"system_prompt": system_prompt})
        if retrieved_sources:
            yield _sse({
                "type": "rag_sources",
                "sources": retrieved_sources,
                "collection": req.retriever_config.get("collection_name", "default"),
                "top_k": len(retrieved_sources),
            })

    # ── Docling pre-parse: if a docling tool with input_path is attached, parse
    # the document now and inject it into the system prompt so the LLM can answer
    # questions about it immediately without needing a tool-call round-trip.
    # Uses {{document}} placeholder if present, otherwise appends to system prompt.
    # Large-document handling:
    #   - max_chars config key caps how much text is injected (default 80 000 chars ≈ ~20k tokens)
    #   - if the parsed content exceeds the cap, a head+tail excerpt is used and a warning is shown
    #   - set max_chars=0 in the tool config to disable the cap (use with care on large docs)
    _DOC_DEFAULT_MAX_CHARS = 80_000  # ~20k tokens — safe for gpt-4o (128k ctx), claude (200k ctx)

    for _t in (attached_tools or []):
        if _t.get("toolId") == "docling":
            _doc_cfg = _t.get("config", {})
            _input_path = (_doc_cfg.get("input_path") or "").strip()
            if _input_path:
                yield _sse({"type": "thought", "text": f"📑 Pre-parsing document: {_input_path}"})
                try:
                    _doc_content = await _step(cp, "docling", lambda: execute_tool_real("docling", _input_path, _doc_cfg))
                    _total_chars = len(_doc_content)
                    _max_chars = int(_doc_cfg.get("max_chars", _DOC_DEFAULT_MAX_CHARS))

                    # ── Size guard ────────────────────────────────────────────
                    _truncated = False
                    _inject_content = _doc_content
                    if _max_chars > 0 and _total_chars > _max_chars:
                        _truncated = True
                        # Keep first 70% and last 30% so start and end are both visible
                        _head = int(_max_chars * 0.70)
                        _tail = _max_chars - _head
                        _inject_content = (
                            _doc_content[:_head]
                            + f"\n\n... [{_total_chars - _max_chars:,} chars omitted — document too large for full inline injection. "
                            f"Use RAG (Retriever node) for documents larger than ~{_max_chars // 1000}k chars] ...\n\n"
                            + _doc_content[-_tail:]
                        )

                    _doc_block = f"\n\n---\nDOCUMENT CONTEXT (parsed by Docling):\n{_inject_content}\n---\n"
                    if "{{document}}" in system_prompt:
                        system_prompt = system_prompt.replace("{{document}}", _inject_content)
                    else:
                        system_prompt = system_prompt + _doc_block
                    cfg = cfg.model_copy(update={"system_prompt": system_prompt})

                    if _truncated:
                        _approx_tokens = _total_chars // 4
                        yield _sse({"type": "thought", "text": (
                            f"⚠ Document is large ({_total_chars:,} chars ≈ {_approx_tokens:,} tokens). "
                            f"Injected first+last {_max_chars:,} chars. "
                            f"For full coverage, use a RAG pipeline (Retriever node) instead."
                        )})
                    else:
                        _approx_tokens = _total_chars // 4
                        yield _sse({"type": "thought", "text": (
                            f"✅ Document loaded ({_total_chars:,} chars ≈ {_approx_tokens:,} tokens) — ready to answer questions."
                        )})
                except Exception as _doc_err:
                    yield _sse({"type": "thought", "text": f"⚠ Docling pre-parse failed: {_doc_err}"})
            break

    # ── Cache check ───────────────────────────────────────────────────────────
    cache_key = None
    scope = "prompt"
    ttl_seconds = 3600
    cache_hit = False

    if req.cache_config:
        c_cfg = req.cache_config
        scope = c_cfg.get("scope", "prompt")
        ttl_seconds = int(c_cfg.get("ttl_seconds", 3600))
        cache_key = make_cache_key(prompt, cfg, scope)
        with get_db_connection() as conn:
            cached = cache_get(conn, cache_key)
        if cached:
            cache_hit = True
            hit_text = f"⚡ [Cache Hit — {scope} scope, {cached['hit_count']} hits]\n\n{cached['output']}"
            async for chunk in _mock_stream(hit_text, chunk=6, delay=0.004):
                yield chunk
            yield _sse({"type": "meta", "provider": cached["provider"], "model": cached["model"],
                        "cache_hit": True, "scope": scope, "steps": 0})
            yield _sse({"type": "done"})
            return

    # ── Memory load ───────────────────────────────────────────────────────────
    who = ltm.current()   # tenant / project (and end user) this run's memory belongs to
    long_term = await asyncio.to_thread(ltm.active, req.memory_config, who)

    async def _load_memory() -> Dict[str, Any]:
        history: List[Dict[str, str]] = []
        if req.session_id and req.memory_config:
            mem_cfg = req.memory_config
            token_budget = int(mem_cfg.get("token_budget") or 4096)
            strategy = mem_cfg.get("strategy") or "sliding_window"
            raw_msgs = await asyncio.to_thread(ltm.load_messages, who, req.session_id,
                                               ltm.session_ttl_hours(mem_cfg))
            trimmed = trim_to_budget(raw_msgs, token_budget, strategy)
            history = [{"role": m["role"], "content": m["content"]} for m in trimmed]
        # Long-term memory: facts about this end user from earlier sessions, ahead of the history
        facts: List[str] = []
        if long_term:
            facts = await asyncio.to_thread(ltm.recall, who, prompt,
                                            int(req.memory_config.get("recall_k") or ltm.DEFAULT_RECALL_K))
            if facts:
                history = [{"role": "system", "content": ltm.context_block(facts)}, *history]
        return {"history": history, "remembered": facts}

    # Saved, so a resume sees the history the run started with, not turns added since
    loaded = await _step(cp, "memory", _load_memory)
    memory_history: List[Dict[str, str]] = loaded["history"]
    remembered: List[str] = loaded["remembered"]

    # ── Persist helper ────────────────────────────────────────────────────────
    async def _persist(user_content: str, assistant_content: str) -> None:
        if dbg.pins:
            return   # a pinned output isn't a real answer: keep it out of memory
        if req.session_id:
            await asyncio.to_thread(ltm.append_messages, who, req.session_id, [
                ("user", user_content, rough_token_count(user_content)),
                ("assistant", assistant_content, rough_token_count(assistant_content))])
        if long_term and req.memory_config.get("extract", True):
            await asyncio.to_thread(ltm.queue_extraction, who, cfg, req.app_id, user_content, assistant_content,
                                    cfg.api_key)
        if cache_key and req.cache_config and not cache_hit:
            with get_db_connection() as conn:
                cache_set(conn, cache_key, scope, user_content, assistant_content, cfg, ttl_seconds)

    # ── Response guard: post-response middleware, run before _persist ─────────
    # Tokens have already streamed, so a block emits error with retract=True
    # and the client replaces the visible answer. Blocked output is never
    # written to memory or cache.
    async def _response_guard(output: str, tokens: int, cost: float,
                              model_answer: bool = True) -> Tuple[Optional[str], List[str]]:
        """model_answer=False for simulated text: skips the grounding fact check and custom rules."""
        g_t0 = time.monotonic()
        try:
            blocked, flags = await _response_checks(output, tokens, cost, model_answer)
        finally:
            if req.middleware_configs:
                _phase("middleware", "response checks", g_t0, time.monotonic())
        if blocked and req.middleware_configs:
            phase_spans[-1].update(status="error", error=blocked)
        return blocked, flags

    async def _response_checks(output: str, tokens: int, cost: float,
                               model_answer: bool) -> Tuple[Optional[str], List[str]]:
        context = None
        if grounding is not None and model_answer:
            # Everything the model was allowed to know: system prompt (RAG / documents),
            # earlier turns, the prompt and every tool output.
            context = "\n".join([cfg.system_prompt or "", *(m["content"] for m in memory_history),
                                 prompt, *tool_outputs])
        blocked, flags = check_response_middleware(req.middleware_configs, output, req.session_id, tokens, cost,
                                                   context=context)
        if blocked or not model_answer:
            return blocked, flags
        rule_blocked, rule_flags = await check_custom_rules(req.middleware_configs, prompt, output, cfg)
        return rule_blocked, flags + rule_flags

    # ── Grounding guard: tell the model to stick to tool / document data ─────
    grounding = get_grounding_config(req.middleware_configs)
    tool_outputs: List[str] = []
    if grounding is not None and grounding.get("inject_instruction", True):
        cfg = cfg.model_copy(update={"system_prompt": f"{cfg.system_prompt or ''}\n\n{GROUNDING_INSTRUCTION}".strip()})

    def _empty_tools_action() -> str:
        """'answer' | 'instruct' | 'off' when every tool output so far is empty, else 'off'."""
        if grounding is None or not tool_outputs or not all(is_empty_tool_output(o) for o in tool_outputs):
            return "off"
        return grounding.get("on_empty_tools", "answer")

    # ── Mock / no-key path ────────────────────────────────────────────────────
    if cfg.provider == "mock" or not _can_attempt_real_call(cfg):
        tool_lines = ""
        sim_spans: List[Dict[str, Any]] = []   # the tools really run, so they get spans like any run
        if attached_tools:
            yield _sse({"type": "thought", "text": f"Planning tool use for: {prompt[:60]}…"})
            await asyncio.sleep(0.1)
            for i, t in enumerate(attached_tools):
                t_name = t.get("label", t.get("toolId", "Tool"))
                t_id = t.get("toolId", "tool")
                t_key, t_node = f"tool:{i}", t.get("nodeId")
                t_in = str(dbg.override(t_key).get("input", prompt))
                if (paused := dbg.pause(t_key, t_node, "tool", t_name, {"input": t_in})):
                    yield _sse(paused)
                    yield _sse({"type": "done"})
                    return
                t_pin = dbg.pin(t_node)
                yield _sse({"type": "tool_call", "name": t_name, "input": t_in[:80]})
                await asyncio.sleep(0.12)
                t_t0 = time.monotonic()
                t_out = await _step(cp, t_key, lambda: _value(t_pin) if t_pin is not None
                                    else execute_tool_real(t_id, t_in, t.get("config", {})))
                sim_spans.append({"span_type": "tool", "step": 1, "start_ms": int((t_t0 - t_start) * 1000),
                                  "name": t_name, "tool_id": t_id, "node_id": t_node,
                                  "latency_ms": int((time.monotonic() - t_t0) * 1000),
                                  "input_preview": t_in[:200], "output_preview": t_out[:400], "status": "success",
                                  "pinned": t_pin is not None, "edited": "input" in dbg.override(t_key),
                                  "checkpoint_key": t_key if cp else None})
                yield _sse({"type": "tool", "name": t_name, "output": t_out[:300], "node_id": t_node, "step_key": t_key})
                tool_lines += f"\n[{t_name}]: {t_out[:200]}"
                await asyncio.sleep(0.04)

        prior = len(memory_history) - (1 if remembered else 0)
        mem_line = f"\n🧠 Memory: {prior} prior messages." if prior else ""
        if remembered:
            mem_line += "\n🧠 Remembered about you: " + "; ".join(remembered)
        simulated = (
            f"[Simulated {cfg.provider.upper()} — {cfg.model}]\n"
            f"Temp={cfg.temperature}  MaxTokens={cfg.max_tokens}\n\n"
            f"Prompt: {prompt}"
            f"{tool_lines}{mem_line}\n\n"
            f"Answer: This is a simulated streaming response with real tool results above.\n"
            f"Add a real API key on the LLM node to enable live model calls."
        )
        async for chunk in _mock_stream(simulated):
            yield chunk
        blocked, flags = await _response_guard(simulated, 0, 0.0, model_answer=False)
        for f in flags:
            yield _sse({"type": "thought", "text": f"⚠ {f}"})
        latency_ms = int((time.monotonic() - t_start) * 1000)
        # Traced like a real run (Traces, metrics, OTLP, Langfuse) — flagged so no one mistakes it for one
        write_trace(
            run_id=run_id, app_id=req.app_id, node_id=req.node_id, node_type="llm",
            provider=cfg.provider, model=cfg.model, latency_ms=latency_ms,
            status="error" if blocked else "success", error=blocked,
            prompt_preview=prompt[:4000] if prompt else None,
            output_preview=simulated[:4000] if not blocked else None,
            metadata_json=json.dumps({"simulated": True, "steps": 1,
                                      "tools_count": len(attached_tools) if attached_tools else 0,
                                      **({"middleware_flags": flags} if flags else {})}),
            spans_json=_with_phases(sim_spans),
        )
        if blocked:
            yield _sse({"type": "error", "message": blocked, "retract": True})
            yield _sse({"type": "done"})
            return
        await _persist(prompt, simulated)
        yield _sse({"type": "meta", "provider": cfg.provider, "model": cfg.model,
                    "simulated": True, "steps": 1, "cost_usd": 0.0, "latency_ms": latency_ms, "run_id": run_id})
        yield _sse({"type": "done"})
        return

    # ── Local servers (Ollama / llama.cpp / Jan) — pre-execute tools, then a single model call ──
    if cfg.provider in ("ollama", "llamacpp", "jan"):
        tool_context = ""
        local_spans: List[Dict[str, Any]] = []   # same records as the tool loop's, for traces and metrics
        if attached_tools:
            for i, t in enumerate(attached_tools):
                t_name = t.get("label", t.get("toolId", "Tool"))
                t_id = t.get("toolId", "tool")
                t_key, t_node = f"tool:{i}", t.get("nodeId")
                t_in = str(dbg.override(t_key).get("input", prompt))
                if (paused := dbg.pause(t_key, t_node, "tool", t_name, {"input": t_in})):
                    yield _sse(paused)
                    yield _sse({"type": "done"})
                    return
                t_pin = dbg.pin(t_node)
                yield _sse({"type": "tool_call", "name": t_name, "input": t_in[:80]})
                t_t0 = time.monotonic()
                t_out = await _step(cp, t_key, lambda: _value(t_pin) if t_pin is not None
                                    else execute_tool_real(t_id, t_in, t.get("config", {})))
                local_spans.append({"span_type": "tool", "step": 1, "start_ms": int((t_t0 - t_start) * 1000),
                                    "name": t_name, "tool_id": t_id, "node_id": t_node,
                                    "latency_ms": int((time.monotonic() - t_t0) * 1000),
                                    "input_preview": t_in[:200], "output_preview": t_out[:400], "status": "success",
                                    "pinned": t_pin is not None, "edited": "input" in dbg.override(t_key),
                                    "checkpoint_key": t_key if cp else None})
                yield _sse({"type": "tool", "name": t_name, "output": t_out[:400], "node_id": t_node, "step_key": t_key})
                yield _sse(_trace_event(local_spans[-1]))
                tool_context += f"\n[Tool '{t_name}']:\n{t_out}\n"
                tool_outputs.append(t_out)

        system = cfg.system_prompt or ""
        if tool_context:
            system += f"\n\nTool Results:{tool_context}"
        empty_action = _empty_tools_action()
        if empty_action == "instruct":
            system += f"\n\n{GROUNDING_EMPTY_INSTRUCTION}"
        elif empty_action == "answer":
            yield _sse({"type": "thought", "text": "🛡 Grounding: every tool returned nothing — skipping the model."})

        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.extend(memory_history)
        messages.append({"role": "user", "content": prompt})

        full_output = ""
        timeout_deadline = time.monotonic() + (max(1000, int(cfg.timeout_ms or 45000)) / 1000.0)
        active_cfg, attempt_count, used_fallback = cfg, 1, False
        if empty_action != "answer":
            if (edited := dbg.override("llm:1").get("messages")) is not None:
                messages[:] = edited
            if (paused := dbg.pause("llm:1", req.node_id, "llm", cfg.model, {"messages": messages})):
                yield _sse(paused)
                yield _sse({"type": "done"})
                return
        llm_pin = dbg.pin(req.node_id)

        try:
            yield _sse({"type": "step", "step": 1})
            response = None
            usage: Dict[str, Any] = {}
            if empty_action == "answer":
                full_output = grounding.get("empty_message") or DEFAULT_EMPTY_MESSAGE
                usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                yield _sse({"type": "token", "text": full_output})
            elif (turn := (cp.saved("llm:1") if cp else None)
                    or (debug_run.pinned_turn(llm_pin, cfg) if llm_pin is not None else None)):
                # Finished before the run was cut off (or pinned): replay it instead of calling the model
                llm_t0 = time.monotonic()
                response, active_cfg, attempt_count, used_fallback = _replay(turn, cfg)
                full_output, usage = turn["text"], turn["usage"]
                yield _sse({"type": "token", "text": full_output})
            else:
                llm_t0 = time.monotonic()
                response, active_cfg, attempt_count, used_fallback = await _start_stream_with_policy(cfg, messages)
                async for chunk in response:
                    if time.monotonic() > timeout_deadline:
                        raise TimeoutError(f"Timed out after {int(cfg.timeout_ms or 45000)} ms")
                    if chunk.text:
                        full_output += chunk.text
                        yield _sse({"type": "token", "text": chunk.text})
                if response.usage:
                    usage = response.usage.as_dict()
                if cp:
                    cp.put("llm:1", _turn(response, active_cfg, attempt_count, used_fallback,
                                          text=full_output, usage=usage))

            # Not every local server reports usage on a stream; estimate so traces aren't all zeros.
            if not usage.get("total_tokens") and empty_action != "answer":
                p_tok = sum(rough_token_count(str(m.get("content") or "")) for m in messages)
                c_tok = rough_token_count(full_output)
                usage = {"prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": p_tok + c_tok}

            # Local servers cost nothing; only price a paid fallback.
            cost = 0.0
            if response is not None and _provider_needs_key(active_cfg.provider):
                cost = response.cost_usd
            if response is not None:
                local_spans.append({
                    "span_type": "llm", "step": 1, "start_ms": int((llm_t0 - t_start) * 1000),
                    "name": "LLM Call (step 1)", "provider": active_cfg.provider, "model": active_cfg.model,
                    "latency_ms": int((time.monotonic() - llm_t0) * 1000),
                    "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0), "cost_usd": round(cost, 6),
                    "finish_reason": "stop", "tool_calls_count": 0, "status": "success",
                    "checkpoint_key": "llm:1" if cp else None, "node_id": req.node_id,
                    "pinned": llm_pin is not None, "edited": "messages" in dbg.override("llm:1"),
                })
                yield _sse(_trace_event(local_spans[-1]))
            blocked, flags = await _response_guard(full_output, usage["total_tokens"], cost,
                                                   model_answer=empty_action != "answer")
            for f in flags:
                yield _sse({"type": "thought", "text": f"⚠ {f}"})
            latency_ms = int((time.monotonic() - t_start) * 1000)
            meta_dict = {"finish_reason": "stop", "steps": 1, "tools_count": len(attached_tools)}
            if response is not None:
                meta_dict["llm_backend"] = response.backend
            if empty_action == "answer":
                meta_dict["grounding"] = "empty_tool_results"
            if flags:
                meta_dict["middleware_flags"] = flags
            write_trace(
                run_id=run_id, app_id=req.app_id, node_id=req.node_id, node_type="llm",
                provider=active_cfg.provider, model=active_cfg.model,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
                attempt_count=attempt_count,
                used_fallback=used_fallback,
                effective_provider=active_cfg.provider,
                effective_model=active_cfg.model,
                latency_ms=latency_ms, cost_usd=round(cost, 6),
                status="error" if blocked else "success", error=blocked,
                prompt_preview=prompt[:4000],
                output_preview=full_output[:4000] if full_output and not blocked else None,
                metadata_json=json.dumps(meta_dict),
                spans_json=_with_phases(local_spans),
            )
            if blocked:
                yield _sse({"type": "error", "message": blocked, "retract": True})
                yield _sse({"type": "done"})
                return
            await _persist(prompt, full_output)
            yield _sse({"type": "meta", "provider": active_cfg.provider, "model": active_cfg.model,
                        "usage": usage, "steps": 1, "cost_usd": round(cost, 6),
                        "latency_ms": latency_ms, "run_id": run_id,
                        "attempt_count": attempt_count, "used_fallback": used_fallback,
                        "effective_provider": active_cfg.provider, "effective_model": active_cfg.model,
                        "llm_backend": response.backend if response is not None else None})
            yield _sse({"type": "done"})
            return
        except Exception as e:
            local_name = {"llamacpp": "llama.cpp", "jan": "Jan"}.get(cfg.provider, "Ollama")
            write_trace(
                run_id=run_id, app_id=req.app_id, node_id=req.node_id, node_type="llm",
                provider=cfg.provider, model=cfg.model,
                attempt_count=attempt_count,
                used_fallback=used_fallback,
                effective_provider=active_cfg.provider,
                effective_model=active_cfg.model,
                latency_ms=int((time.monotonic() - t_start) * 1000), status="error", error=str(e),
                prompt_preview=prompt[:4000],
            )
            logger.error(f"{local_name} error: {e}")
            yield _sse({"type": "error", "message": f"{local_name} error: {e}"})
            yield _sse({"type": "done"})
            return

    # ── Spend budget gate (paid providers only; mock/local servers returned above) ───
    _budget = check_budget(req.app_id)
    if _budget["blocked"]:
        yield _sse({"type": "error", "message": f"Budget exceeded — {_budget['message']}"})
        yield _sse({"type": "done"})
        return
    for _w in _budget["warnings"]:
        yield _sse({"type": "thought", "text": f"⚠ {_w}"})

    # ── All other providers — unified ReAct loop ─────────────────────────────
    typed_tools = await asyncio.to_thread(_typed_tools, attached_tools) if attached_tools else {}
    mcp_functions = await asyncio.to_thread(_mcp_functions, attached_tools) if attached_tools else {}
    def _schemas_now() -> List[Dict[str, Any]]:
        """The tools offered this step: attached ones not waiting for a skill, the loaded skills'
        tools, and use_skill (rebuilt every step, as skills load)."""
        visible = skillset.visible_tools(attached_tools)
        mcp_visible = {k: v for k, v in mcp_functions.items() if skillset.tool_visible(v["tool_id"])}
        return (_tool_schemas(visible, typed_tools, mcp_visible) if visible else []) + skillset.schemas()

    tool_schemas = _schemas_now()

    # Determine output-parser format reminder (injected after tool results)
    _op = req.output_parser or {}
    _op_type = _op.get("parser_type", "")
    _FORMAT_REMINDERS: Dict[str, str] = {
        "json":     "IMPORTANT: Your final response MUST be valid JSON only. No prose, no markdown fences, no explanation — raw JSON.",
        "pydantic": "IMPORTANT: Your final response MUST be valid JSON only. No prose, no markdown fences, no explanation — raw JSON.",
        "csv":      "IMPORTANT: Your final response MUST be CSV only. First row is the header. No prose or explanation.",
    }
    _format_reminder: Optional[str] = _FORMAT_REMINDERS.get(_op_type)

    messages = []
    if cfg.system_prompt:
        messages.append({"role": "system", "content": cfg.system_prompt})
    messages.extend(memory_history)
    messages.append({"role": "user", "content": prompt})

    final_output = ""
    usage: Dict[str, Any] = {}
    cost_usd = 0.0
    step = 0
    finish_reason = "stop"
    effective_provider = cfg.provider
    effective_model = cfg.model
    attempt_count = 1
    used_fallback = False
    llm_backend = None
    # Per-step span records for flame-graph visualization
    _spans: List[Dict[str, Any]] = []

    _force_no_tools_next_step = False   # set after injecting format reminder

    try:
        for step in range(1, MAX_AGENT_STEPS + 1):
            yield _sse({"type": "step", "step": step})
            tool_schemas = _schemas_now()
            _step_start = time.monotonic()

            collected_content = ""
            collected_tool_calls: List[Dict[str, Any]] = []
            collected_thinking: List[Dict[str, Any]] = []
            finish_reason = "stop"

            # When a format reminder was injected after the last tool results,
            # force tool_choice="none" so the LLM writes its final answer
            # instead of calling the tool again.
            _this_tool_choice = (
                "none"
                if _force_no_tools_next_step
                else ("auto" if tool_schemas else None)
            )
            _force_no_tools_next_step = False

            llm_key = f"llm:{step}"
            turn = cp.saved(llm_key) if cp else None
            llm_pinned = False
            if not turn:
                if (edited := dbg.override(llm_key).get("messages")) is not None:
                    messages[:] = edited
                if (paused := dbg.pause(llm_key, req.node_id, "llm", cfg.model, {"messages": messages})):
                    yield _sse(paused)
                    yield _sse({"type": "done"})
                    return
                if (llm_pin := dbg.pin(req.node_id)) is not None:
                    turn, llm_pinned = debug_run.pinned_turn(llm_pin, cfg), True
            if turn:
                # Finished before the run was cut off (or pinned): replay it instead of calling the model
                response, active_cfg, attempt_count, used_fallback = _replay(turn, cfg)
                collected_content, finish_reason = turn["text"], turn["finish_reason"]
                collected_tool_calls, collected_thinking = turn["tool_calls"], turn["thinking"]
                if collected_content:
                    final_output += collected_content
                    yield _sse({"type": "token", "text": collected_content})
            else:
                response, active_cfg, attempt_count, used_fallback = await _start_stream_with_policy(
                    cfg,
                    messages,
                    tools=tool_schemas if tool_schemas else None,
                    tool_choice=_this_tool_choice,
                )
            effective_provider = active_cfg.provider
            effective_model = active_cfg.model
            llm_backend = response.backend
            timeout_deadline = time.monotonic() + (max(1000, int(active_cfg.timeout_ms or 45000)) / 1000.0)

            async for chunk in (response if not turn else _no_chunks()):
                if time.monotonic() > timeout_deadline:
                    raise TimeoutError(f"Timed out after {int(active_cfg.timeout_ms or 45000)} ms")

                if chunk.text:
                    collected_content += chunk.text
                    final_output += chunk.text
                    yield _sse({"type": "token", "text": chunk.text})

                for tc_delta in chunk.tool_calls:
                    idx = tc_delta.index
                    while len(collected_tool_calls) <= idx:
                        collected_tool_calls.append(
                            {"id": "", "type": "function",
                             "function": {"name": "", "arguments": ""}}
                        )
                    if tc_delta.id:
                        collected_tool_calls[idx]["id"] = tc_delta.id
                    collected_tool_calls[idx]["function"]["name"] += tc_delta.name
                    collected_tool_calls[idx]["function"]["arguments"] += tc_delta.arguments

                collected_thinking.extend(chunk.thinking_blocks)
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason

            _step_latency_ms = int((time.monotonic() - _step_start) * 1000)

            if response.usage:
                usage = response.usage.as_dict()
            elif turn and turn["usage"]:
                usage = turn["usage"]
            if cp and not turn:
                cp.put(llm_key, _turn(response, active_cfg, attempt_count, used_fallback,
                                            text=collected_content, tool_calls=collected_tool_calls,
                                            thinking=collected_thinking, finish_reason=finish_reason,
                                            usage=response.usage.as_dict() if response.usage else {}))
            _step_cost = response.cost_usd
            cost_usd += _step_cost

            # Record LLM span for this step (start_ms: offset from the run's start, for timelines)
            _spans.append({
                "span_type": "llm",
                "step": step,
                "start_ms": int((_step_start - t_start) * 1000),
                "name": f"LLM Call (step {step})",
                "provider": active_cfg.provider,
                "model": active_cfg.model,
                "latency_ms": _step_latency_ms,
                "prompt_tokens": usage.get("prompt_tokens", 0) if finish_reason == "stop" else 0,
                "completion_tokens": usage.get("completion_tokens", 0) if finish_reason == "stop" else 0,
                "total_tokens": usage.get("total_tokens", 0) if finish_reason == "stop" else 0,
                "cost_usd": round(_step_cost, 6),
                "finish_reason": finish_reason,
                "tool_calls_count": len(collected_tool_calls),
                "status": "success",
                # The saved step behind this span: the trace drawer re-runs a run from it
                "checkpoint_key": llm_key if cp else None,
                "resumed": bool(turn) and not llm_pinned,
                "node_id": req.node_id, "pinned": llm_pinned, "edited": "messages" in dbg.override(llm_key),
            })
            yield _sse(_trace_event(_spans[-1]))

            if finish_reason == "stop" or not collected_tool_calls:
                break

            messages.append({
                "role": "assistant",
                "content": collected_content or None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}
                    for tc in collected_tool_calls
                ],
                # Anthropic: the turn's reasoning must go back unchanged with the tool results
                **({"thinking_blocks": collected_thinking} if collected_thinking else {}),
            })

            for tc_index, tc in enumerate(collected_tool_calls):
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                if skillset.on_demand and func_name == skills_runtime.USE_SKILL:
                    # Loading is decided from the call itself, so a replayed (resumed) call switches the
                    # same skill on; the result text is saved like any tool result
                    _skill_t0 = time.monotonic()
                    skill_text, loaded_skill = skillset.load(str(args.get("name") or ""), attached_tools, _tool_func_name)
                    t_key = f"tool:{step}:{tc_index}"
                    skill_out = await _step(cp, t_key, lambda: _value(skill_text))
                    if loaded_skill:
                        yield _sse({"type": "skill_loaded", **loaded_skill})
                    yield _sse({"type": "thought", "text": f"🧩 {skill_text.splitlines()[0].lstrip('# ')}"})
                    _spans.append({
                        "span_type": "skill", "step": step, "start_ms": int((_skill_t0 - t_start) * 1000),
                        "name": f"Loaded skill: {loaded_skill['name']}" if loaded_skill else "use_skill",
                        "latency_ms": int((time.monotonic() - _skill_t0) * 1000), "status": "success" if loaded_skill else "error",
                        "input_preview": str(args.get("name") or "")[:200], "output_preview": skill_out[:400],
                        **({"skill_id": loaded_skill["id"], "skill_version": loaded_skill["version"],
                            "tools_enabled": loaded_skill["tools"]} if loaded_skill else {}),
                        "checkpoint_key": t_key if cp else None,
                    })
                    yield _sse(_trace_event(_spans[-1]))
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": skill_out})
                    continue
                # Typed tools get the model's arguments as they are; the rest one input string. A typed
                # tool called the old way, with only {"input": ...}, is treated as the old call
                sig = typed_tools.get(func_name)
                legacy_call = sig is not None and set(args) == {"input"} and "input" not in sig.parameters.get("properties", {})
                tool_args = args if sig is not None and not legacy_call else None
                tool_input = json.dumps(args, ensure_ascii=False) if tool_args is not None else args.get("input", prompt)
                tool_id = _tool_id_for_name(func_name, attached_tools)
                tool_cfg = _tool_config_for_id(tool_id or func_name, attached_tools)
                mcp_fn = mcp_functions.get(func_name)
                if mcp_fn:   # one tool of an MCP server node: its arguments go straight to tools/call
                    tool_id, tool_args, tool_input = mcp_fn["tool_id"], None, json.dumps(args, ensure_ascii=False)
                    tool_cfg = {**_tool_config_for_id(tool_id, attached_tools), "tool_name": mcp_fn["tool_name"],
                                "arguments": args}
                if (needs := skillset.blocked_by(tool_id)):
                    # A tool that waits for a skill, called before it was loaded: tell the model, don't run it
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": f"'{func_name}' isn't available yet: load the skill '{needs}' with use_skill first."})
                    continue

                t_key = f"tool:{step}:{tc_index}"
                t_node = debug_run.tool_node_id(func_name, tool_id, attached_tools, _tool_func_name)
                t_edit = dbg.override(t_key)
                if "input" in t_edit:
                    tool_input, tool_args = debug_run.tool_input(t_edit, tool_input, tool_args)
                    if mcp_fn:   # an MCP tool's edited arguments go to tools/call
                        try:
                            mcp_args = json.loads(tool_input)
                        except json.JSONDecodeError:
                            mcp_args = None
                        if isinstance(mcp_args, dict):
                            tool_cfg = {**tool_cfg, "arguments": mcp_args}
                if cp and cp.saved(t_key) is None and (
                        paused := dbg.pause(t_key, t_node, "tool", func_name, {"input": tool_input})):
                    yield _sse(paused)
                    yield _sse({"type": "done"})
                    return
                t_pin = dbg.pin(t_node)
                yield _sse({"type": "tool_call", "name": func_name, "input": tool_input[:200]})
                _tool_t0 = time.monotonic()
                tool_output = await _step(cp, t_key, lambda: _value(t_pin) if t_pin is not None else execute_tool_real(
                    tool_id or func_name, tool_input, tool_cfg, tool_args))
                _tool_latency_ms = int((time.monotonic() - _tool_t0) * 1000)
                yield _sse({"type": "tool", "name": func_name, "output": tool_output[:400], "node_id": t_node,
                            "step_key": t_key})

                # Record tool execution span
                _spans.append({
                    "span_type": "tool",
                    "step": step,
                    "start_ms": int((_tool_t0 - t_start) * 1000),
                    "name": func_name,
                    "tool_id": tool_id or func_name,
                    "latency_ms": _tool_latency_ms,
                    "input_preview": tool_input[:200],
                    "output_preview": tool_output[:400],
                    "status": "success",
                    "checkpoint_key": t_key if cp else None,
                    "node_id": t_node, "pinned": t_pin is not None, "edited": "input" in t_edit,
                })
                yield _sse(_trace_event(_spans[-1]))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_output,
                })
                tool_outputs.append(tool_output)

            empty_action = _empty_tools_action()
            if empty_action == "answer":
                empty_msg = grounding.get("empty_message") or DEFAULT_EMPTY_MESSAGE
                text = f"\n\n{empty_msg}" if final_output else empty_msg
                final_output += text
                yield _sse({"type": "thought", "text": "🛡 Grounding: every tool returned nothing — skipping the model."})
                yield _sse({"type": "token", "text": text})
                finish_reason = "stop"
                break
            if empty_action == "instruct":
                messages.append({"role": "system", "content": GROUNDING_EMPTY_INSTRUCTION})

            # After all tool results, inject the format reminder as a system
            # message and flag the next step to use tool_choice="none" so the
            # LLM writes its final answer without calling tools again.
            if _format_reminder:
                messages.append({"role": "system", "content": _format_reminder})
                _force_no_tools_next_step = True

        latency_ms = int((time.monotonic() - t_start) * 1000)
        meta_dict = {
            "finish_reason": finish_reason,
            "steps": step,
            "tools_count": len(attached_tools) if attached_tools else 0,
            "llm_backend": llm_backend,
            **({"skills_used": skillset.used} if skillset.used else {}),
        }
        blocked, flags = await _response_guard(final_output, usage.get("total_tokens", 0), cost_usd)
        for f in flags:
            yield _sse({"type": "thought", "text": f"⚠ {f}"})
        if flags:
            meta_dict["middleware_flags"] = flags
        write_trace(
            run_id=run_id, app_id=req.app_id, node_id=req.node_id, node_type="llm",
            provider=effective_provider, model=effective_model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            attempt_count=attempt_count,
            used_fallback=used_fallback,
            effective_provider=effective_provider,
            effective_model=effective_model,
            latency_ms=latency_ms, cost_usd=round(cost_usd, 6),
            status="error" if blocked else "success", error=blocked,
            prompt_preview=prompt[:4000] if prompt else None,
            output_preview=final_output[:4000] if final_output and not blocked else None,
            metadata_json=json.dumps(meta_dict),
            spans_json=_with_phases(_spans),
        )
        if blocked:
            yield _sse({"type": "error", "message": blocked, "retract": True})
            yield _sse({"type": "done"})
            return
        await _persist(prompt, final_output)
        yield _sse({
            "type": "meta", "provider": effective_provider, "model": effective_model,
            "usage": usage, "finish_reason": finish_reason, "steps": step,
            "cost_usd": round(cost_usd, 6), "latency_ms": latency_ms, "run_id": run_id,
            "attempt_count": attempt_count, "used_fallback": used_fallback,
            "effective_provider": effective_provider, "effective_model": effective_model,
            "llm_backend": llm_backend, "skills_used": skillset.used,
        })
        yield _sse({"type": "done"})

    except Exception as e:
        latency_ms = int((time.monotonic() - t_start) * 1000)
        write_trace(
            run_id=run_id, app_id=req.app_id, node_id=req.node_id, node_type="llm",
            provider=cfg.provider, model=cfg.model,
            attempt_count=attempt_count,
            used_fallback=used_fallback,
            effective_provider=effective_provider,
            effective_model=effective_model,
            latency_ms=latency_ms, status="error", error=str(e),
            prompt_preview=prompt[:4000] if prompt else None,
            spans_json=_with_phases(_spans),
        )
        logger.error(f"LLM agent loop error [{cfg.provider}/{cfg.model}]: {e}")
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})
