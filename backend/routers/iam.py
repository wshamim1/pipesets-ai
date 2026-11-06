import uuid
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from db import get_db_connection, get_engine, insert_ignore
from services import auth
from services.acl import has_access, require_access
from services.request_context import get_current_user, get_request_context
from services.request_context import RequestContext

router = APIRouter(prefix="/api/iam", tags=["iam"])


TENANT_ROLES = ("owner", "editor", "viewer")


class UserCreateRequest(BaseModel):
    email: str
    display_name: str
    status: str = "active"
    role: str = "viewer"
    # Initial password for a brand-new account; ignored when the email already exists
    password: Optional[str] = None


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    status: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None


class GroupCreateRequest(BaseModel):
    name: str
    description: str = ""


class GroupUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class GroupMemberRequest(BaseModel):
    user_id: str


class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class AclCreateRequest(BaseModel):
    project_id: Optional[str] = None
    principal_type: str
    principal_id: str
    resource: str
    action: str
    effect: str = "allow"


class AclUpdateRequest(BaseModel):
    project_id: Optional[str] = None
    principal_type: Optional[str] = None
    principal_id: Optional[str] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    effect: Optional[str] = None


PRINCIPAL_TYPES = ("user", "group")
EFFECTS = ("allow", "deny")


def _validate_acl(conn, tenant_id: str, project_id: Optional[str], principal_type: str,
                  principal_id: str, effect: str) -> None:
    """An ACL may only reference principals and projects inside its own tenant."""
    error = None
    if principal_type not in PRINCIPAL_TYPES:
        error = (400, f"principal_type must be one of: {', '.join(PRINCIPAL_TYPES)}")
    elif effect not in EFFECTS:
        error = (400, f"effect must be one of: {', '.join(EFFECTS)}")
    elif principal_type == "user" and not _tenant_role(conn, tenant_id, principal_id):
        error = (404, f"User '{principal_id}' is not in this tenant")
    elif principal_type == "group" and not conn.execute(
        "SELECT 1 FROM groups WHERE id = ? AND tenant_id = ?", (principal_id, tenant_id)
    ).fetchone():
        error = (404, f"Group '{principal_id}' is not in this tenant")
    elif project_id and not conn.execute(
        "SELECT 1 FROM projects WHERE id = ? AND tenant_id = ?", (project_id, tenant_id)
    ).fetchone():
        error = (404, f"Project '{project_id}' is not in this tenant")
    if error:
        conn.close()
        raise HTTPException(status_code=error[0], detail=error[1])


class AccessCheckRequest(BaseModel):
    user_id: str
    project_id: str
    resource: str
    action: str
    tenant_id: Optional[str] = None


class TenantCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    status: str = "active"


class TenantUpdateRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    status: Optional[str] = None


def _row_to_dict(row) -> Dict[str, Any]:
    return dict(row)


def _slugify(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())
    return normalized.strip("-")


def _require_admin(ctx: RequestContext) -> None:
    """IAM changes need the iam:admin ACL; tenant owners have it implicitly."""
    require_access(ctx, "iam", "admin")


def _tenant_role(conn, tenant_id: str, user_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT role FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?", (tenant_id, user_id)
    ).fetchone()
    return row[0] if row else None


# Kept when a workspace or project is deleted: audit entries leave only by retention (services/audit.py)
KEEP_ON_DELETE = {"audit_log"}


def _scoped_tables(column: str) -> List[str]:
    """Tables holding a ``column`` (tenant_id / project_id) that no foreign key cascades — apps,
    secrets, API keys, schedules, webhooks, … Found from the schema, so a new table can't be missed."""
    from sqlalchemy import inspect

    insp = inspect(get_engine())
    out = []
    for table in insp.get_table_names():
        if table in KEEP_ON_DELETE:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        cascaded = {c for fk in insp.get_foreign_keys(table) for c in fk["constrained_columns"]}
        if "tenant_id" in cols and column in cols and column not in cascaded:
            out.append(table)
    return sorted(out)


