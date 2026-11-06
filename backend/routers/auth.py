"""
auth.py — sign-up, login and the current user's identity.

POST /api/auth/signup           — create an account + a tenant you own; returns a session
POST /api/auth/login            — email + password; returns a session token
POST /api/auth/logout           — end the current session
GET  /api/auth/me               — current user, tenants (with role) and their projects
POST /api/auth/change-password  — requires the current password; ends all other sessions
GET  /api/auth/config           — public: whether sign-up is enabled

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


def _me(user_id: str) -> dict:
    conn = get_db_connection()
    row = conn.execute("SELECT id, email, display_name, status FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    return {"user": {**dict(row), "server_admin": auth.is_server_admin(user_id)}, "tenants": auth.memberships(user_id)}


def _session_response(user_id: str, request: Request) -> dict:
    token, session = auth.create_session(user_id, request.headers.get("user-agent", ""))
    return {"token": token, "expires_at": session["expires_at"], **_me(user_id)}


@router.get("/config")
def auth_config():
    return {"signup_enabled": auth.signup_enabled(), "mode": auth_mode()}


@router.post("/signup", status_code=201)
def signup(req: SignupRequest, request: Request):
    ids = auth.signup(req.email, req.password, req.display_name, req.workspace_name)
    return _session_response(ids["user_id"], request)


@router.post("/login")
def login(req: LoginRequest, request: Request):
    user = auth.authenticate_password(req.email, req.password)
    return _session_response(user["id"], request)


@router.post("/logout")
def logout(request: Request):
    get_current_user(request)
    session_id = getattr(request.state, "session_id", None)
    if session_id:
        auth.revoke_session(session_id)
    return {"logged_out": True}


@router.get("/me")
def me(request: Request):
    return _me(get_current_user(request))


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, request: Request):
    user_id = get_current_user(request)
    conn = get_db_connection()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not row or not auth.verify_password(req.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    auth.set_password(user_id, req.new_password)  # revokes every session, including this one
    return _session_response(user_id, request)
