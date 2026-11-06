"""
admin.py — Settings → Admin console: the whole server, across every workspace. Server admins only
(services/auth.is_server_admin); a workspace owner alone isn't one.

Reads cover every user, workspace and pipeline. Other workspaces' pipelines are view-only here:
to edit one, an admin joins that workspace (POST .../join), which is audited like every write below.

GET    /api/admin/overview                     — counts for the whole server
GET    /api/admin/users                        — every account, with its workspaces and last activity
PATCH  /api/admin/users/{user_id}              — rename, enable / disable, grant / revoke server admin
POST   /api/admin/users/{user_id}/password     — set a new password (signs the user out everywhere)
POST   /api/admin/users/{user_id}/sign-out     — revoke every session
DELETE /api/admin/users/{user_id}              — delete an account
GET    /api/admin/workspaces                   — every workspace, with owners and usage
POST   /api/admin/workspaces/{tenant_id}/join  — add the caller as an owner
DELETE /api/admin/workspaces/{tenant_id}       — delete a workspace and everything in it
GET    /api/admin/apps                         — every pipeline
GET    /api/admin/apps/{app_id}                — one pipeline's flow, read-only
GET    /api/admin/audit                        — the audit log of every workspace
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from db import get_db_connection, insert_ignore
from routers.iam import _purge_scope
from services import auth
from services.acl import require_server_admin
from services.request_context import RequestContext, get_request_context

router = APIRouter(prefix="/api/admin", tags=["admin"])

USER_STATUSES = ("active", "disabled")


def _admin(request: Request) -> RequestContext:
    ctx = get_request_context(request)
    require_server_admin(ctx)
    return ctx


def _now() -> str:
    return datetime.utcnow().isoformat()


def _usable_admins_besides(conn, user_id: str) -> int:
    """Active server admins other than ``user_id`` who can sign in (flag or PIPESETS_SERVER_ADMINS)."""
    env = auth._env_server_admins()
    rows = conn.execute("SELECT email, server_admin FROM users WHERE id != ? AND status = 'active' "
                        "AND password_hash IS NOT NULL", (user_id,)).fetchall()
    return sum(1 for r in rows if r["server_admin"] or auth.normalize_email(r["email"] or "") in env)


def _sole_owned(conn, user_id: str) -> List[str]:
    """Names of the workspaces ``user_id`` is the only owner of."""
    rows = conn.execute(
        "SELECT t.name FROM tenants t JOIN tenant_memberships m ON m.tenant_id = t.id "
        "WHERE m.user_id = ? AND m.role = 'owner' AND "
        "(SELECT COUNT(*) FROM tenant_memberships o WHERE o.tenant_id = t.id AND o.role = 'owner') = 1",
        (user_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def _revoke_sessions(conn, user_id: str) -> int:
    return conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                        (_now(), user_id)).rowcount


# ── Overview ──────────────────────────────────────────────────────────────────

@router.get("/overview")
def overview(request: Request) -> Dict[str, Any]:
    _admin(request)
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    conn = get_db_connection()
    try:
        one = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]   # noqa: E731
        return {
            "users": one("SELECT COUNT(*) FROM users"),
            "users_disabled": one("SELECT COUNT(*) FROM users WHERE status != 'active'"),
            "server_admins": len(auth.list_server_admins()),
            "active_sessions": one("SELECT COUNT(DISTINCT user_id) FROM auth_sessions WHERE revoked_at IS NULL "
                                   "AND expires_at > ?", (_now(),)),
            "workspaces": one("SELECT COUNT(*) FROM tenants"),
            "projects": one("SELECT COUNT(*) FROM projects"),
            "pipelines": one("SELECT COUNT(*) FROM apps"),
            "pipelines_published": one("SELECT COUNT(*) FROM apps WHERE status = 'published'"),
            "runs_7d": one("SELECT COUNT(DISTINCT run_id) FROM traces WHERE created_at >= ?", (week_ago,)),
            "cost_7d": round(float(one("SELECT COALESCE(SUM(cost_usd), 0) FROM traces WHERE created_at >= ?",
                                       (week_ago,))), 4),
        }
    finally:
        conn.close()


# ── Users ─────────────────────────────────────────────────────────────────────

class AdminUserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=200)
    status: Optional[str] = None
    server_admin: Optional[bool] = None


class AdminPassword(BaseModel):
    password: str


def _user_rows(conn, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    env = auth._env_server_admins()
    where, args = ("WHERE u.id = ?", (user_id,)) if user_id else ("", ())
    users = conn.execute(
        "SELECT u.id, u.email, u.display_name, u.status, u.server_admin, u.created_at, "
        "u.password_hash IS NOT NULL AS has_password, "
        "(SELECT MAX(s.last_seen_at) FROM auth_sessions s WHERE s.user_id = u.id) AS last_seen_at, "
        "(SELECT COUNT(*) FROM auth_sessions s WHERE s.user_id = u.id AND s.revoked_at IS NULL "
        " AND s.expires_at > ?) AS active_sessions, "
        "(SELECT COUNT(*) FROM apps a WHERE a.owner_user_id = u.id) AS pipelines "
        f"FROM users u {where} ORDER BY u.created_at ASC", (_now(), *args),
    ).fetchall()
    memberships: Dict[str, List[Dict[str, str]]] = {}
    for m in conn.execute("SELECT m.user_id, m.role, t.id, t.name FROM tenant_memberships m "
                          "JOIN tenants t ON t.id = m.tenant_id ORDER BY t.name").fetchall():
        memberships.setdefault(m["user_id"], []).append({"id": m["id"], "name": m["name"], "role": m["role"]})
    return [{
        **{k: u[k] for k in ("id", "email", "display_name", "status", "created_at", "last_seen_at",
                             "active_sessions", "pipelines")},
        "has_password": bool(u["has_password"]),
        "server_admin": bool(u["server_admin"]) or auth.normalize_email(u["email"] or "") in env,
        "server_admin_source": "flag" if u["server_admin"] else
                               ("PIPESETS_SERVER_ADMINS" if auth.normalize_email(u["email"] or "") in env else None),
        "workspaces": memberships.get(u["id"], []),
    } for u in users]


def _require_user(conn, user_id: str):
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.get("/users")
def list_users(request: Request, q: str = "") -> Dict[str, Any]:
    _admin(request)
    conn = get_db_connection()
    try:
        users = _user_rows(conn)
    finally:
        conn.close()
    needle = q.strip().lower()
    if needle:
        users = [u for u in users if needle in f"{u['email']} {u['display_name']}".lower()]
    return {"users": users}


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: AdminUserUpdate, request: Request) -> Dict[str, Any]:
    ctx = _admin(request)
    if body.status is not None and body.status not in USER_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(USER_STATUSES)}")
    conn = get_db_connection()
    try:
        row = _require_user(conn, user_id)
        losing_admin = (body.status == "disabled" and row["status"] == "active") or body.server_admin is False
        if user_id == ctx.user_id and losing_admin:
            raise HTTPException(status_code=400, detail="You can't disable yourself or revoke your own admin role.")
        if losing_admin and auth.is_server_admin(user_id) and not _usable_admins_besides(conn, user_id):
            raise HTTPException(status_code=400, detail="This is the last server admin who can sign in. "
                                                        "Make someone else an admin first.")
        if body.server_admin is False and not row["server_admin"]:
            raise HTTPException(status_code=400, detail="This admin comes from PIPESETS_SERVER_ADMINS; "
                                                        "remove the email there to revoke it.")
        sets: Dict[str, Any] = {}
        if body.display_name is not None:
            if not body.display_name.strip():
                raise HTTPException(status_code=400, detail="Name cannot be empty")
            sets["display_name"] = body.display_name.strip()
        if body.status is not None:
            sets["status"] = body.status
        if body.server_admin is not None:
            sets["server_admin"] = 1 if body.server_admin else 0
        if sets:
            sets["updated_at"] = _now()
            conn.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                         (*sets.values(), user_id))
            if sets.get("status") == "disabled":
                _revoke_sessions(conn, user_id)
            conn.commit()
        return _user_rows(conn, user_id)[0]
    finally:
        conn.close()


@router.post("/users/{user_id}/password")
def set_password(user_id: str, body: AdminPassword, request: Request) -> Dict[str, Any]:
    _admin(request)
    auth.validate_password(body.password)
    conn = get_db_connection()
    try:
        _require_user(conn, user_id)
        active = conn.execute("SELECT COUNT(*) FROM auth_sessions WHERE user_id = ? AND revoked_at IS NULL",
                              (user_id,)).fetchone()[0]
    finally:
        conn.close()
    auth.set_password(user_id, body.password)   # also ends every session
    return {"id": user_id, "sessions_revoked": active}


@router.post("/users/{user_id}/sign-out")
def sign_out(user_id: str, request: Request) -> Dict[str, Any]:
    _admin(request)
    conn = get_db_connection()
    try:
        _require_user(conn, user_id)
        revoked = _revoke_sessions(conn, user_id)
        conn.commit()
    finally:
        conn.close()
    return {"id": user_id, "sessions_revoked": revoked}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, request: Request) -> Dict[str, Any]:
    ctx = _admin(request)
    if user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="You can't delete your own account here.")
    conn = get_db_connection()
    try:
        _require_user(conn, user_id)
        if auth.is_server_admin(user_id) and not _usable_admins_besides(conn, user_id):
            raise HTTPException(status_code=400, detail="This is the last server admin who can sign in.")
        sole = _sole_owned(conn, user_id)
        if sole:
            raise HTTPException(status_code=409, detail=(
                f"They are the only owner of {', '.join(sole)}. Delete that workspace, or add another owner, first."))
        # projects.created_by is RESTRICT: the acting admin takes over the record of who created them
        conn.execute("UPDATE projects SET created_by = ? WHERE created_by = ?", (ctx.user_id, user_id))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))   # cascades memberships and sessions
        conn.commit()
    finally:
        conn.close()
    return {"deleted": True, "id": user_id}


# ── Workspaces ────────────────────────────────────────────────────────────────

@router.get("/workspaces")
def list_workspaces(request: Request) -> Dict[str, Any]:
    ctx = _admin(request)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT t.id, t.name, t.slug, t.status, t.created_at, "
            "(SELECT COUNT(*) FROM tenant_memberships m WHERE m.tenant_id = t.id) AS members, "
            "(SELECT COUNT(*) FROM projects p WHERE p.tenant_id = t.id) AS projects, "
            "(SELECT COUNT(*) FROM apps a WHERE a.tenant_id = t.id) AS pipelines, "
            "(SELECT MAX(a.updated_at) FROM apps a WHERE a.tenant_id = t.id) AS last_activity "
            "FROM tenants t ORDER BY t.created_at ASC"
        ).fetchall()
        owners: Dict[str, List[str]] = {}
        for o in conn.execute("SELECT m.tenant_id, u.email FROM tenant_memberships m JOIN users u ON u.id = m.user_id "
                              "WHERE m.role = 'owner' ORDER BY u.email").fetchall():
            owners.setdefault(o["tenant_id"], []).append(o["email"])
        mine = {r["tenant_id"] for r in conn.execute("SELECT tenant_id FROM tenant_memberships WHERE user_id = ?",
                                                     (ctx.user_id,)).fetchall()}
    finally:
        conn.close()
    return {"workspaces": [{**dict(r), "owners": owners.get(r["id"], []), "is_member": r["id"] in mine} for r in rows]}


@router.post("/workspaces/{tenant_id}/join")
def join_workspace(tenant_id: str, request: Request) -> Dict[str, Any]:
    """Add the calling admin as an owner, so they can open and edit its pipelines like a member."""
    ctx = _admin(request)
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM tenants WHERE id = ?", (tenant_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Workspace not found")
        current = conn.execute("SELECT role FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?",
                               (tenant_id, ctx.user_id)).fetchone()
        if current:
            conn.execute("UPDATE tenant_memberships SET role = 'owner' WHERE tenant_id = ? AND user_id = ?",
                         (tenant_id, ctx.user_id))
        else:
            insert_ignore(conn, "tenant_memberships", {"tenant_id": tenant_id, "user_id": ctx.user_id,
                                                       "role": "owner", "created_at": _now()},
                          key=("tenant_id", "user_id"))
        conn.commit()
    finally:
        conn.close()
    return {"tenant_id": tenant_id, "role": "owner"}


@router.delete("/workspaces/{tenant_id}")
def delete_workspace(tenant_id: str, request: Request) -> Dict[str, Any]:
    ctx = _admin(request)
    if tenant_id == ctx.tenant_id:
        raise HTTPException(status_code=400, detail="Switch to another workspace before deleting this one.")
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM tenants WHERE id = ?", (tenant_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Workspace not found")
        if conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0] <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last workspace")
        removed = _purge_scope(conn, tenant_id)
        conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))   # cascades memberships, groups, projects, ACLs
        conn.commit()
    finally:
        conn.close()
    return {"deleted": True, "id": tenant_id, "removed": removed}


# ── Pipelines ─────────────────────────────────────────────────────────────────

def _node_count(flow_data: Optional[str]) -> int:
    try:
        return len((json.loads(flow_data or "{}") or {}).get("nodes") or [])
    except (ValueError, AttributeError):
        return 0


@router.get("/apps")
def list_apps(request: Request, q: str = "", tenant_id: Optional[str] = None) -> Dict[str, Any]:
    _admin(request)
    month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
    sql = ("SELECT a.id, a.name, a.description, a.status, a.version, a.created_at, a.updated_at, a.flow_data, "
           "a.tenant_id, t.name AS workspace, p.name AS project, u.email AS owner, "
           "(SELECT COUNT(DISTINCT r.run_id) FROM traces r WHERE r.app_id = a.id AND r.created_at >= ?) AS runs_30d "
           "FROM apps a LEFT JOIN tenants t ON t.id = a.tenant_id LEFT JOIN projects p ON p.id = a.project_id "
           "LEFT JOIN users u ON u.id = a.owner_user_id")
    args: List[Any] = [month_ago]
    if tenant_id:
        sql += " WHERE a.tenant_id = ?"
        args.append(tenant_id)
    conn = get_db_connection()
    try:
        rows = conn.execute(sql + " ORDER BY a.updated_at DESC", tuple(args)).fetchall()
    finally:
        conn.close()
    apps = [{**{k: r[k] for k in r.keys() if k != "flow_data"}, "nodes": _node_count(r["flow_data"])} for r in rows]
    needle = q.strip().lower()
    if needle:
        apps = [a for a in apps if needle in f"{a['name']} {a['workspace'] or ''} {a['owner'] or ''}".lower()]
    return {"apps": apps}


@router.get("/apps/{app_id}")
def get_app(app_id: str, request: Request) -> Dict[str, Any]:
    _admin(request)
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT a.id, a.name, a.status, a.version, a.flow_data, a.tenant_id, t.name AS workspace "
                           "FROM apps a LEFT JOIN tenants t ON t.id = a.tenant_id WHERE a.id = ?", (app_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    try:
        flow = json.loads(row["flow_data"] or "{}") or {}
    except ValueError:
        flow = {}
    return {**{k: row[k] for k in row.keys() if k != "flow_data"},
            "flow_data": {"nodes": flow.get("nodes") or [], "edges": flow.get("edges") or []}}


# ── Audit ─────────────────────────────────────────────────────────────────────

@router.get("/audit")
def audit(request: Request, limit: int = Query(default=100, ge=1, le=500), action: str = "",
          before: Optional[str] = None) -> Dict[str, Any]:
    _admin(request)
    sql = ("SELECT l.*, t.name AS workspace, u.email AS actor_email FROM audit_log l "
           "LEFT JOIN tenants t ON t.id = l.tenant_id LEFT JOIN users u ON u.id = l.actor WHERE 1=1")
    args: List[Any] = []
    if action:
        sql += " AND l.action LIKE ?"
        args.append(action.replace("%", "") + "%")
    if before:
        sql += " AND l.created_at < ?"
        args.append(before)
    conn = get_db_connection()
    try:
        rows = conn.execute(sql + " ORDER BY l.created_at DESC LIMIT ?", tuple(args + [limit])).fetchall()
    finally:
        conn.close()
    return {"entries": [dict(r) for r in rows]}
