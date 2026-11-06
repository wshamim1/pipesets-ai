"""
custom_tools.py — User-defined Python tools.

A custom tool is a Python snippet that defines one function — typed, so the model calls it with
real arguments (services/tool_signature.py):

    @tool(description="Weather for a city")
    def weather(city: str, units: Literal["metric", "imperial"] = "metric", *, config) -> str: ...

or the legacy form, which gets one input string:

    def run(input_text: str, config: dict) -> str:
        ...
        return "result string"

Every content change is a new version (services/tool_store.py); a node pins one with
``tool_version`` in its config. Tools deployed from the SDK are read-only here: fork to edit a copy.

It runs in a separate sandboxed process (services/sandbox.py), never inside the backend:

  CUSTOM_TOOL_SANDBOX  local (default) — subprocess with a scrubbed env and throwaway cwd.
                       Not isolation: it can still read files the backend user can.
                       container — podman/docker with network on (CUSTOM_TOOL_IMAGE, default
                       python:3.12-slim).
                       auto — container if an engine is reachable, otherwise local.
                       Default when SANDBOX_URL is set: auto, i.e. the sandbox runner.
  SANDBOX_REQUIRE_ISOLATION=1 makes the default auto-without-fallback.
  CUSTOM_TOOL_TIMEOUT (seconds, default 30), CUSTOM_TOOL_MEMORY_MB (default 1024).

A tool's ``requirements`` (pip specs) are installed into that tool's own sandbox environment —
a cached image or venv keyed by the specs (services/sandbox.py) — never into the backend.
A tool without requirements runs on the base image / the backend's Python.

Tools are stored in SQLite and appear in the sidebar catalog.

Endpoints
---------
GET    /api/custom-tools              — list all custom tools
POST   /api/custom-tools              — create (JSON body)
PUT    /api/custom-tools/{id}         — update
DELETE /api/custom-tools/{id}         — delete
POST   /api/custom-tools/upload       — create from uploaded .py file
POST   /api/custom-tools/{id}/execute — run a saved custom tool (input_text, or args when typed)
POST   /api/custom-tools/execute-code — run ad-hoc code (test before saving)
POST   /api/custom-tools/signature    — the schema the code would have (nothing runs)
GET    /api/custom-tools/{id}/versions[/{v}] — history / one version's code
POST   /api/custom-tools/{id}/rollback — new version with an earlier version's content
POST   /api/custom-tools/{id}/fork    — an editable copy (e.g. of an SDK-deployed tool)
"""

import json
import os
from typing import Annotated, Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from pydantic import AfterValidator, BaseModel

from db import get_db_connection
from services import sandbox, tool_store
from services.tool_signature import ToolCodeError, analyze, single_text_parameter, validate_args
from services.acl import require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/custom-tools", tags=["custom-tools"])


# ── Pydantic models ────────────────────────────────────────────────────────────

# pip specs, e.g. ["requests>=2.31", "boto3"]; a bad one is a 422 naming it
Requirements = Annotated[List[str], AfterValidator(sandbox.normalize_requirements)]


class CustomToolCreate(BaseModel):
    name: str
    icon: str = "🔧"
    description: str = ""
    code: str
    config_keys: List[str] = []   # e.g. ["credential_id", "token", "job_id"]
    requirements: Requirements = []


class CustomToolUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    code: Optional[str] = None
    config_keys: Optional[List[str]] = None
    requirements: Optional[Requirements] = None


class CustomToolExecuteRequest(BaseModel):
    tool_id: str = ""
    input_text: str = ""
    config: Dict[str, Any] = {}
    args: Optional[Dict[str, Any]] = None   # typed tools: the arguments the model would send


