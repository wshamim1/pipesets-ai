"""
v1_tools.py — custom tools as code: what ``pipesets tool deploy / list / versions / rollback / run``
call (services/tool_store.py). API-key authenticated, like the rest of /v1.

GET  /v1/tools                          — the project's custom tools                (tools:read)
GET  /v1/tools/{name}                   — one tool, with its code and schema        (tools:read)
PUT  /v1/tools/{name}                   — deploy: create, or a new version when the content
                                          changed; the same content again is a no-op  (tools:write)
GET  /v1/tools/{name}/versions[/{v}]    — history / one version's code              (tools:read)
POST /v1/tools/{name}/rollback          — new version with an earlier one's content (tools:write)
POST /v1/tools/{name}/run               — run it in the server's sandbox            (tools:execute)

Tools deployed here are marked ``source: sdk`` and are read-only in the UI (fork to edit a copy).
A name used by several tools in the project is a 409 until they are renamed. Deploys and
rollbacks are recorded in the audit log under the key's owner, with the key named.
"""

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services import tool_store
from services.api_keys import ApiKeyPrincipal, require_scope

router = APIRouter(prefix="/v1/tools", tags=["v1"])


class ToolDeploy(BaseModel):
    code: str = Field(..., min_length=1)
    description: str = ""
    icon: str = "🔧"
    requirements: List[str] = Field(default_factory=list)
    config_keys: List[str] = Field(default_factory=list, description="secret / config keys the tool reads")
    note: Optional[str] = Field(default=None, max_length=500, description="e.g. the git commit")


class ToolRollback(BaseModel):
    version: int = Field(..., ge=1)


class ToolRun(BaseModel):
    args: Optional[Dict[str, Any]] = None
    input: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    version: Optional[int] = None


def _summary(tool: Dict[str, Any]) -> Dict[str, Any]:
    sig = tool.get("signature") or {}
    return {"id": tool.get("id") or tool.get("tool_id"), "name": tool["name"], "version": tool["version"],
            "source": tool.get("source"), "description": tool.get("description"), "parameters": sig.get("parameters"),
            "legacy": sig.get("legacy"), "updated_at": tool.get("updated_at") or tool.get("created_at")}


def _one(name: str, p: ApiKeyPrincipal) -> Dict[str, Any]:
    found = tool_store.find_by_name(name, p.ctx.tenant_id, p.ctx.project_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"No tool named '{name}'")
    if len(found) > 1:
        raise HTTPException(status_code=409, detail=f"{len(found)} tools are named '{name}' in this project; rename "
                                                    "all but one in the UI to deploy by name")
    return found[0]


def _audit(p: ApiKeyPrincipal, request: Request, action: str, tool: Dict[str, Any]) -> None:
    from services import audit
    audit.record(tenant_id=p.ctx.tenant_id, project_id=p.ctx.project_id, actor=p.ctx.user_id, action=action,
                 target_id=f"{tool['id']} v{tool['version']}", outcome="success", status=200, method="PUT",
                 path=f"/v1/tools/{tool['name']} · key {p.name} ({p.key_id})",
                 ip=request.client.host if request.client else "")


@router.get("")
def list_tools(p: ApiKeyPrincipal = Depends(require_scope("tools:read"))):
    return {"data": [_summary(t) for t in tool_store.list_tools(p.ctx.tenant_id, p.ctx.project_id)]}


@router.get("/{name}")
def get_tool(name: str, p: ApiKeyPrincipal = Depends(require_scope("tools:read"))):
    tool = _one(name, p)
    return {**_summary(tool), "code": tool["code"], "requirements": tool["requirements"],
            "config_keys": tool["config_keys"], "entrypoint": (tool["signature"] or {}).get("entrypoint")}


@router.put("/{name}")
def deploy_tool(name: str, body: ToolDeploy, request: Request, p: ApiKeyPrincipal = Depends(require_scope("tools:write"))):
    found = tool_store.find_by_name(name, p.ctx.tenant_id, p.ctx.project_id)
    if len(found) > 1:
        _one(name, p)   # raises the 409
    try:
        tool, changed = tool_store.save(
            p.ctx.tenant_id, p.ctx.project_id, p.ctx.user_id, name=name, code=body.code, description=body.description,
            icon=body.icon, config_keys=body.config_keys, requirements=body.requirements, source="sdk", note=body.note,
            tool_id=found[0]["id"] if found else None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if changed:
        _audit(p, request, "custom_tool.deploy", tool)
    return {**_summary(tool), "created": not found, "changed": changed}


@router.get("/{name}/versions")
def list_versions(name: str, p: ApiKeyPrincipal = Depends(require_scope("tools:read"))):
    tool = _one(name, p)
    return {"current": tool["version"],
            "data": tool_store.list_versions(tool["id"], p.ctx.tenant_id, p.ctx.project_id)}


@router.get("/{name}/versions/{version}")
def get_version(name: str, version: int, p: ApiKeyPrincipal = Depends(require_scope("tools:read"))):
    tool = _one(name, p)
    found = tool_store.get_version(tool["id"], version, p.ctx.tenant_id, p.ctx.project_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"'{name}' has no version {version}")
    return {**_summary(found), "id": tool["id"], "code": found["code"], "requirements": found["requirements"],
            "config_keys": found["config_keys"], "note": found.get("note")}


@router.post("/{name}/rollback")
def rollback(name: str, body: ToolRollback, request: Request, p: ApiKeyPrincipal = Depends(require_scope("tools:write"))):
    tool = _one(name, p)
    try:
        rolled = tool_store.rollback(tool["id"], body.version, p.ctx.tenant_id, p.ctx.project_id, p.ctx.user_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"'{name}' has no version {body.version}")
    _audit(p, request, "custom_tool.rollback", rolled)
    return _summary(rolled)


@router.post("/{name}/run")
async def run_tool(name: str, body: ToolRun, p: ApiKeyPrincipal = Depends(require_scope("tools:execute"))):
    """Run the tool (latest, or ``version``) in the server sandbox — what a pipeline would do."""
    from routers.custom_tools import _exec_tool_code
    from services import secret_store

    tool = _one(name, p)
    if body.version:
        pinned = tool_store.get_version(tool["id"], body.version, p.ctx.tenant_id, p.ctx.project_id)
        if not pinned:
            raise HTTPException(status_code=404, detail=f"'{name}' has no version {body.version}")
        tool = pinned
    token = secret_store.request_scope.set((p.ctx.tenant_id, p.ctx.project_id))   # secret:// refs in config
    t0 = time.monotonic()
    try:
        config = secret_store.resolve_refs(body.config)
        output = await _exec_tool_code(tool["code"], body.input, config, tool["requirements"], body.args)
        ok, error = True, None
    except (RuntimeError, secret_store.SecretError) as e:
        output, ok, error = "", False, str(e)
    finally:
        secret_store.request_scope.reset(token)
    return {"ok": ok, "output": output, "error": error, "version": tool["version"],
            "duration_ms": int((time.monotonic() - t0) * 1000)}