def _purge_scope(conn, tenant_id: str, project_id: Optional[str] = None) -> Dict[str, int]:
    """Delete a workspace's (or one project's) rows from the tables no foreign key covers; the
    database cascades the rest (memberships, groups, projects, ACLs) when the parent goes."""
    removed = {}
    for table in _scoped_tables("project_id" if project_id else "tenant_id"):
        where, args = ("tenant_id = ? AND project_id = ?", (tenant_id, project_id)) if project_id \
            else ("tenant_id = ?", (tenant_id,))
        n = conn.execute(f"DELETE FROM {table} WHERE {where}", args).rowcount
        if n:
            removed[table] = n
    return removed


def _require_tenant_owner(conn, tenant_id: str, user_id: str) -> None:
    if _tenant_role(conn, tenant_id, user_id) != "owner":
        conn.close()
        raise HTTPException(status_code=403, detail="Only a tenant owner can do this.")


@router.get("/context")
def get_context(request: Request):
    ctx = get_request_context(request)
    return {
        "tenant_id": ctx.tenant_id,
        "project_id": ctx.project_id,
        "user_id": ctx.user_id,
        "can_admin": has_access(ctx, "iam", "admin"),
        "server_admin": auth.is_server_admin(ctx.user_id),
    }


@router.get("/tenants")
def list_tenants(request: Request):
    """Tenants the caller belongs to."""
    user_id = get_current_user(request)
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT t.id, t.name, t.slug, t.status, tm.role
        FROM tenants t JOIN tenant_memberships tm ON tm.tenant_id = t.id
        WHERE tm.user_id = ?
        ORDER BY t.name ASC
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return {"tenants": [_row_to_dict(r) for r in rows]}


