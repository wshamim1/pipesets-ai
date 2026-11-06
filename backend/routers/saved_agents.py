"""
saved_agents.py — agents saved from the canvas (plan.md C11 step 2).

"Save as agent" on a child agent stores its settings plus the tool, toolkit and skill nodes wired to
it as one ``spec``; dropping the saved agent onto another canvas recreates the child and those nodes,
wired up. The canvas gets a copy: editing a saved agent changes what the next drop creates, not
pipelines that already use it (their child node records ``saved_agent_id`` / ``saved_agent_version``).

    spec = {"child":  {role, system_prompt, provider, model, kind, ...},
            "tools":  [{"type": "tool" | "toolkit", "data": {toolId, label, config, ...}}],
            "skills": [{skill_id, skill_version, label, ...}]}

Credentials never leave the canvas: string values under key / token / password-like names are
blanked on save (``stripped`` lists them), except ``secret://`` refs, which only resolve in this
workspace anyway. Saved agents are scoped to their tenant + project, like skills.

Endpoints
---------
GET    /api/saved-agents                          — the project's saved agents, newest first
POST   /api/saved-agents                          — save one (version 1)
GET    /api/saved-agents/{id}                     — one agent
PUT    /api/saved-agents/{id}                     — update it (next version)
DELETE /api/saved-agents/{id}                     — delete it and its versions
GET    /api/saved-agents/{id}/versions            — its versions, newest first
GET    /api/saved-agents/{id}/versions/{version}  — the agent as it was at that version
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_db_connection
from services.acl import require_access
from services.marketplace import _SAFE_FIELDS, _SECRET_FIELD_RE
from services.request_context import get_request_context

router = APIRouter(prefix="/api/saved-agents", tags=["saved-agents"])

MAX_SPEC_BYTES = 256 * 1024
MAX_TOOLS = 50
MAX_SKILLS = 20

CHILD_FIELDS = (
    "role", "system_prompt", "provider", "model", "api_key", "base_url", "timeout_ms", "max_retries",
    "retry_backoff_ms", "fallback_provider", "fallback_model", "fallback_api_key", "fallback_base_url",
    "kind", "skill_mode", "allowed_tool_ids", "skill_ids", "app_id", "app_name", "app_version",
    "endpoint_url", "protocol", "auth_type", "auth_header", "request_template", "response_path",
)
TOOL_FIELDS = ("toolId", "toolType", "label", "icon", "description", "config", "subTools", "toolkitId")
SKILL_FIELDS = ("skill_id", "skill_version", "label", "icon", "description", "instructions", "category",
                "tool_ids", "tags")
# Names a header or a provider, not a credential
_KEEP = _SAFE_FIELDS | {"auth_header", "auth_type"}


class AgentSpec(BaseModel):
    child: Dict[str, Any] = Field(default_factory=dict)
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    skills: List[Dict[str, Any]] = Field(default_factory=list)


class SavedAgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    icon: str = Field(default="🤖", max_length=32)
    description: str = Field(default="", max_length=2000)
    spec: AgentSpec


class SavedAgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    icon: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = Field(default=None, max_length=2000)
    spec: Optional[AgentSpec] = None


# ── Spec cleaning ─────────────────────────────────────────────────────────────

def _strip(value: Any, path: str, found: List[str]) -> Any:
    """Blank credential-like string values (keeping secret:// refs); ``found`` collects their paths."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            sub = f"{path}.{k}" if path else k
            if (isinstance(v, str) and v.strip() and k not in _KEEP and _SECRET_FIELD_RE.search(k)
                    and not v.startswith("secret://")):
                out[k] = ""
                found.append(sub)
            else:
                out[k] = _strip(v, sub, found)
        return out
    if isinstance(value, list):
        return [_strip(v, f"{path}[{i}]", found) for i, v in enumerate(value)]
    return value


def _pick(d: Any, fields: tuple) -> Dict[str, Any]:
    return {k: d[k] for k in fields if isinstance(d, dict) and k in d and d[k] is not None}


def clean_spec(spec: AgentSpec) -> tuple[Dict[str, Any], List[str]]:
    """(the spec as stored, paths of the credentials blanked). Raises 422 when it's too big."""
    if len(spec.tools) > MAX_TOOLS or len(spec.skills) > MAX_SKILLS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_TOOLS} tools and {MAX_SKILLS} skills per agent")
    tools = []
    for t in spec.tools:
        kind = t.get("type") if t.get("type") in ("tool", "toolkit") else "tool"
        data = _pick(t.get("data"), TOOL_FIELDS)
        if not data.get("toolId") and kind == "tool":
            continue
        tools.append({"type": kind, "data": data})
    raw = {"child": _pick(spec.child, CHILD_FIELDS), "tools": tools,
           "skills": [_pick(s, SKILL_FIELDS) for s in spec.skills if isinstance(s, dict)]}
    found: List[str] = []
    cleaned = _strip(raw, "", found)
    if len(json.dumps(cleaned)) > MAX_SPEC_BYTES:
        raise HTTPException(status_code=422, detail="Agent is too large to save (over 256 KB)")
    return cleaned, found


