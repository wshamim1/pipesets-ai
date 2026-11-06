import json
import logging
import os
import time
import asyncio
import uuid
from typing import List, Dict, Any

import httpx
from fastapi import APIRouter, HTTPException

import llm
from llm.catalog import PROVIDERS, DEFAULT_MODELS
from db import get_db_connection
from models import (
    LLMConfig,
    PromptRunRequest,
    PromptRunResponse,
    ProviderValidateRequest,
    ProviderValidateResponse,
    ProviderBulkValidateRequest,
)
from routers.cache import make_cache_key, cache_get, cache_set
from routers.memory import trim_to_budget, rough_token_count
from routers.traces import write_trace
from routers.middleware import (
    GROUNDING_INSTRUCTION, check_prompt_middleware, check_response_middleware, get_grounding_config,
)
from services import long_term_memory as ltm
from services.guardrail_judge import check_custom_rules
from services.budget import check_budget

logger = logging.getLogger("pipesets-ai-backend")

router = APIRouter(tags=["run"])


def _provider_needs_key(provider: str) -> bool:
    p = provider.lower()
    return p not in {"mock", "local", "ollama", "llamacpp", "jan"}


def _iter_policy_configs(cfg: LLMConfig) -> List[LLMConfig]:
    configs = [cfg]
    fallback_provider = (cfg.fallback_provider or "").strip()
    fallback_model = (cfg.fallback_model or "").strip()
    if fallback_provider == "mock":
        return configs
    if fallback_provider and fallback_model:
        fallback_cfg = cfg.model_copy(update={
            "provider": fallback_provider,
            "model": fallback_model,
            "api_key": (cfg.fallback_api_key or cfg.api_key or "").strip(),
            "base_url": cfg.fallback_base_url or cfg.base_url,
        })
        if fallback_cfg.provider != cfg.provider or fallback_cfg.model != cfg.model:
            configs.append(fallback_cfg)
    return configs


def _can_attempt_real_call(cfg: LLMConfig) -> bool:
    for item in _iter_policy_configs(cfg):
        if not _provider_needs_key(item.provider):
            return True
        if (item.api_key or "").strip():
            return True
    return False


async def _completion_with_policy(cfg: LLMConfig, messages: List[Dict[str, str]]):
    retries = max(0, int(cfg.max_retries or 0))
    backoff_ms = max(0, int(cfg.retry_backoff_ms or 0))
    timeout_s = max(1000, int(cfg.timeout_ms or 45000)) / 1000.0
    last_error: Exception | None = None

    for cfg_idx, active_cfg in enumerate(_iter_policy_configs(cfg)):
        req = llm.request_from_config(
            active_cfg, messages,
            temperature=active_cfg.temperature, max_tokens=active_cfg.max_tokens, top_p=active_cfg.top_p,
        )

        for attempt in range(1, retries + 2):
            try:
                completion = await asyncio.wait_for(llm.complete(req), timeout=timeout_s)
                return completion, active_cfg, attempt, cfg_idx > 0
            except Exception as e:
                last_error = e
                if attempt <= retries and backoff_ms > 0:
                    await asyncio.sleep((backoff_ms * attempt) / 1000.0)

    raise last_error or RuntimeError("LLM completion failed")


