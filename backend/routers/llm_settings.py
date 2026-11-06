"""
llm_settings.py — Settings → Model backends.

GET    /api/llm-settings                    — every provider: backends that can serve it, the
                                              project / workspace settings, and what's in effect
PUT    /api/llm-settings/{provider}         — set the backend and/or base URL (scope: project | workspace);
                                              fields left out keep their saved value
DELETE /api/llm-settings/{provider}?scope=  — clear one scope's setting
POST   /api/llm-settings/{provider}/test    — one tiny real call through a backend; reports
                                              which backend answered and how fast

Uses the ``secrets`` ACL, like model provider keys (read to view and test, write to change).
Resolution order and caching: services/llm_settings.py.
"""

import asyncio
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import llm
from llm.backends import ADAPTER_FIRST, BACKENDS
from llm.backends.openai_compat import PROVIDERS as OPENAI_COMPAT_PROVIDERS
from llm.backends.watsonx import DEFAULT_BASE as WATSONX_DEFAULT_BASE
from llm.catalog import PROVIDERS, DEFAULT_MODELS
from routers import run as run_router
from routers.run import _strip_v1
from services import llm_settings
from services.acl import has_access, require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/llm-settings", tags=["llm-settings"])

BACKEND_LABELS = {
    "litellm": "LiteLLM (legacy fallback)",
    "openai_compat": "Built-in (OpenAI-compatible)",
    "anthropic": "Built-in (Anthropic SDK)",
    "gemini": "Built-in (Gemini)",
    "bedrock": "Built-in (AWS Bedrock)",
    "watsonx": "Built-in (IBM watsonx)",
    "mistral": "Built-in (Mistral native)",
    "cohere": "Built-in (Cohere v2 native)",
    "ollama": "Built-in (Ollama native)",
}
HIDDEN_PROVIDERS = {"mock"}
TEST_TIMEOUT_S = 30.0


class SettingUpdate(BaseModel):
    backend: Optional[str] = Field(default=None, max_length=64, description="auto | a backend id that serves this provider; None = keep")
    base_url: Optional[str] = Field(default=None, max_length=1024, description='"" = the provider default; None = keep')
    scope: Literal["project", "workspace"] = "project"


class TestRequest(BaseModel):
    backend: Optional[str] = Field(default=None, max_length=64, description="None = the setting in effect")
    base_url: Optional[str] = Field(default=None, max_length=1024, description="None = the setting in effect")
    model: Optional[str] = Field(default=None, max_length=256, description="None = a default model for the provider")


def _provider(provider_id: str) -> Dict[str, Any]:
    pid = (provider_id or "").strip().lower()
    for p in PROVIDERS:
        if p["id"] == pid and pid not in HIDDEN_PROVIDERS:
            return p
    raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")


def _default_base_url(pid: str) -> str:
    if pid in OPENAI_COMPAT_PROVIDERS:
        return OPENAI_COMPAT_PROVIDERS[pid].base_url
    if pid == "watsonx":
        return WATSONX_DEFAULT_BASE
    return ""


