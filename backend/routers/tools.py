"""
tools.py — HTTP routes for tools. The tools themselves live in backend/tools/
(one module per tool, registered automatically; see tools/__init__.py).

GET  /api/tools                 — catalog, generated from the tool specs; each package (built-in
                                  tool or MCP server) says whether this workspace installed it
GET  /api/tools/packages        — Settings → Tools & MCP packages: every package and its install state
PUT  /api/tools/packages        — install or uninstall packages ({tool_ids, installed})
DELETE /api/tools/packages      — forget the workspace's choices (back to the defaults)
POST /api/tools/reload          — pick up added / edited / deleted tool modules without a restart
                                  (server admins; tools/__init__.py reload())
GET  /api/tools/runtime-status  — sandbox isolation + Langfuse export status
POST /api/tools/execute         — run a tool once (the Tool panel's test button, etc.)
POST /api/tools/discover        — an MCP server node's tools and their input schemas
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from models import ToolRunRequest, ToolRunResponse
from services import tool_packages
from services.acl import has_access, require_access, require_server_admin
from services.auth import is_server_admin
from services.request_context import get_request_context
import tools as tool_registry

router = APIRouter(prefix="/api/tools", tags=["tools"])


async def execute_tool_real(
    tool_type: str,
    input_text: str,
    config: Optional[Dict[str, Any]] = None,
    args: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Execute a tool and return its string output.
    Called both by the /execute endpoint and the agent loop in stream.py. ``args``: a typed
    custom tool's arguments from the model's function call.
    """
    return await tool_registry.execute(tool_type, input_text, config, args)


def _tenant(request: Request) -> Optional[str]:
    try:
        return get_request_context(request).tenant_id
    except HTTPException:
        return None


@router.get("")
def get_tools_catalog(request: Request):
    tool_registry.maybe_reload()
    categories = tool_registry.catalog()
    tenant_id = _tenant(request)
    installed = tool_packages.installed_ids(tenant_id) if tenant_id else tool_packages.DEFAULTS
    for section in categories:
        if section["id"] in tool_packages.SECTIONS:
            for entry in section["tools"]:
                entry["installed"] = entry["id"] in installed
    return {"categories": categories}


def _package_ids() -> List[str]:
    return [t["id"] for s in tool_registry.catalog() if s["id"] in tool_packages.SECTIONS for t in s["tools"]]


@router.get("/packages")
def list_packages(request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "tools", "read")
    return {"can_edit": has_access(ctx, "tools", "write"), "can_reload": is_server_admin(ctx.user_id),
            "packages": tool_packages.describe(ctx.tenant_id, _package_ids())}


class PackagesUpdate(BaseModel):
    tool_ids: List[str] = Field(..., min_length=1, max_length=500)
    installed: bool


@router.put("/packages")
def update_packages(req: PackagesUpdate, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "tools", "write")
    known = set(_package_ids())
    unknown = [i for i in req.tool_ids if i not in known]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown tool or MCP server: {', '.join(unknown[:5])}")
    tool_packages.set_installed(ctx.tenant_id, ctx.user_id, dict.fromkeys(req.tool_ids), req.installed)
    return {"packages": tool_packages.describe(ctx.tenant_id, req.tool_ids)}


@router.delete("/packages")
def reset_packages(request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "tools", "write")
    tool_packages.reset(ctx.tenant_id)
    return {"ok": True}


@router.post("/reload")
def reload_tools(request: Request):
    """Re-scan backend/tools/ for added, edited and deleted tools and MCP servers. It changes code
    for every workspace on the server, so it needs a server admin."""
    require_server_admin(get_request_context(request))
    return tool_registry.reload()


@router.get("/runtime-status")
def get_runtime_status():
    """Sandbox isolation + Langfuse export status, for UI badges."""
    import os
    from services.sandbox import _container_runtime
    from services.langfuse_export import is_enabled, _redact
    return {
        "sandbox": {
            "container_runtime": _container_runtime(),
            "require_isolation": os.environ.get("SANDBOX_REQUIRE_ISOLATION", "").lower() in ("1", "true", "yes"),
        },
        "langfuse": {"enabled": is_enabled(), "redact": _redact()},
    }


@router.post("/execute", response_model=ToolRunResponse)
async def execute_tool(req: ToolRunRequest):
    """HTTP endpoint — delegates to the shared real executor."""
    try:
        output = await execute_tool_real(req.tool_type, req.input_text, req.config)
        return ToolRunResponse(success=True, output=output, tool_type=req.tool_type)
    except Exception as e:
        return ToolRunResponse(success=False, output=f"Tool Error: {e}", tool_type=req.tool_type)


class DiscoverRequest(BaseModel):
    tool_type: str = Field(..., min_length=1)
    config: Dict[str, Any] = Field(default_factory=dict)


@router.post("/discover")
async def discover_mcp_tools(req: DiscoverRequest, request: Request):
    """List an MCP server node's tools (it starts the server, so it needs mcp:execute). The node
    stores the ones to offer in ``mcp_tools``; each becomes a function the model can call."""
    require_access(get_request_context(request), "mcp", "execute")
    try:
        return {"tools": await tool_registry.discover(req.tool_type, req.config)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # the server didn't start or couldn't list its tools
        raise HTTPException(status_code=502, detail=str(e))
