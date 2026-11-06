import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request

from db import get_db_connection
from services import auth


@dataclass
class RequestContext:
    tenant_id: str
    project_id: str
    user_id: str


def auth_mode() -> str:
    """'session' (default): callers must log in. 'headers': legacy dev mode that also
    trusts x-user-id when no session token is sent — never use it on a shared server."""
    return "headers" if os.getenv("AUTH_MODE", "session").strip().lower() == "headers" else "session"


def get_current_user(request: Request) -> str:
    """The authenticated user id; raises 401 when the caller is not signed in.

    Also usable as a router dependency (``Depends(get_current_user)``) to make every
    route behind it require a login.
    """
    cached: Optional[str] = getattr(request.state, "user_id", None)
    if cached:
        return cached

    token = auth.extract_token(request)
    if token:
        user = auth.resolve_session(token)
        if not user:
            raise HTTPException(status_code=401, detail="Session expired or invalid. Sign in again.",
                                headers={"WWW-Authenticate": "Bearer"})
        request.state.user_id = user.user_id
        request.state.session_id = user.session_id
        return user.user_id

    if auth_mode() == "headers":
        user_id = request.headers.get("x-user-id", "user_admin").strip() or "user_admin"
        request.state.user_id = user_id
        return user_id

    raise HTTPException(status_code=401, detail="Not signed in.", headers={"WWW-Authenticate": "Bearer"})


def get_request_context(request: Request) -> RequestContext:
    """Resolve the caller's tenant/project scope.

    The user comes from the session. Tenant and project come from x-tenant-id /
    x-project-id (defaulting to the user's first tenant and its first project) and
    must be ones the user belongs to. In legacy 'headers' mode without a session,
    the old header defaults apply unchecked.
    """
    cached: Optional[RequestContext] = getattr(request.state, "ctx", None)
    if cached:
        return cached

    user_id = get_current_user(request)
    tenant_hdr = request.headers.get("x-tenant-id", "").strip()
    project_hdr = request.headers.get("x-project-id", "").strip()

    if getattr(request.state, "session_id", None) is None:  # legacy headers mode
        ctx = RequestContext(tenant_id=tenant_hdr or "tenant_demo",
                             project_id=project_hdr or "proj_research", user_id=user_id)
        request.state.ctx = ctx
        return ctx

    conn = get_db_connection()
    try:
        if tenant_hdr:
            member = conn.execute(
                "SELECT 1 FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?", (tenant_hdr, user_id)
            ).fetchone()
            if not member:
                raise HTTPException(status_code=403, detail=f"You are not a member of tenant '{tenant_hdr}'.")
            tenant_id = tenant_hdr
        else:
            row = conn.execute(
                "SELECT tenant_id FROM tenant_memberships WHERE user_id = ? ORDER BY created_at ASC LIMIT 1",
                (user_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="Your account is not a member of any tenant.")
            tenant_id = row[0]

        if project_hdr:
            if not conn.execute(
                "SELECT 1 FROM projects WHERE id = ? AND tenant_id = ?", (project_hdr, tenant_id)
            ).fetchone():
                raise HTTPException(status_code=403, detail=f"Project '{project_hdr}' is not in tenant '{tenant_id}'.")
            project_id = project_hdr
        else:
            row = conn.execute(
                "SELECT id FROM projects WHERE tenant_id = ? ORDER BY created_at ASC LIMIT 1", (tenant_id,)
            ).fetchone()
            project_id = row[0] if row else ""
    finally:
        conn.close()

    ctx = RequestContext(tenant_id=tenant_id, project_id=project_id, user_id=user_id)
    request.state.ctx = ctx
    return ctx


# The signed-in user of the current request, for code deep inside a run (long-term memory is about
# them on interactive runs). Set with the secret scope below.
request_user: ContextVar[Optional[str]] = ContextVar("request_user", default=None)


async def bind_secret_scope(request: Request) -> None:
    """Router dependency: expose the caller's tenant/project to secret resolution.

    Tool execution happens deep inside run/stream handlers that never see the request,
    so the scope rides on a ContextVar for the rest of the request (including streamed
    responses). A request whose scope can't be resolved simply can't use secrets.
    """
    from starlette.concurrency import run_in_threadpool
    from services.secret_store import request_scope

    try:
        ctx = await run_in_threadpool(get_request_context, request)
    except HTTPException:
        return
    request_scope.set((ctx.tenant_id, ctx.project_id))
    request_user.set(ctx.user_id)