@router.post("/tenants")
def create_tenant(req: TenantCreateRequest, request: Request):
    user_id = get_current_user(request)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tenant name is required")

    slug = (req.slug or _slugify(name) or f"tenant-{uuid.uuid4().hex[:6]}").strip().lower()
    now = datetime.utcnow().isoformat()
    tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"

    conn = get_db_connection()
    slug_exists = conn.execute("SELECT 1 FROM tenants WHERE slug = ?", (slug,)).fetchone()
    if slug_exists:
        conn.close()
        raise HTTPException(status_code=409, detail="Tenant slug already exists")

    conn.execute(
        "INSERT INTO tenants (id, name, slug, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (tenant_id, name, slug, req.status, now, now),
    )
    insert_ignore(conn, "tenant_memberships",
                  {"tenant_id": tenant_id, "user_id": user_id, "role": "owner", "created_at": now},
                  key=("tenant_id", "user_id"))
    conn.commit()
    row = conn.execute("SELECT id, name, slug, status FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


@router.put("/tenants/{tenant_id}")
def update_tenant(tenant_id: str, req: TenantUpdateRequest, request: Request):
    user_id = get_current_user(request)
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Tenant not found")
    _require_tenant_owner(conn, tenant_id, user_id)

    now = datetime.utcnow().isoformat()
    name = req.name.strip() if req.name is not None else row["name"]
    status = req.status if req.status is not None else row["status"]
    slug = req.slug.strip().lower() if req.slug is not None else row["slug"]
    if req.slug is None and req.name is not None:
        slug = _slugify(name) or row["slug"]

    duplicate = conn.execute(
        "SELECT 1 FROM tenants WHERE slug = ? AND id != ?",
        (slug, tenant_id),
    ).fetchone()
    if duplicate:
        conn.close()
        raise HTTPException(status_code=409, detail="Tenant slug already exists")

    conn.execute(
        "UPDATE tenants SET name = ?, slug = ?, status = ?, updated_at = ? WHERE id = ?",
        (name, slug, status, now, tenant_id),
    )
    conn.commit()
    updated = conn.execute("SELECT id, name, slug, status FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    conn.close()
    return _row_to_dict(updated)


@router.delete("/tenants/{tenant_id}")
def delete_tenant(tenant_id: str, request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    tenant = conn.execute("SELECT 1 FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if not tenant:
        conn.close()
        raise HTTPException(status_code=404, detail="Tenant not found")
    _require_tenant_owner(conn, tenant_id, ctx.user_id)

    count_row = conn.execute("SELECT COUNT(1) FROM tenants").fetchone()
    tenant_count = int(count_row[0]) if count_row else 0
    if tenant_count <= 1:
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot delete the last tenant")

    if tenant_id == ctx.tenant_id:
        conn.close()
        raise HTTPException(status_code=400, detail="Switch to another tenant before deleting the current tenant")

    removed = _purge_scope(conn, tenant_id)
    conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))   # cascades memberships, groups, projects, ACLs
    conn.commit()
    conn.close()
    return {"deleted": True, "id": tenant_id, "removed": removed}


@router.get("/users")
def list_users(request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT u.id, u.email, u.display_name, u.status, u.created_at, u.updated_at,
               u.password_hash IS NOT NULL AS has_password, tm.role AS tenant_role
        FROM users u
        JOIN tenant_memberships tm
          ON tm.user_id = u.id
        WHERE tm.tenant_id = ?
        ORDER BY u.display_name ASC
        """,
        (ctx.tenant_id,),
    ).fetchall()
    conn.close()
    return {"users": [_row_to_dict(r) for r in rows]}


@router.post("/users")
def create_user(req: UserCreateRequest, request: Request):
    """Add a user to the current tenant. An email that already has an account (e.g. from
    sign-up) is linked as-is; otherwise a new account is created, optionally with a
    password so the person can sign in straight away."""
    ctx = get_request_context(request)
    _require_admin(ctx)
    if req.role not in TENANT_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(TENANT_ROLES)}")
    email = auth.normalize_email(req.email)
    conn = get_db_connection()
    if req.role == "owner":
        _require_tenant_owner(conn, ctx.tenant_id, ctx.user_id)
    now = datetime.utcnow().isoformat()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        user_id = existing["id"]
    else:
        if req.password:
            auth.validate_password(req.password)
        user_id = f"user_{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO users (id, email, display_name, status, password_hash, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, email, req.display_name.strip(), req.status,
             auth.hash_password(req.password) if req.password else None, now, now),
        )
    insert_ignore(conn, "tenant_memberships",
                  {"tenant_id": ctx.tenant_id, "user_id": user_id, "role": req.role, "created_at": now},
                  key=("tenant_id", "user_id"))
    conn.commit()
    row = conn.execute(
        "SELECT u.id, u.email, u.display_name, u.status, u.password_hash IS NOT NULL AS has_password, "
        "tm.role AS tenant_role FROM users u JOIN tenant_memberships tm ON tm.user_id = u.id "
        "WHERE u.id = ? AND tm.tenant_id = ?",
        (user_id, ctx.tenant_id),
    ).fetchone()
    conn.close()
    return {**_row_to_dict(row), "existing_account": bool(existing)}


@router.put("/users/{user_id}")
def update_user(user_id: str, req: UserUpdateRequest, request: Request):
    ctx = get_request_context(request)
    # Anyone may rename themselves; everything else is an admin action
    if user_id != ctx.user_id or req.status is not None or req.role is not None or req.password is not None:
        _require_admin(ctx)
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    role = _tenant_role(conn, ctx.tenant_id, user_id)
    if not row or not role:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found in tenant")

    if req.role is not None and req.role != role:
        if req.role not in TENANT_ROLES:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(TENANT_ROLES)}")
        if "owner" in (role, req.role):
            _require_tenant_owner(conn, ctx.tenant_id, ctx.user_id)
        if role == "owner":
            owners = conn.execute(
                "SELECT COUNT(1) FROM tenant_memberships WHERE tenant_id = ? AND role = 'owner'", (ctx.tenant_id,)
            ).fetchone()[0]
            if owners <= 1:
                conn.close()
                raise HTTPException(status_code=400, detail="A tenant needs at least one owner")
        conn.execute("UPDATE tenant_memberships SET role = ? WHERE tenant_id = ? AND user_id = ?",
                     (req.role, ctx.tenant_id, user_id))

    if req.password is not None:
        # A tenant admin may only set passwords on accounts that are theirs to manage:
        # not yet activated, or belonging to no other tenant.
        other_tenants = conn.execute(
            "SELECT COUNT(1) FROM tenant_memberships WHERE user_id = ? AND tenant_id != ?", (user_id, ctx.tenant_id)
        ).fetchone()[0]
        if row["password_hash"] and other_tenants:
            conn.close()
            raise HTTPException(status_code=403, detail="This user also belongs to other tenants; they must change their own password.")

    now = datetime.utcnow().isoformat()
    display_name = req.display_name.strip() if req.display_name is not None else row["display_name"]
    status = req.status if req.status is not None else row["status"]
    conn.execute(
        "UPDATE users SET display_name = ?, status = ?, updated_at = ? WHERE id = ?",
        (display_name, status, now, user_id),
    )
    if status != "active":
        conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now, user_id))
    conn.commit()
    conn.close()
    if req.password is not None:
        auth.set_password(user_id, req.password)

    conn = get_db_connection()
    updated = conn.execute(
        "SELECT u.id, u.email, u.display_name, u.status, u.password_hash IS NOT NULL AS has_password, "
        "tm.role AS tenant_role FROM users u JOIN tenant_memberships tm ON tm.user_id = u.id "
        "WHERE u.id = ? AND tm.tenant_id = ?",
        (user_id, ctx.tenant_id),
    ).fetchone()
    conn.close()
    return _row_to_dict(updated)


@router.delete("/users/{user_id}")
def delete_user(user_id: str, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    if user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself from the tenant")
    conn = get_db_connection()
    if _tenant_role(conn, ctx.tenant_id, user_id) == "owner":
        _require_tenant_owner(conn, ctx.tenant_id, ctx.user_id)
    membership = conn.execute(
        "SELECT 1 FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?",
        (ctx.tenant_id, user_id),
    ).fetchone()
    if not membership:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found in tenant")

    conn.execute(
        "DELETE FROM group_memberships WHERE tenant_id = ? AND user_id = ?",
        (ctx.tenant_id, user_id),
    )
    conn.execute(
        "DELETE FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?",
        (ctx.tenant_id, user_id),
    )

    still_linked = conn.execute(
        "SELECT 1 FROM tenant_memberships WHERE user_id = ? LIMIT 1",
        (user_id,),
    ).fetchone()
    if not still_linked:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    conn.commit()
    conn.close()
    return {"deleted": True, "id": user_id}


@router.get("/groups")
def list_groups(request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT g.*,
               (SELECT COUNT(1) FROM group_memberships gm WHERE gm.group_id = g.id) AS member_count
        FROM groups g
        WHERE g.tenant_id = ?
        ORDER BY g.name ASC
        """,
        (ctx.tenant_id,),
    ).fetchall()
    conn.close()
    return {"groups": [_row_to_dict(r) for r in rows]}


@router.post("/groups")
def create_group(req: GroupCreateRequest, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    now = datetime.utcnow().isoformat()
    group_id = f"group_{uuid.uuid4().hex[:8]}"
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO groups (id, tenant_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (group_id, ctx.tenant_id, req.name.strip(), req.description.strip(), now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


@router.put("/groups/{group_id}")
def update_group(group_id: str, req: GroupUpdateRequest, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM groups WHERE id = ? AND tenant_id = ?", (group_id, ctx.tenant_id)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Group not found")
    now = datetime.utcnow().isoformat()
    name = req.name.strip() if req.name is not None else row["name"]
    description = req.description.strip() if req.description is not None else row["description"]
    conn.execute(
        "UPDATE groups SET name = ?, description = ?, updated_at = ? WHERE id = ?",
        (name, description, now, group_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    conn.close()
    return _row_to_dict(updated)


@router.delete("/groups/{group_id}")
def delete_group(group_id: str, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    conn = get_db_connection()
    group = conn.execute(
        "SELECT 1 FROM groups WHERE id = ? AND tenant_id = ?",
        (group_id, ctx.tenant_id),
    ).fetchone()
    if not group:
        conn.close()
        raise HTTPException(status_code=404, detail="Group not found")
    conn.execute("DELETE FROM groups WHERE id = ? AND tenant_id = ?", (group_id, ctx.tenant_id))
    conn.commit()
    conn.close()
    return {"deleted": True, "id": group_id}


@router.get("/groups/{group_id}/members")
def list_group_members(group_id: str, request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    group = conn.execute("SELECT * FROM groups WHERE id = ? AND tenant_id = ?", (group_id, ctx.tenant_id)).fetchone()
    if not group:
        conn.close()
        raise HTTPException(status_code=404, detail="Group not found")
    rows = conn.execute(
        """
        SELECT u.id, u.email, u.display_name, u.status
        FROM group_memberships gm
        JOIN users u ON u.id = gm.user_id
        WHERE gm.group_id = ?
        ORDER BY u.display_name ASC
        """,
        (group_id,),
    ).fetchall()
    conn.close()
    return {"members": [_row_to_dict(r) for r in rows]}


@router.post("/groups/{group_id}/members")
def add_group_member(group_id: str, req: GroupMemberRequest, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    conn = get_db_connection()
    group = conn.execute("SELECT * FROM groups WHERE id = ? AND tenant_id = ?", (group_id, ctx.tenant_id)).fetchone()
    if not group:
        conn.close()
        raise HTTPException(status_code=404, detail="Group not found")
    if not _tenant_role(conn, ctx.tenant_id, req.user_id):
        conn.close()
        raise HTTPException(status_code=404, detail="User not found in tenant")
    now = datetime.utcnow().isoformat()
    insert_ignore(conn, "group_memberships",
                  {"group_id": group_id, "user_id": req.user_id, "tenant_id": ctx.tenant_id, "created_at": now},
                  key=("group_id", "user_id"))
    conn.commit()
    conn.close()
    return {"success": True, "group_id": group_id, "user_id": req.user_id}


@router.delete("/groups/{group_id}/members/{user_id}")
def remove_group_member(group_id: str, user_id: str, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    conn = get_db_connection()
    group = conn.execute("SELECT * FROM groups WHERE id = ? AND tenant_id = ?", (group_id, ctx.tenant_id)).fetchone()
    if not group:
        conn.close()
        raise HTTPException(status_code=404, detail="Group not found")
    conn.execute("DELETE FROM group_memberships WHERE group_id = ? AND user_id = ? AND tenant_id = ?",
                 (group_id, user_id, ctx.tenant_id))
    conn.commit()
    conn.close()
    return {"success": True, "group_id": group_id, "user_id": user_id}


@router.get("/projects")
def list_projects(request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM projects WHERE tenant_id = ? ORDER BY updated_at DESC",
        (ctx.tenant_id,),
    ).fetchall()
    conn.close()
    return {"projects": [_row_to_dict(r) for r in rows]}


@router.post("/projects")
def create_project(req: ProjectCreateRequest, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    now = datetime.utcnow().isoformat()
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO projects (id, tenant_id, name, description, status, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (project_id, ctx.tenant_id, req.name.strip(), req.description.strip(), ctx.user_id, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


@router.put("/projects/{project_id}")
def update_project(project_id: str, req: ProjectUpdateRequest, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM projects WHERE id = ? AND tenant_id = ?", (project_id, ctx.tenant_id)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Project not found")
    now = datetime.utcnow().isoformat()
    name = req.name.strip() if req.name is not None else row["name"]
    description = req.description.strip() if req.description is not None else row["description"]
    status = req.status if req.status is not None else row["status"]
    conn.execute(
        "UPDATE projects SET name = ?, description = ?, status = ?, updated_at = ? WHERE id = ?",
        (name, description, status, now, project_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return _row_to_dict(updated)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    conn = get_db_connection()
    row = conn.execute(
        "SELECT 1 FROM projects WHERE id = ? AND tenant_id = ?",
        (project_id, ctx.tenant_id),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Project not found")

    removed = _purge_scope(conn, ctx.tenant_id, project_id)
    conn.execute("DELETE FROM projects WHERE id = ? AND tenant_id = ?", (project_id, ctx.tenant_id))
    conn.execute(   # cascaded too where foreign keys are on; explicit for databases that don't
        "DELETE FROM acl_entries WHERE tenant_id = ? AND project_id = ?",
        (ctx.tenant_id, project_id),
    )
    conn.commit()
    conn.close()
    return {"deleted": True, "id": project_id, "removed": removed}


@router.get("/acls")
def list_acls(request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM acl_entries WHERE tenant_id = ? ORDER BY created_at DESC",
        (ctx.tenant_id,),
    ).fetchall()
    conn.close()
    return {"acls": [_row_to_dict(r) for r in rows]}


@router.post("/acls")
def create_acl(req: AclCreateRequest, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    now = datetime.utcnow().isoformat()
    acl_id = f"acl_{uuid.uuid4().hex[:10]}"
    conn = get_db_connection()
    _validate_acl(conn, ctx.tenant_id, req.project_id, req.principal_type, req.principal_id, req.effect)
    conn.execute(
        """
        INSERT INTO acl_entries (id, tenant_id, project_id, principal_type, principal_id, resource, action, effect, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            acl_id,
            ctx.tenant_id,
            req.project_id,
            req.principal_type,
            req.principal_id,
            req.resource,
            req.action,
            req.effect,
            now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM acl_entries WHERE id = ?", (acl_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


@router.put("/acls/{acl_id}")
def update_acl(acl_id: str, req: AclUpdateRequest, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM acl_entries WHERE id = ? AND tenant_id = ?", (acl_id, ctx.tenant_id)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="ACL entry not found")
    now = datetime.utcnow().isoformat()
    project_id = req.project_id if req.project_id is not None else row["project_id"]
    principal_type = req.principal_type if req.principal_type is not None else row["principal_type"]
    principal_id = req.principal_id if req.principal_id is not None else row["principal_id"]
    resource = req.resource if req.resource is not None else row["resource"]
    action = req.action if req.action is not None else row["action"]
    effect = req.effect if req.effect is not None else row["effect"]
    _validate_acl(conn, ctx.tenant_id, project_id, principal_type, principal_id, effect)
    conn.execute(
        """
        UPDATE acl_entries
        SET project_id = ?, principal_type = ?, principal_id = ?, resource = ?, action = ?, effect = ?, created_at = ?
        WHERE id = ?
        """,
        (project_id, principal_type, principal_id, resource, action, effect, now, acl_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM acl_entries WHERE id = ?", (acl_id,)).fetchone()
    conn.close()
    return _row_to_dict(updated)


@router.delete("/acls/{acl_id}")
def delete_acl(acl_id: str, request: Request):
    ctx = get_request_context(request)
    _require_admin(ctx)
    conn = get_db_connection()
    cur = conn.execute("DELETE FROM acl_entries WHERE id = ? AND tenant_id = ?", (acl_id, ctx.tenant_id))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="ACL entry not found")
    return {"deleted": True, "id": acl_id}


@router.post("/access-check")
def access_check(req: AccessCheckRequest, request: Request):
    ctx = get_request_context(request)
    if req.user_id.strip() != ctx.user_id:
        _require_admin(ctx)
    if req.tenant_id and req.tenant_id.strip() != ctx.tenant_id:
        raise HTTPException(status_code=400, detail="Access checks run within your current tenant")
    eval_ctx = RequestContext(
        tenant_id=ctx.tenant_id,
        project_id=req.project_id.strip(),
        user_id=req.user_id.strip(),
    )
    allowed = has_access(eval_ctx, req.resource.strip(), req.action.strip())
    return {
        "allowed": allowed,
        "tenant_id": eval_ctx.tenant_id,
        "project_id": eval_ctx.project_id,
        "user_id": eval_ctx.user_id,
        "resource": req.resource.strip(),
        "action": req.action.strip(),
    }