def _public(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {k: row[k] for k in ("backend", "base_url", "updated_by", "updated_at")}


@router.get("")
def list_settings(request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "secrets", "read")
    rows = llm_settings.rows_for(ctx.tenant_id, ctx.project_id)
    scope = (ctx.tenant_id, ctx.project_id)
    providers: List[Dict[str, Any]] = []
    for p in PROVIDERS:
        pid = p["id"]
        if pid in HIDDEN_PROVIDERS:
            continue
        eff = llm_settings.effective(pid, scope)
        try:
            serving = llm.backend_for(pid, eff["backend"]).id
        except llm.BackendUnavailable:
            serving = None
        levels = rows.get(pid, {})
        providers.append({
            "id": pid,
            "name": p["name"],
            "local": bool(p.get("local")),
            "backends": llm.backends_for(pid),
            "default_base_url": _default_base_url(pid),
            "project": _public(levels.get("project")),
            "workspace": _public(levels.get("shared")),
            "effective": {**eff, "serving_backend": serving},
        })
    return {
        "can_edit": has_access(ctx, "secrets", "write"),
        "backends": [{"id": b.id, "label": BACKEND_LABELS.get(b.id, b.id)} for b in BACKENDS],
        "providers": providers,
    }


@router.post("/migrate-litellm")
def migrate_litellm_overrides(request: Request, scope: Literal["project", "workspace"] = "project", dry_run: bool = False):
    """Replace explicit ``litellm`` rows with ``auto`` for providers with built-in adapters."""
    ctx = get_request_context(request)
    require_access(ctx, "secrets", "write")
    rows = llm_settings.rows_for(ctx.tenant_id, ctx.project_id)
    level = "project" if scope == "project" else "shared"
    target_project = None if scope == "workspace" else ctx.project_id
    updated: List[Dict[str, Any]] = []
    for p in PROVIDERS:
        pid = p["id"]
        row = (rows.get(pid) or {}).get(level)
        if not row or (row.get("backend") or "").strip().lower() != "litellm" or pid not in ADAPTER_FIRST:
            continue
        serving = llm.backend_for(pid, "auto").id
        updated.append({"provider": pid, "from": "litellm", "to": "auto", "serving_backend": serving})
        if not dry_run:
            llm_settings.set_setting(
                ctx.tenant_id, target_project, ctx.user_id, pid,
                "auto", None, llm.backends_for(pid),
            )
    return {"scope": scope, "dry_run": dry_run, "updated_count": len(updated), "updated": updated}


@router.put("/{provider}")
def update_setting(provider: str, body: SettingUpdate, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "secrets", "write")
    pid = _provider(provider)["id"]
    try:
        return llm_settings.set_setting(
            ctx.tenant_id, None if body.scope == "workspace" else ctx.project_id, ctx.user_id,
            pid, body.backend, body.base_url, llm.backends_for(pid),
        )
    except llm_settings.SettingsError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{provider}", status_code=204)
def clear_setting(provider: str, request: Request, scope: Literal["project", "workspace"] = "project"):
    ctx = get_request_context(request)
    require_access(ctx, "secrets", "write")
    pid = _provider(provider)["id"]
    llm_settings.clear_setting(ctx.tenant_id, None if scope == "workspace" else ctx.project_id, pid)


async def _test_model(pid: str, base_url: str) -> str:
    """A model the server actually has, for local providers; a cheap default otherwise."""
    if pid == "ollama":
        return (await run_router._fetch_ollama_models(_strip_v1(base_url) or "http://localhost:11434"))[0]
    if pid == "llamacpp":
        return (await run_router._fetch_llamacpp_models(base_url))[0]
    if pid == "jan":
        return (await run_router._fetch_jan_models(base_url))[0]
    return DEFAULT_MODELS.get(pid, "")


@router.post("/{provider}/test")
async def test_setting(provider: str, body: TestRequest, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "secrets", "read")
    pid = _provider(provider)["id"]
    eff = llm_settings.effective(pid)
    backend_id = (body.backend or eff["backend"]).strip().lower()
    base_url = (body.base_url if body.base_url is not None else eff["base_url"]).strip()
    try:
        serving = llm.backend_for(pid, backend_id).id
    except llm.BackendUnavailable as e:
        raise HTTPException(status_code=400, detail=str(e))
    model = (body.model or "").strip() or await _test_model(pid, base_url)
    if not model:
        raise HTTPException(status_code=400, detail=f"No default test model for {pid} — pass one")

    t0 = time.monotonic()
    try:
        resp = await asyncio.wait_for(
            llm.complete(llm.LLMRequest(
                provider=pid, model=model, messages=[{"role": "user", "content": "Reply with OK"}],
                base_url=base_url or None, max_tokens=8, temperature=0,
            ), backend_id=serving),
            timeout=TEST_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        return {"ok": False, "backend": serving, "model": model, "latency_ms": int(TEST_TIMEOUT_S * 1000),
                "message": f"No answer within {int(TEST_TIMEOUT_S)} s"}
    except Exception as e:  # noqa: BLE001 — any failure is the test result
        return {"ok": False, "backend": serving, "model": model,
                "latency_ms": int((time.monotonic() - t0) * 1000), "message": str(e)[:300]}
    return {"ok": True, "backend": resp.backend, "model": model,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "message": (resp.text or "").strip()[:120] or "Connected"}
