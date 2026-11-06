"""
api_keys.py — issuing, verifying and rate-limiting API keys for the public /v1 API.

Keys look like ``ps_<43 url-safe chars>``. Only the SHA-256 hash is stored (keys are
256-bit random, so a slow hash adds nothing); the plaintext is returned once by
``create_key``. A key is bound to a tenant + project and acts as the user who created
it, so every request is still checked against that user's ACLs — a key can never do
more than its creator, and loses access when the creator does.

Accepted on requests as ``Authorization: Bearer <key>`` or ``X-API-Key: <key>``.
"""

import hashlib
import json
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
from services.acl import has_access
from services.request_context import RequestContext

KEY_PREFIX = "ps_"
# apps:write (create / edit drafts) and apps:publish (put a draft live) are used by the MCP
# server's write tools (routers/v1_mcp.py); tools:* by tools as code (routers/v1_tools.py, the
# SDK's `pipesets tool`). A key gets them only when they're asked for.
SCOPES = ("apps:read", "apps:run", "apps:write", "apps:publish", "tools:read", "tools:write", "tools:execute")
DEFAULT_SCOPES = ["apps:read", "apps:run"]



@dataclass
class ApiKeyPrincipal:
    key_id: str
    name: str
    scopes: List[str]
    ctx: RequestContext


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _row_to_dict(row) -> Dict[str, Any]:
    """Public view of a key row — never includes the hash."""
    return {
        "id": row["id"],
        "name": row["name"],
        "key_prefix": row["key_prefix"],
        "tenant_id": row["tenant_id"],
        "project_id": row["project_id"],
        "created_by": row["created_by"],
        "scopes": json.loads(row["scopes"] or "[]"),
        "rate_limit_rpm": row["rate_limit_rpm"],
        "request_count": row["request_count"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "expires_at": row["expires_at"],
        "revoked_at": row["revoked_at"],
        "active": row["revoked_at"] is None and not _expired(row["expires_at"]),
    }


def _expired(expires_at: Optional[str]) -> bool:
    return bool(expires_at) and datetime.fromisoformat(expires_at) <= datetime.utcnow()


# ── Management ────────────────────────────────────────────────────────────────

def create_key(
    ctx: RequestContext,
    name: str,
    scopes: Optional[List[str]] = None,
    rate_limit_rpm: int = 60,
    expires_in_days: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Issue a key for ctx's tenant/project, acting as ctx.user_id. Returns (plaintext, record)."""
    scopes = scopes or DEFAULT_SCOPES
    unknown = [s for s in scopes if s not in SCOPES]
    if unknown:
        raise ValueError(f"Unknown scope(s): {', '.join(unknown)}. Valid: {', '.join(SCOPES)}")

    plaintext = KEY_PREFIX + secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires_at = (now + timedelta(days=expires_in_days)).isoformat() if expires_in_days else None
    key_id = f"key_{uuid.uuid4().hex[:12]}"
    with _db() as conn:
        conn.execute(
            "INSERT INTO api_keys (id, tenant_id, project_id, created_by, name, key_prefix, key_hash, "
            "scopes, rate_limit_rpm, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key_id, ctx.tenant_id, ctx.project_id, ctx.user_id, name, plaintext[:12],
             hash_key(plaintext), json.dumps(scopes), rate_limit_rpm, now.isoformat(), expires_at),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    return plaintext, _row_to_dict(row)


def list_keys(tenant_id: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM api_keys WHERE tenant_id = ?"
    params: List[Any] = [tenant_id]
    if project_id:
        sql += " AND project_id = ?"
        params.append(project_id)
    with _db() as conn:
        rows = conn.execute(sql + " ORDER BY created_at DESC", params).fetchall()
    return [_row_to_dict(r) for r in rows]


def revoke_key(key_id: str, tenant_id: str) -> bool:
    with _db() as conn:
        cur = conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND tenant_id = ? AND revoked_at IS NULL",
            (datetime.utcnow().isoformat(), key_id, tenant_id),
        )
        conn.commit()
    shared_state.reset(f"rl:key:{key_id}")
    return cur.rowcount > 0


# ── Request authentication ────────────────────────────────────────────────────

def _extract_key(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return (request.headers.get("x-api-key") or "").strip() or None


def _check_rate(key_id: str, rpm: int) -> Optional[int]:
    """Sliding 60 s window, shared by every replica (services/shared_state.py). Returns seconds
    to wait when over the limit, else None; refused requests don't count."""
    if rpm <= 0:
        return None
    w = shared_state.add(f"rl:key:{key_id}", 60, rpm)
    return None if w.allowed else w.retry_after


def authenticate(request: Request, scope: Optional[str]) -> ApiKeyPrincipal:
    """Resolve the request's API key; raise 401 / 403 / 429 when it may not proceed.
    ``scope=None`` accepts a key with any scope (the caller checks ``principal.scopes``)."""
    key = _extract_key(request)
    if not key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Send 'Authorization: Bearer <key>' or 'X-API-Key: <key>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    with _db() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (hash_key(key),)).fetchone()
    if not row or row["revoked_at"] or _expired(row["expires_at"]):
        raise HTTPException(status_code=403, detail="Invalid, revoked or expired API key.")

    scopes = json.loads(row["scopes"] or "[]")
    if scope is not None and scope not in scopes:
        raise HTTPException(status_code=403, detail=f"API key lacks the '{scope}' scope.")

    ctx = RequestContext(tenant_id=row["tenant_id"], project_id=row["project_id"], user_id=row["created_by"])
    resource, action = (scope or "apps:read").split(":")
    # apps:run executes a published app, which needs read access to it
    if not has_access(ctx, resource, "read" if action == "run" else action):
        raise HTTPException(status_code=403, detail="The key's owner no longer has access to this project.")

    retry_after = _check_rate(row["id"], int(row["rate_limit_rpm"]))
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {row['rate_limit_rpm']} requests/minute for this key.",
            headers={"Retry-After": str(retry_after)},
        )

    with _db() as conn:
        conn.execute(
            "UPDATE api_keys SET last_used_at = ?, request_count = request_count + 1 WHERE id = ?",
            (datetime.utcnow().isoformat(), row["id"]),
        )
        conn.commit()
    return ApiKeyPrincipal(key_id=row["id"], name=row["name"], scopes=scopes, ctx=ctx)


def require_scope(scope: str):
    """FastAPI dependency factory: ``Depends(require_scope("apps:run"))``."""
    def dependency(request: Request) -> ApiKeyPrincipal:
        return authenticate(request, scope)
    return dependency
