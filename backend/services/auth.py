"""
auth.py — passwords, sign-up, login sessions for the UI and internal /api routes.

Passwords are hashed with scrypt (stdlib, per-user salt). A login issues an opaque
session token ``uas_<43 url-safe chars>``; like API keys only its SHA-256 hash is
stored, so the plaintext exists only in the client. Sessions expire after
AUTH_SESSION_TTL_HOURS (default 168 = 7 days) and die immediately on logout, password
change, or when the user is disabled.

Sign-up creates the user, a new tenant they own and a default project. Joining an
existing tenant happens through an admin adding the user's email (see routers/iam.py).

Accepted on requests as ``Authorization: Bearer <token>`` or ``X-Session-Token: <token>``.
API keys (``ps_``) are never accepted as sessions — they only reach /v1.
"""

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional, Tuple

from fastapi import HTTPException, Request

from db import get_db_connection
from services import shared_state

TOKEN_PREFIX = "uas_"
MIN_PASSWORD_LENGTH = 8
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# scrypt cost: 2**14 * 8 * 128 B = 16 MiB per hash, ~50 ms
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1

# Failed logins per email: at most _MAX_FAILURES in _FAILURE_WINDOW s, counted across replicas
# (services/shared_state.py)
_MAX_FAILURES = 10
_FAILURE_WINDOW = 15 * 60


@dataclass
class SessionUser:
    session_id: str
    user_id: str
    email: str
    display_name: str


def session_ttl() -> timedelta:
    return timedelta(hours=int(os.getenv("AUTH_SESSION_TTL_HOURS", "168")))


def signup_enabled() -> bool:
    return os.getenv("AUTH_ALLOW_SIGNUP", "1") != "0"


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Passwords ─────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64),
                                n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return email


def set_password(user_id: str, password: str) -> None:
    """Set a user's password and end all their sessions."""
    validate_password(password)
    now = datetime.utcnow().isoformat()
    with _db() as conn:
        conn.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                     (hash_password(password), now, user_id))
        conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                     (now, user_id))
        conn.commit()


# ── Sessions ──────────────────────────────────────────────────────────────────

def create_session(user_id: str, user_agent: str = "") -> Tuple[str, Dict[str, Any]]:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires_at = (now + session_ttl()).isoformat()
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    with _db() as conn:
        conn.execute(
            "INSERT INTO auth_sessions (id, user_id, token_hash, user_agent, created_at, last_seen_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, user_id, _hash_token(token), user_agent[:200], now.isoformat(), now.isoformat(), expires_at),
        )
        conn.commit()
    return token, {"id": session_id, "expires_at": expires_at}


def extract_token(request: Request) -> Optional[str]:
    token = (request.headers.get("x-session-token") or "").strip()
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    return token if token.startswith(TOKEN_PREFIX) else None


def resolve_session(token: str) -> Optional[SessionUser]:
    """The active user behind a session token, or None if it is unknown/expired/revoked."""
    now = datetime.utcnow().isoformat()
    with _db() as conn:
        row = conn.execute(
            """
            SELECT s.id AS session_id, s.expires_at, u.id AS user_id, u.email, u.display_name
            FROM auth_sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.revoked_at IS NULL AND u.status = 'active'
            """,
            (_hash_token(token),),
        ).fetchone()
        if not row or row["expires_at"] <= now:
            return None
        conn.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?", (now, row["session_id"]))
        conn.commit()
    return SessionUser(row["session_id"], row["user_id"], row["email"], row["display_name"])


def revoke_session(session_id: str) -> None:
    with _db() as conn:
        conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                     (datetime.utcnow().isoformat(), session_id))
        conn.commit()


# ── Login / sign-up ───────────────────────────────────────────────────────────

def _check_throttle(email: str) -> None:
    w = shared_state.peek(f"login:{email}", _FAILURE_WINDOW, _MAX_FAILURES)
    if w.count >= _MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many failed sign-in attempts. Try again later.",
                            headers={"Retry-After": str(w.retry_after)})


_dummy: List[str] = []


def _dummy_hash() -> str:
    if not _dummy:
        _dummy.append(hash_password(secrets.token_urlsafe(16)))
    return _dummy[0]


def authenticate_password(email: str, password: str) -> Dict[str, Any]:
    """Return the user row for valid credentials; 401 otherwise (same message either way)."""
    email = email.strip().lower()
    _check_throttle(email)
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    # Unknown emails still pay for one scrypt so timing doesn't reveal which emails exist
    stored = row["password_hash"] if row else _dummy_hash()
    if not verify_password(password, stored) or not row:
        shared_state.add(f"login:{email}", _FAILURE_WINDOW)
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="This account is disabled.")
    shared_state.reset(f"login:{email}")
    return dict(row)