async def _validate_provider(req: ProviderValidateRequest) -> ProviderValidateResponse:
    provider = req.provider.lower().strip()
    model = (req.model or DEFAULT_MODELS.get(provider, "gpt-4o")).strip()
    api_key = (req.api_key or "").strip()

    if provider in {"mock", "local"}:
        return ProviderValidateResponse(
            provider=provider,
            model=model,
            ok=True,
            message="Provider does not require an API key.",
            latency_ms=0,
        )

    if _provider_needs_key(provider) and not api_key:
        return ProviderValidateResponse(
            provider=provider,
            model=model,
            ok=False,
            message="Missing API key.",
            latency_ms=0,
        )

    cfg = LLMConfig(provider=provider, model=model, api_key=api_key, base_url=req.base_url or "")
    t0 = time.monotonic()

    try:
        completion = await asyncio.wait_for(
            llm.complete(llm.request_from_config(
                cfg, [{"role": "user", "content": "Reply with OK"}], max_tokens=8, temperature=0,
            )),
            timeout=15,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        text = completion.text.strip()
        return ProviderValidateResponse(
            provider=provider,
            model=model,
            ok=True,
            message=text[:120] if text else "Connection successful.",
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return ProviderValidateResponse(
            provider=provider,
            model=model,
            ok=False,
            message=str(e)[:240],
            latency_ms=latency_ms,
        )

# Shared mutable config — owned here, exposed via /api/config
_current_config: LLMConfig = LLMConfig()


def get_current_config() -> LLMConfig:
    return _current_config


def set_current_config(cfg: LLMConfig) -> LLMConfig:
    global _current_config
    _current_config = cfg
    return _current_config


@router.get("/api/config", response_model=LLMConfig)
def get_config():
    masked_key = ""
    if _current_config.api_key:
        k = _current_config.api_key
        masked_key = f"{k[:4]}...{k[-4:]}" if len(k) > 8 else "***"
    cfg = _current_config.model_dump()
    cfg["api_key_masked"] = masked_key
    return cfg


@router.post("/api/config", response_model=LLMConfig)
def update_config(new_config: LLMConfig):
    updated = set_current_config(new_config)
    logger.info(f"Updated LLM Config: provider={new_config.provider}, model={new_config.model}")
    return updated


_OLLAMA_FALLBACK_MODELS = ["llama3.2", "llama3.1", "mistral", "deepseek-r1", "qwen2.5-coder", "phi3"]


async def _fetch_ollama_models(base_url: str = "http://localhost:11434") -> list:
    """Query Ollama /api/tags and return a list of model name strings.
    Falls back to _OLLAMA_FALLBACK_MODELS if Ollama is unreachable."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m["name"] for m in data.get("models", []) if "name" in m]
                logger.info(f"[Ollama] fetched {len(models)} model(s): {models}")
                if models:
                    return models
    except Exception as e:
        logger.warning(f"[Ollama] could not fetch models: {e}")
    return _OLLAMA_FALLBACK_MODELS


async def _fetch_llamacpp_models(base_url: str = "") -> list:
    """Query llama-server's OpenAI-compatible /v1/models for the loaded model(s).
    llama-server serves one model per process, so this is usually a single entry."""
    base = (base_url or os.environ.get("LLAMACPP_API_BASE") or "http://localhost:8080").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base}/v1/models")
            if resp.status_code == 200:
                models = [m["id"] for m in resp.json().get("data", []) if "id" in m]
                logger.info(f"[llama.cpp] fetched {len(models)} model(s): {models}")
                if models:
                    return models
    except Exception as e:
        logger.warning(f"[llama.cpp] could not fetch models: {e}")
    return ["default"]


async def _fetch_jan_models(base_url: str = "") -> list:
    """Query Jan's local API server (/v1/models). Jan requires its API key when one is set,
    which the catalog only has via JAN_API_KEY; on 401 or no server, fall back to 'default'."""
    from models import JAN_DEFAULT_BASE
    key = os.environ.get("JAN_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{(base_url or JAN_DEFAULT_BASE).rstrip('/')}/models",
                                    headers={"Authorization": f"Bearer {key}"} if key else {})
            if resp.status_code == 200:
                models = [m["id"] for m in resp.json().get("data", []) if "id" in m]
                if models:
                    return models
    except Exception as e:
        logger.info(f"[Jan] could not fetch models: {e}")
    return ["default"]


def _strip_v1(base_url: str) -> str:
    """Ollama's native /api/* routes live beside its OpenAI-compatible /v1."""
    base = (base_url or "").rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


@router.get("/api/models")
async def get_supported_models():
    from services import llm_settings
    # Local servers are asked at the address set in Settings → Model backends, if any
    bases = {p: llm_settings.effective(p)["base_url"] for p in ("ollama", "llamacpp")}
    ollama_models, llamacpp_models = await asyncio.gather(
        _fetch_ollama_models(_strip_v1(bases["ollama"]) or "http://localhost:11434"),
        _fetch_llamacpp_models(bases["llamacpp"]))
    local = {"ollama": ollama_models, "llamacpp": llamacpp_models}
    return {"providers": [{**p, "models": local[p["id"]]} if p["id"] in local else dict(p)
                          for p in PROVIDERS]}


@router.post("/api/providers/validate", response_model=ProviderValidateResponse)
async def validate_provider(req: ProviderValidateRequest):
    return await _validate_provider(req)


@router.post("/api/providers/validate-all")
async def validate_all_providers(req: ProviderBulkValidateRequest):
    results: List[ProviderValidateResponse] = []
    for provider, key in req.credentials.items():
        trimmed = (key or "").strip()
        if not trimmed:
            continue
        probe_req = ProviderValidateRequest(
            provider=provider,
            model=req.models.get(provider) or DEFAULT_MODELS.get(provider, "gpt-4o"),
            api_key=trimmed,
        )
        results.append(await _validate_provider(probe_req))

    return {"results": [r.model_dump() for r in results]}


@router.post("/api/run", response_model=PromptRunResponse)
async def run_prompt(req: PromptRunRequest):
    cfg = req.config or _current_config
    prompt = req.prompt.strip()

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    # ── Cache check ──────────────────────────────────────────────────────────
    cache_hit = False
    cache_meta: Dict[str, Any] = {}
    cache_key = None
    ttl_seconds = 3600
    scope = "prompt"

    if req.cache_config:
        c_cfg = req.cache_config
        scope = c_cfg.get("scope", "prompt")
        ttl_seconds = int(c_cfg.get("ttl_seconds", 3600))
        cache_key = make_cache_key(prompt, cfg, scope)
        conn = get_db_connection()
        cached = cache_get(conn, cache_key)
        conn.close()
        if cached:
            cache_hit = True
            cache_meta = {
                "cache_hit": True,
                "cache_key": cache_key[:12] + "…",
                "scope": scope,
                "hit_count": cached["hit_count"],
            }
            logger.info(f"Cache HIT: key={cache_key[:12]}… scope={scope} hits={cached['hit_count']}")
            return PromptRunResponse(
                success=True,
                provider=cached["provider"],
                model=cached["model"],
                output=f"⚡ [Cache Hit — {scope} scope, {cached['hit_count']} hits]\n\n{cached['output']}",
                tools_used=[],
                metadata=cache_meta,
            )
        cache_meta = {
            "cache_hit": False,
            "cache_key": cache_key[:12] + "…",
            "scope": scope,
            "ttl_seconds": ttl_seconds,
        }

    # ── Middleware pre-flight (rate limiter + content moderation) ────────────
    blocked, throttled, _ = check_prompt_middleware(req.middleware_configs, prompt, req.session_id)
    if blocked:
        raise HTTPException(status_code=429 if throttled else 400, detail=blocked)

    # ── Tool injection ───────────────────────────────────────────────────────
    tools_used: List[Dict[str, Any]] = []
    tool_context_injection = ""
    if req.attached_tools:
        for t in req.attached_tools:
            t_name = t.get("label") or t.get("tool_type", "Tool")
            t_type = t.get("tool_type", "tool")
            t_output = f"Result from {t_name}: Processed input '{prompt[:40]}...'"
            tools_used.append({"tool": t_name, "type": t_type, "status": "executed", "output": t_output})
            tool_context_injection += f"\n[Attached Tool '{t_name}' Output]: {t_output}\n"

    final_system_prompt = cfg.system_prompt or ""
    if tool_context_injection:
        final_system_prompt += f"\n\nContext from Connected Tools:{tool_context_injection}"
    grounding = get_grounding_config(req.middleware_configs)
    if grounding is not None and grounding.get("inject_instruction", True):
        final_system_prompt = f"{final_system_prompt}\n\n{GROUNDING_INSTRUCTION}".strip()

    # ── Memory load ──────────────────────────────────────────────────────────
    memory_history: List[Dict[str, Any]] = []
    memory_meta: Dict[str, Any] = {}
    who = ltm.current()   # tenant / project (and end user) this run's memory belongs to
    if req.session_id and req.memory_config:
        mem_cfg = req.memory_config
        token_budget = int(mem_cfg.get("token_budget") or 4096)
        strategy = mem_cfg.get("strategy") or "sliding_window"
        raw_msgs = await asyncio.to_thread(ltm.load_messages, who, req.session_id,
                                           ltm.session_ttl_hours(mem_cfg))
        trimmed = trim_to_budget(raw_msgs, token_budget, strategy)
        memory_history = [{"role": m["role"], "content": m["content"]} for m in trimmed]
        memory_meta = {
            "session_id": req.session_id,
            "messages_in_context": len(memory_history),
            "tokens_in_context": sum(m["token_count"] for m in trimmed),
            "strategy": strategy,
            "token_budget": token_budget,
        }
        logger.info(
            f"Memory: session={req.session_id} loaded {len(memory_history)} "
            f"messages ({memory_meta['tokens_in_context']} tokens)"
        )
    long_term = await asyncio.to_thread(ltm.active, req.memory_config, who)
    if long_term:
        remembered = await asyncio.to_thread(ltm.recall, who, prompt,
                                             int(req.memory_config.get("recall_k") or ltm.DEFAULT_RECALL_K))
        if remembered:
            memory_history = [{"role": "system", "content": ltm.context_block(remembered)}, *memory_history]
            memory_meta["long_term_facts"] = len(remembered)

    # ── Persist exchange helper ──────────────────────────────────────────────
    async def _persist_exchange(user_content: str, assistant_content: str) -> None:
        if req.session_id:
            await asyncio.to_thread(ltm.append_messages, who, req.session_id, [
                ("user", user_content, rough_token_count(user_content)),
                ("assistant", assistant_content, rough_token_count(assistant_content))])
        if long_term and req.memory_config.get("extract", True):
            await asyncio.to_thread(ltm.queue_extraction, who, cfg, req.app_id, user_content, assistant_content,
                                    cfg.api_key)
        if cache_key and req.cache_config and not cache_hit:
            conn = get_db_connection()
            cache_set(conn, cache_key, scope, user_content, assistant_content, cfg, ttl_seconds)
            conn.close()
            logger.info(f"Cache STORE: key={cache_key[:12]}… ttl={ttl_seconds}s scope={scope}")

    # ── Mock / no-key path ───────────────────────────────────────────────────
    if cfg.provider == "mock" or not _can_attempt_real_call(cfg):
        tools_summary = ""
        if tools_used:
            tools_summary = "\n\n🛠️ Tools executed:\n" + "\n".join(
                f"  - {t['tool']} ({t['type']}): ✓ OK" for t in tools_used
            )
        mem_summary = (
            f"\n\n🧠 Memory: {len(memory_history)} messages from session '{req.session_id}'."
            if memory_history else ""
        )
        simulated_text = (
            f"[Simulated {cfg.provider.upper()} — {cfg.model}]\n"
            f"Temp={cfg.temperature}  MaxTokens={cfg.max_tokens}  TopP={cfg.top_p}\n\n"
            f"Prompt: {prompt}{tools_summary}{mem_summary}\n\n"
            f"Answer: Add a real API key on the LLM node to call a live model."
        )
        blocked, mw_flags = check_response_middleware(req.middleware_configs, simulated_text, req.session_id)
        if blocked:
            raise HTTPException(status_code=400, detail=blocked)
        await _persist_exchange(prompt, simulated_text)
        return PromptRunResponse(
            success=True, provider=cfg.provider, model=cfg.model,
            output=simulated_text, tools_used=tools_used,
            metadata={"simulated": True, **memory_meta, **cache_meta,
                      **({"middleware_flags": mw_flags} if mw_flags else {})},
        )

    # ── Spend budget gate ───────────────────────────────────────────────────
    if _provider_needs_key(cfg.provider):
        _budget = check_budget(req.app_id)
        if _budget["blocked"]:
            raise HTTPException(status_code=429, detail=f"Budget exceeded — {_budget['message']}")

    # ── LLM gateway — our adapters, or the optional LiteLLM fallback ─────────
    messages: List[Dict[str, str]] = []
    if final_system_prompt:
        messages.append({"role": "system", "content": final_system_prompt})
    messages.extend(memory_history)
    messages.append({"role": "user", "content": prompt})

    run_id = str(uuid.uuid4())
    t_start = time.monotonic()
    attempt_count = 1
    used_fallback = False
    effective_provider = cfg.provider
    effective_model = cfg.model

    try:
        completion, active_cfg, attempt_count, used_fallback = await _completion_with_policy(cfg, messages)
        effective_provider = active_cfg.provider
        effective_model = active_cfg.model
        latency_ms = int((time.monotonic() - t_start) * 1000)
        output = completion.text
        usage = {}
        prompt_tokens = completion_tokens = total_tokens = 0
        if completion.usage:
            usage = completion.usage.as_dict()
            prompt_tokens = usage["prompt_tokens"]
            completion_tokens = usage["completion_tokens"]
            total_tokens = usage["total_tokens"]
        cost_usd = round(completion.cost_usd, 6)

        meta_dict = {
            "finish_reason": completion.finish_reason,
            "tools_used": tools_used,
            "memory_meta": memory_meta,
            "cache_meta": cache_meta,
        }
        grounding_context = None
        if grounding is not None:
            grounding_context = "\n".join([final_system_prompt, *(m["content"] for m in memory_history), prompt])
        blocked, mw_flags = check_response_middleware(
            req.middleware_configs, output, req.session_id, total_tokens, cost_usd,
            context=grounding_context,
        )
        if not blocked:
            blocked, rule_flags = await check_custom_rules(req.middleware_configs, prompt, output, active_cfg)
            mw_flags = mw_flags + rule_flags
        if mw_flags:
            meta_dict["middleware_flags"] = mw_flags
        write_trace(
            run_id=run_id,
            app_id=req.app_id,
            node_id=req.node_id,
            node_type="llm",
            provider=effective_provider,
            model=effective_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            attempt_count=attempt_count,
            used_fallback=used_fallback,
            effective_provider=effective_provider,
            effective_model=effective_model,
            status="error" if blocked else "success",
            error=blocked,
            prompt_preview=prompt[:4000] if prompt else None,
            output_preview=output[:4000] if output and not blocked else None,
            metadata_json=json.dumps(meta_dict),
        )
        if blocked:
            raise HTTPException(status_code=400, detail=blocked)

        await _persist_exchange(prompt, output)
        return PromptRunResponse(
            success=True, provider=effective_provider, model=effective_model, output=output,
            tools_used=tools_used,
            metadata={
                "run_id": run_id,
                "latency_ms": latency_ms,
                "usage": usage,
                "finish_reason": completion.finish_reason,
                "cost_usd": cost_usd,
                "attempt_count": attempt_count,
                "used_fallback": used_fallback,
                "effective_provider": effective_provider,
                "effective_model": effective_model,
                **memory_meta, **cache_meta,
                **({"middleware_flags": mw_flags} if mw_flags else {}),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        latency_ms = int((time.monotonic() - t_start) * 1000)
        write_trace(
            run_id=run_id,
            app_id=req.app_id,
            node_id=req.node_id,
            node_type="llm",
            provider=effective_provider,
            model=effective_model,
            attempt_count=attempt_count,
            used_fallback=used_fallback,
            effective_provider=effective_provider,
            effective_model=effective_model,
            latency_ms=latency_ms,
            status="error",
            error=str(e),
            prompt_preview=prompt[:4000] if prompt else None,
        )
        logger.error(f"LLM error [{cfg.provider}/{cfg.model}]: {e}")
        raise HTTPException(status_code=500, detail=str(e))
