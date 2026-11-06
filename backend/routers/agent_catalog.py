"""
agent_catalog.py — built-in agents (backend/agents/) and Settings → Agents (plan.md C11 step 3).

Endpoints
---------
GET    /api/agent-catalog           — every built-in agent with this workspace's install state and
                                      readiness (the tools it needs that aren't installed)
PUT    /api/agent-catalog/packages  — install / uninstall agents; ``with_tools`` also installs the
                                      tools they're missing (needs write access to tools)
DELETE /api/agent-catalog/packages  — forget every choice: back to the defaults plus what pipelines use
POST   /api/agent-catalog/{id}/eval-dataset — copy an agent's eval set into a new eval dataset (linked to
                                      the pipeline it's in), to run with the llm_judge scorer
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import agents
import tools as tool_registry
from services import agent_packages, tool_packages
from services.acl import has_access, require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/agent-catalog", tags=["agent-catalog"])


def _tenant(request: Request) -> Optional[str]:
    try:
        return get_request_context(request).tenant_id
    except HTTPException:
        return None


def _entries(tenant_id: Optional[str], ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    installed_tools = tool_packages.installed_ids(tenant_id) if tenant_id else tool_packages.DEFAULTS
    specs = [s for s in agents.all_specs() if ids is None or s.id in ids]
    states = {p["id"]: p for p in agent_packages.STORE.describe(tenant_id, [s.id for s in specs])} if tenant_id else {}
    out = []
    for s in specs:
        entry = s.catalog_entry(installed_tools)
        for need in entry["tools"]:   # catalog names for the UI ("Tavily Search", not tavily_search)
            need["names"] = {i: getattr(tool_registry.get_spec(i), "name", i) for i in need["ids"]}
        state = states.get(s.id) or {"installed": s.default_installed, "source": "default" if s.default_installed else None,
                                     "in_use": False}
        entry.update(installed=state["installed"], source=state["source"], in_use=state["in_use"])
        out.append(entry)
    return out


@router.get("")
def get_agent_catalog(request: Request) -> Dict[str, Any]:
    """Served like the tools catalog (no access check): the sidebar reads it for anyone who can build."""
    tenant_id = _tenant(request)
    ctx = get_request_context(request) if tenant_id else None
    return {
        "groups": agents.GROUPS,
        "can_edit": bool(ctx and has_access(ctx, "agents", "write")),
        "can_install_tools": bool(ctx and has_access(ctx, "tools", "write")),
        "agents": _entries(tenant_id),
    }


class AgentPackagesUpdate(BaseModel):
    agent_ids: List[str] = Field(..., min_length=1, max_length=200)
    installed: bool
    with_tools: bool = False   # installing: also install the tools each agent still needs


@router.put("/packages")
def update_agent_packages(req: AgentPackagesUpdate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "agents", "write")
    ids = list(dict.fromkeys(req.agent_ids))
    unknown = [i for i in ids if agents.get(i) is None]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown built-in agent: {', '.join(unknown[:5])}")

    tools_installed: List[str] = []
    if req.installed and req.with_tools:
        missing = list(dict.fromkeys(t for e in _entries(ctx.tenant_id, ids) for t in e["missing_tools"]))
        if missing:
            require_access(ctx, "tools", "write")
            tool_packages.set_installed(ctx.tenant_id, ctx.user_id, missing, True)
            tools_installed = missing
    agent_packages.STORE.set_installed(ctx.tenant_id, ctx.user_id, ids, req.installed)
    return {"agents": _entries(ctx.tenant_id, ids), "tools_installed": tools_installed}


@router.delete("/packages")
def reset_agent_packages(request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "agents", "write")
    agent_packages.STORE.reset(ctx.tenant_id)
    return {"ok": True}


class EvalDatasetRequest(BaseModel):
    app_id: Optional[str] = None      # the pipeline the agent was dropped into
    app_version: int = Field(default=0, ge=0)


@router.post("/{agent_id}/eval-dataset")
def create_eval_dataset(agent_id: str, req: EvalDatasetRequest, request: Request) -> Dict[str, Any]:
    from routers.eval import DatasetCreate, _insert_cases, new_dataset   # lazy: eval imports the runners

    ctx = get_request_context(request)
    require_access(ctx, "agents", "read")
    spec = agents.get(agent_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown built-in agent: {agent_id}")
    if not spec.evals:
        raise HTTPException(status_code=400, detail=f"{spec.name} has no eval set")
    scope = (ctx.tenant_id, ctx.project_id)
    ds = new_dataset(DatasetCreate(
        name=f"{spec.name} — built-in eval", app_id=req.app_id, app_version=req.app_version,
        description=f"The {spec.name} agent's eval set. Run it with the LLM judge scorer: each expected "
                    "output says what a good answer does."), scope)
    added = _insert_cases(ds["id"], [{"prompt": c.prompt, "expected_output": c.expected, "tags": list(c.tags),
                                      "source": "builtin"} for c in spec.evals], scope=scope)
    return {"dataset_id": ds["id"], "name": ds["name"], "cases_created": added["cases_created"], "scorer": "llm_judge"}