# ── Server admins ─────────────────────────────────────────────────────────────
# Manage the server itself (Settings → Database), above any workspace. Granted by: being the
# first account to sign up while no admin can sign in, PIPESETS_SERVER_ADMINS (emails), or
# `python manage.py server-admin EMAIL`. Workspace owners are not server admins by default.

def _env_server_admins() -> set:
    return {normalize_email(e) for e in os.getenv("PIPESETS_SERVER_ADMINS", "").split(",") if e.strip()}


def is_server_admin(user_id: str) -> bool:
    with _db() as conn:
        row = conn.execute("SELECT email, status, server_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or row["status"] != "active":
        return False
    return bool(row["server_admin"]) or normalize_email(row["email"] or "") in _env_server_admins()


def _has_usable_server_admin(conn) -> bool:
    """An active server admin who can actually sign in (the seeded demo admin has no password)."""
    if conn.execute("SELECT 1 FROM users WHERE server_admin = 1 AND status = 'active' "
                    "AND password_hash IS NOT NULL").fetchone():
        return True
    env = _env_server_admins()
    return bool(env) and any(normalize_email(r["email"] or "") in env for r in conn.execute(
        "SELECT email FROM users WHERE status = 'active' AND password_hash IS NOT NULL").fetchall())


def set_server_admin(email: str, on: bool = True) -> Optional[str]:
    """Grant or revoke by email; returns the user id, or None when there's no such user."""
    with _db() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE users SET server_admin = ?, updated_at = ? WHERE id = ?",
                     (1 if on else 0, datetime.utcnow().isoformat(), row["id"]))
        conn.commit()
        return row["id"]


def list_server_admins() -> List[Dict[str, Any]]:
    env = _env_server_admins()
    with _db() as conn:
        rows = conn.execute("SELECT id, email, display_name, status, server_admin, "
                            "password_hash IS NOT NULL AS has_password FROM users ORDER BY email").fetchall()
    return [{"id": r["id"], "email": r["email"], "status": r["status"], "has_password": bool(r["has_password"]),
             "source": "flag" if r["server_admin"] else "PIPESETS_SERVER_ADMINS"}
            for r in rows if r["server_admin"] or normalize_email(r["email"] or "") in env]


def signup(email: str, password: str, display_name: str, workspace_name: Optional[str] = None) -> Dict[str, Any]:
    """Create a user who owns a new tenant with one default project. Returns ids."""
    if not signup_enabled():
        raise HTTPException(status_code=403, detail="Sign-up is disabled on this server.")
    email = normalize_email(email)
    validate_password(password)
    display_name = display_name.strip() or email.split("@")[0]
    workspace_name = (workspace_name or "").strip() or f"{display_name}'s workspace"

    now = datetime.utcnow().isoformat()
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    slug = f"{re.sub(r'[^a-z0-9]+', '-', workspace_name.lower()).strip('-') or 'workspace'}-{uuid.uuid4().hex[:4]}"

    with _db() as conn:
        # An existing email — including one an admin added without a password — is
        # never claimable through sign-up; the admin sets its password instead.
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="An account with this email already exists. Sign in instead.")
        # The first account on a server nobody can administer owns the server (desktop, fresh install)
        first_admin = not _has_usable_server_admin(conn)
        conn.execute(
            "INSERT INTO users (id, email, display_name, status, password_hash, server_admin, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', ?, ?, ?, ?)",
            (user_id, email, display_name, hash_password(password), 1 if first_admin else 0, now, now),
        )
        conn.execute(
            "INSERT INTO tenants (id, name, slug, status, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?)",
            (tenant_id, workspace_name, slug, now, now),
        )
        conn.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)",
            (tenant_id, user_id, now),
        )
        conn.execute(
            "INSERT INTO projects (id, tenant_id, name, description, status, created_by, created_at, updated_at) "
            "VALUES (?, ?, 'Default', 'Created at sign-up', 'active', ?, ?, ?)",
            (project_id, tenant_id, user_id, now, now),
        )
        conn.commit()
    return {"user_id": user_id, "tenant_id": tenant_id, "project_id": project_id}


def memberships(user_id: str) -> List[Dict[str, Any]]:
    """Tenants the user belongs to, with their role and the tenant's projects."""
    with _db() as conn:
        tenants = conn.execute(
            """
            SELECT t.id, t.name, t.slug, tm.role FROM tenant_memberships tm
            JOIN tenants t ON t.id = tm.tenant_id
            WHERE tm.user_id = ? AND t.status = 'active'
            ORDER BY tm.created_at ASC
            """,
            (user_id,),
        ).fetchall()
        result = []
        for t in tenants:
            projects = conn.execute(
                "SELECT id, name, status FROM projects WHERE tenant_id = ? ORDER BY created_at ASC", (t["id"],)
            ).fetchall()
            result.append({**dict(t), "projects": [dict(p) for p in projects]})
    return result