class AdHocExecuteRequest(BaseModel):
    code: str
    input_text: str = ""
    config: Dict[str, Any] = {}
    requirements: Requirements = []
    args: Optional[Dict[str, Any]] = None


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_tool(tool_id: str, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    return tool_store.get(tool_id, tenant_id, project_id)


def _require_tool(tool_id: str, ctx) -> Dict[str, Any]:
    tool = _get_tool(tool_id, ctx.tenant_id, ctx.project_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Custom tool not found")
    return tool


def _save(ctx, **fields) -> Dict[str, Any]:
    try:
        tool, _ = tool_store.save(ctx.tenant_id, ctx.project_id, ctx.user_id, **fields)
    except ValueError as e:   # code that can't be a tool, or a bad requirement
        raise HTTPException(status_code=422, detail=str(e))
    return tool


# ── Execute helper (shared between save+execute and ad-hoc) ───────────────────

def _sandbox_cfg(requirements: Optional[List[str]] = None) -> Dict[str, Any]:
    # With a sandbox runner (or isolation required) tools go through auto → remote / container
    default = "auto" if sandbox.isolation_required() or sandbox.remote_url() else "local"
    return {
        "requirements": requirements or [],
        "backend": os.getenv("CUSTOM_TOOL_SANDBOX") or default,
        "image": os.getenv("CUSTOM_TOOL_IMAGE") or None,
        "timeout": int(os.getenv("CUSTOM_TOOL_TIMEOUT") or 30),
        "memory_mb": int(os.getenv("CUSTOM_TOOL_MEMORY_MB") or 1024),
        "allow_network": True,   # tools typically call external APIs
    }


def _call(code: str, input_text: str, args: Optional[Dict[str, Any]]) -> Tuple[Optional[Any], Optional[str]]:
    """(signature, error) for running ``code`` with plain text or ``args``. A typed tool given only
    text gets it as its one text parameter."""
    try:
        sig = analyze(code)
    except ToolCodeError as e:
        return None, str(e)
    if sig.legacy or args is not None:
        return sig, None
    param = single_text_parameter(sig.parameters)
    if not param:
        return sig, f"'{sig.name}' takes {', '.join(sig.parameters.get('properties', {}))}; call it with arguments"
    return sig, None


async def _exec_tool_code(code: str, input_text: str, config: Dict[str, Any],
                          requirements: Optional[List[str]] = None, args: Optional[Dict[str, Any]] = None) -> str:
    """
    Run a tool's code in the sandbox with its requirements installed: legacy run(input_text, config),
    or a typed tool with ``args`` (validated against its schema first).
    Returns the string result or raises RuntimeError.
    """
    sig, error = _call(code, input_text, args)
    if error:
        raise RuntimeError(error)
    if sig.legacy:
        return await sandbox.run_tool(code, input_text, config, _sandbox_cfg(requirements))
    if args is None:
        args = {single_text_parameter(sig.parameters): input_text}
    problem = validate_args(sig.parameters, args)
    if problem:
        raise RuntimeError(f"Invalid arguments for {sig.name}: {problem}")
    return await sandbox.run_tool(code, input_text, config, _sandbox_cfg(requirements), entrypoint=sig.entrypoint,
                                  args=args, takes_config=sig.takes_config)


# ── Public execute function (called from tools.py execute_tool_real) ──────────

async def execute_custom_tool(tool_id: str, input_text: str, config: Dict[str, Any],
                              args: Optional[Dict[str, Any]] = None) -> str:
    """Called from execute_tool_real for tool_type == 'custom_<id>'. Looks the tool up in the run's
    tenant / project only; ``tool_version`` in the node config pins a version."""
    cfg = dict(config or {})
    version = cfg.pop("tool_version", None)
    tool = tool_store.for_run(tool_id, version if version not in ("", "latest") else None)
    if not tool:
        return f"[Custom tool not found: {tool_id}{f' v{version}' if version else ''}]"
    try:
        return await _exec_tool_code(tool["code"], input_text, cfg, tool["requirements"], args)
    except RuntimeError as e:
        return f"[Custom tool error] {e}"


def _public(tool: Dict[str, Any]) -> Dict[str, Any]:
    """A tool for the UI: its fields plus the parameter schema, and whether the UI may edit it."""
    sig = tool.get("signature") or {}
    return {**{k: v for k, v in tool.items() if k != "signature"}, "parameters": sig.get("parameters"),
            "entrypoint": sig.get("entrypoint"), "legacy": sig.get("legacy"), "signature_error": sig.get("error"),
            "read_only": tool.get("source") == "sdk"}


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("")
def list_custom_tools(request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "tools", "read")
    return {"tools": [_public(t) for t in tool_store.list_tools(ctx.tenant_id, ctx.project_id)]}


@router.post("", status_code=201)
def create_custom_tool(req: CustomToolCreate, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "tools", "write")
    return _public(_save(ctx, name=req.name, icon=req.icon, description=req.description, code=req.code,
                         config_keys=req.config_keys, requirements=req.requirements))


@router.put("/{tool_id}")
def update_custom_tool(tool_id: str, req: CustomToolUpdate, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "tools", "write")
    tool = _require_tool(tool_id, ctx)
    if tool["source"] == "sdk":
        raise HTTPException(status_code=409, detail="This tool is deployed from the SDK; change it in code and "
                                                    "redeploy, or fork it to edit a copy here.")
    return _public(_save(
        ctx, tool_id=tool_id,
        name=req.name if req.name is not None else tool["name"],
        icon=req.icon if req.icon is not None else tool["icon"],
        description=req.description if req.description is not None else tool["description"],
        code=req.code if req.code is not None else tool["code"],
        config_keys=req.config_keys if req.config_keys is not None else tool["config_keys"],
        requirements=req.requirements if req.requirements is not None else tool["requirements"],
    ))


@router.delete("/{tool_id}")
def delete_custom_tool(tool_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "tools", "delete")
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM custom_tools WHERE id = ? AND tenant_id = ? AND project_id = ?",
                     (tool_id, ctx.tenant_id, ctx.project_id))
        conn.execute("DELETE FROM custom_tool_versions WHERE tool_id = ? AND tenant_id = ? AND project_id = ?",
                     (tool_id, ctx.tenant_id, ctx.project_id))
        conn.commit()
    finally:
        conn.close()
    return {"success": True, "id": tool_id}


@router.post("/upload", status_code=201)
async def upload_custom_tool(
    request: Request,
    name: str = Form(...),
    icon: str = Form("🔧"),
    description: str = Form(""),
    config_keys: str = Form("[]"),   # JSON array string
    file: UploadFile = File(...),
):
    """Upload a .py file as a custom tool."""
    raw = await file.read()
    code = raw.decode("utf-8", errors="replace")
    try:
        keys = json.loads(config_keys)
    except json.JSONDecodeError:
        keys = []
    ctx = get_request_context(request)
    require_access(ctx, "tools", "write")
    return _public(_save(ctx, name=name, icon=icon, description=description, code=code, config_keys=keys))


@router.get("/{tool_id}/versions")
def list_custom_tool_versions(tool_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "tools", "read")
    tool = _require_tool(tool_id, ctx)
    return {"current": tool["version"], "versions": tool_store.list_versions(tool_id, ctx.tenant_id, ctx.project_id)}


@router.get("/{tool_id}/versions/{version}")
def get_custom_tool_version(tool_id: str, version: int, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "tools", "read")
    found = tool_store.get_version(tool_id, version, ctx.tenant_id, ctx.project_id)
    if not found:
        raise HTTPException(status_code=404, detail="Version not found")
    return _public(found)


class RollbackRequest(BaseModel):
    version: int


@router.post("/{tool_id}/rollback")
def rollback_custom_tool(tool_id: str, body: RollbackRequest, request: Request):
    """A new version with an earlier version's content."""
    ctx = get_request_context(request)
    require_access(ctx, "tools", "write")
    _require_tool(tool_id, ctx)
    try:
        return _public(tool_store.rollback(tool_id, body.version, ctx.tenant_id, ctx.project_id, ctx.user_id))
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Version {body.version} not found")


@router.post("/{tool_id}/fork", status_code=201)
def fork_custom_tool(tool_id: str, request: Request):
    """A separate tool, editable here, with this one's latest content."""
    ctx = get_request_context(request)
    require_access(ctx, "tools", "write")
    tool = _require_tool(tool_id, ctx)
    return _public(_save(ctx, name=f"{tool['name']} (fork)", icon=tool["icon"], description=tool["description"],
                         code=tool["code"], config_keys=tool["config_keys"], requirements=tool["requirements"]))


@router.post("/{tool_id}/execute")
async def execute_saved_tool(tool_id: str, req: CustomToolExecuteRequest, request: Request):
    """Execute a saved custom tool by ID: plain ``input_text``, or ``args`` for a typed tool."""
    ctx = get_request_context(request)
    require_access(ctx, "tools", "execute")
    tool = _require_tool(tool_id, ctx)
    try:
        output = await _exec_tool_code(tool["code"], req.input_text, req.config, tool["requirements"], req.args)
        return {"success": True, "output": output, "tool_id": tool_id}
    except RuntimeError as e:
        return {"success": False, "output": str(e), "tool_id": tool_id}


@router.post("/execute-code")
async def execute_adhoc_code(req: AdHocExecuteRequest, request: Request):
    """Test-run ad-hoc code before saving it as a tool."""
    ctx = get_request_context(request)
    require_access(ctx, "tools", "execute")
    try:
        output = await _exec_tool_code(req.code, req.input_text, req.config, req.requirements, req.args)
        return {"success": True, "output": output}
    except RuntimeError as e:
        return {"success": False, "output": str(e)}


class SignatureRequest(BaseModel):
    code: str


@router.post("/signature")
def read_signature(req: SignatureRequest, request: Request):
    """The entry point and parameter schema the code would have, for the editor (nothing runs)."""
    ctx = get_request_context(request)
    require_access(ctx, "tools", "read")
    try:
        return {"ok": True, **analyze(req.code).as_dict()}
    except ToolCodeError as e:
        return {"ok": False, "error": str(e)}
