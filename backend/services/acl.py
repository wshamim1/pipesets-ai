from typing import List

from fastapi import HTTPException

from db import get_db_connection
from services.request_context import RequestContext


def _user_group_ids(conn, tenant_id: str, user_id: str) -> List[str]:
    rows = conn.execute(
        "SELECT group_id FROM group_memberships WHERE tenant_id = ? AND user_id = ?",
        (tenant_id, user_id),
    ).fetchall()
    return [r[0] for r in rows]


def has_access(ctx: RequestContext, resource: str, action: str) -> bool:
    conn = get_db_connection()
    try:
        # Tenant membership required
        member = conn.execute(
            "SELECT role FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?",
            (ctx.tenant_id, ctx.user_id),
        ).fetchone()
        if not member:
            return False

        # Tenant owner shortcut
        if member[0] == "owner":
            return True

        # Entries for the user or any of their groups, scoped to this project or
        # tenant-wide, matching the resource/action exactly or by '*'.
        # An explicit deny beats any allow; no matching entry means no access.
        groups = _user_group_ids(conn, ctx.tenant_id, ctx.user_id)
        group_marks = ",".join("?" * len(groups)) or "NULL"
        effects = {
            r[0] for r in conn.execute(
                f"""
                SELECT DISTINCT effect FROM acl_entries
                WHERE tenant_id = ?
                  AND (project_id IS NULL OR project_id = ?)
                  AND ((principal_type = 'user' AND principal_id = ?)
                       OR (principal_type = 'group' AND principal_id IN ({group_marks})))
                  AND resource IN (?, '*')
                  AND action IN (?, '*')
                """,
                (ctx.tenant_id, ctx.project_id, ctx.user_id, *groups, resource, action),
            ).fetchall()
        }
        return "allow" in effects and "deny" not in effects
    finally:
        conn.close()


def require_access(ctx: RequestContext, resource: str, action: str) -> None:
    if has_access(ctx, resource, action):
        return
    raise HTTPException(
        status_code=403,
        detail=f"Access denied for user '{ctx.user_id}' on resource '{resource}' action '{action}' in project '{ctx.project_id}'.",
    )


def require_server_admin(ctx: RequestContext) -> None:
    """Server-wide settings (the database) need a server admin, not just a workspace owner."""
    from services.auth import is_server_admin  # lazy: services.auth imports request_context too

    if not is_server_admin(ctx.user_id):
        raise HTTPException(status_code=403, detail="Only a server admin can do this.")
