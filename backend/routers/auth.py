"""
auth.py — sign-up, login and the current user's identity.

POST /api/auth/signup           — create an account + a tenant you own; returns a session
POST /api/auth/login            — email + password; returns a session token
POST /api/auth/logout           — end the current session
GET  /api/auth/me               — current user, tenants (with role) and their projects
POST /api/auth/change-password  — requires the current password; ends all other sessions
GET  /api/auth/config           — public: whether sign-up is enabled
/api/auth/sso/*                 — single sign-on (routers/sso.py)

The token is returned in the body and sent back as ``Authorization: Bearer <token>``.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_db_connection
from services import auth
from services.request_context import auth_mode, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)
    display_name: str = Field(default="", max_length=100)
    workspace_name: Optional[str] = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=256)
    new_password: str = Field(..., max_length=256)


def _me(user_id: str, sso_tenant: Optional[str] = None) -> dict:
    conn = get_db_connection()
    row = conn.execute("SELECT id, email, display_name, status, password_hash IS NOT NULL AS has_password "
                       "FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    user = {**dict(row), "has_password": bool(row["has_password"]),
            "server_admin": not sso_tenant and auth.is_server_admin(user_id)}
    return {"user": user, "tenants": auth.memberships(user_id, sso_tenant),
            "session": {"sso": bool(sso_tenant), "tenant_id": sso_tenant}}


def session_response(user_id: str, request: Request, tenant_id: Optional[str] = None,
                     sso_provider_id: Optional[str] = None) -> dict:
    token, session = auth.create_session(user_id, request.headers.get("user-agent", ""), tenant_id, sso_provider_id)
    return {"token": token, "expires_at": session["expires_at"], **_me(user_id, tenant_id)}



@router.get("/config")
def auth_config():
    return {"signup_enabled": auth.signup_enabled(), "mode": auth_mode()}


@router.post("/signup", status_code=201)
def signup(req: SignupRequest, request: Request):
    ids = auth.signup(req.email, req.password, req.display_name, req.workspace_name)
    return session_response(ids["user_id"], request)


@router.post("/login")
def login(req: LoginRequest, request: Request):
    user = auth.authenticate_password(req.email, req.password)
    if not auth.memberships(user["id"]):
        conn = get_db_connection()
        enforced = conn.execute("SELECT 1 FROM tenant_memberships WHERE user_id = ?", (user["id"],)).fetchone()
        conn.close()
        if enforced:
            raise HTTPException(status_code=403, detail="Your workspace requires single sign-on. Use \"Sign in with SSO\".")
    return session_response(user["id"], request)


@router.post("/logout")
def logout(request: Request):
    get_current_user(request)
    session_id = getattr(request.state, "session_id", None)
    if session_id:
        auth.revoke_session(session_id)
    return {"logged_out": True}


@router.get("/me")
def me(request: Request):
    user_id = get_current_user(request)
    return _me(user_id, getattr(request.state, "sso_tenant", None))


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, request: Request):
    user_id = get_current_user(request)
    conn = get_db_connection()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not row or not auth.verify_password(req.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    auth.set_password(user_id, req.new_password)  # revokes every session, including this one
    sso = getattr(request.state, "sso_tenant", None)   # the new session keeps the old one's scope
    return session_response(user_id, request, sso, None)