# ── Rows ──────────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["spec"] = json.loads(d.get("spec") or "{}")
    except json.JSONDecodeError:
        d["spec"] = {}
    return d


def _own_row(conn, agent_id: str, tenant_id: str, project_id: str):
    return conn.execute("SELECT * FROM saved_agents WHERE id = ? AND tenant_id = ? AND project_id = ?",
                        (agent_id, tenant_id, project_id)).fetchone()


def _snapshot(conn, agent: Dict[str, Any], author: str, now: str) -> None:
    conn.execute(
        "INSERT INTO saved_agent_versions (agent_id, version, tenant_id, project_id, snapshot, author, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (agent["id"], agent["version"], agent["tenant_id"], agent["project_id"],
         json.dumps({k: agent[k] for k in ("name", "icon", "description", "spec")}), author, now),
    )


def _get_own(conn, agent_id: str, tenant_id: str, project_id: str) -> Dict[str, Any]:
    row = _own_row(conn, agent_id, tenant_id, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Saved agent not found")
    return _row_to_dict(row)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
def list_saved_agents(request: Request) -> List[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "agents", "read")
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM saved_agents WHERE tenant_id = ? AND project_id = ? "
                            "ORDER BY updated_at DESC", (ctx.tenant_id, ctx.project_id)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


@router.post("")
def create_saved_agent(req: SavedAgentCreate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "agents", "create")
    spec, stripped = clean_spec(req.spec)
    agent_id = f"agent_{uuid.uuid4().hex[:10]}"
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO saved_agents (id, tenant_id, project_id, owner_user_id, name, icon, description, spec, "
            "version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (agent_id, ctx.tenant_id, ctx.project_id, ctx.user_id, req.name.strip(), req.icon.strip() or "🤖",
             req.description.strip(), json.dumps(spec), now, now),
        )
        agent = _get_own(conn, agent_id, ctx.tenant_id, ctx.project_id)
        _snapshot(conn, agent, ctx.user_id, now)
        conn.commit()
        return {**agent, "stripped": stripped}
    finally:
        conn.close()


@router.get("/{agent_id}")
def get_saved_agent(agent_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "agents", "read")
    conn = get_db_connection()
    try:
        return _get_own(conn, agent_id, ctx.tenant_id, ctx.project_id)
    finally:
        conn.close()


@router.put("/{agent_id}")
def update_saved_agent(agent_id: str, req: SavedAgentUpdate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "agents", "update")
    conn = get_db_connection()
    try:
        current = _get_own(conn, agent_id, ctx.tenant_id, ctx.project_id)
        spec, stripped = clean_spec(req.spec) if req.spec is not None else (current["spec"], [])
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE saved_agents SET name = ?, icon = ?, description = ?, spec = ?, version = version + 1, "
            "updated_at = ? WHERE id = ? AND tenant_id = ? AND project_id = ?",
            ((req.name or current["name"]).strip(), (req.icon or current["icon"]).strip() or "🤖",
             (current["description"] if req.description is None else req.description).strip(),
             json.dumps(spec), now, agent_id, ctx.tenant_id, ctx.project_id),
        )
        agent = _get_own(conn, agent_id, ctx.tenant_id, ctx.project_id)
        _snapshot(conn, agent, ctx.user_id, now)
        conn.commit()
        return {**agent, "stripped": stripped}
    finally:
        conn.close()


@router.delete("/{agent_id}")
def delete_saved_agent(agent_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "agents", "delete")
    conn = get_db_connection()
    try:
        _get_own(conn, agent_id, ctx.tenant_id, ctx.project_id)
        conn.execute("DELETE FROM saved_agents WHERE id = ? AND tenant_id = ? AND project_id = ?",
                     (agent_id, ctx.tenant_id, ctx.project_id))
        conn.execute("DELETE FROM saved_agent_versions WHERE agent_id = ? AND tenant_id = ? AND project_id = ?",
                     (agent_id, ctx.tenant_id, ctx.project_id))
        conn.commit()
        return {"success": True, "deleted_id": agent_id}
    finally:
        conn.close()


@router.get("/{agent_id}/versions")
def list_versions(agent_id: str, request: Request) -> List[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "agents", "read")
    conn = get_db_connection()
    try:
        _get_own(conn, agent_id, ctx.tenant_id, ctx.project_id)
        rows = conn.execute("SELECT version, author, created_at FROM saved_agent_versions WHERE agent_id = ? "
                            "AND tenant_id = ? AND project_id = ? ORDER BY version DESC",
                            (agent_id, ctx.tenant_id, ctx.project_id)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{agent_id}/versions/{version}")
def get_version(agent_id: str, version: int, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "agents", "read")
    conn = get_db_connection()
    try:
        current = _get_own(conn, agent_id, ctx.tenant_id, ctx.project_id)
        row = conn.execute("SELECT snapshot FROM saved_agent_versions WHERE agent_id = ? AND version = ? "
                           "AND tenant_id = ? AND project_id = ?",
                           (agent_id, version, ctx.tenant_id, ctx.project_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Saved agent version not found")
        return {**current, **json.loads(row["snapshot"]), "version": version}
    finally:
        conn.close()
