"""
llm_settings.py — Settings → Model backends: which LLM backend serves a provider, and its
default base URL, per project or for the whole workspace.

A setting belongs to a tenant and either one project or, with project_id NULL, every project
in the tenant. Each field resolves on its own, most specific first:

    backend:  project row → workspace row → LLM_BACKEND_<PROVIDER> → LLM_BACKEND → "auto"
    base_url: node's base URL → project row → workspace row → the backend's default

"auto" (or "") in a row means "not set here" and falls through. Rows are cached per scope for
a few seconds so a model call doesn't cost a query; writes in this process clear the cache,
other replicas see them within CACHE_TTL_S.
"""

import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from db import get_db_connection
from services.secret_store import current_scope_ids

CACHE_TTL_S = 10.0
AUTO = "auto"

# (tenant_id, project_id) → (expires_at, {provider: {"project": row|None, "shared": row|None}})
_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Dict[str, Optional[Dict[str, Any]]]]]] = {}


class SettingsError(ValueError):
    pass


def clear_cache() -> None:
    _cache.clear()


def _rows(scope: Tuple[str, str]) -> Dict[str, Dict[str, Optional[Dict[str, Any]]]]:
    hit = _cache.get(scope)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    tenant_id, project_id = scope
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT provider, project_id, backend, base_url, updated_by, updated_at FROM llm_settings "
            "WHERE tenant_id = ? AND (project_id = ? OR project_id IS NULL)",
            (tenant_id, project_id),
        ).fetchall()
    finally:
        conn.close()
    by_provider: Dict[str, Dict[str, Optional[Dict[str, Any]]]] = {}
    for r in rows:
        level = "shared" if r["project_id"] is None else "project"
        by_provider.setdefault(r["provider"], {"project": None, "shared": None})[level] = dict(r)
    _cache[scope] = (time.monotonic() + CACHE_TTL_S, by_provider)
    return by_provider


def _env_backend(provider: str) -> Tuple[str, str]:
    for var in (f"LLM_BACKEND_{provider.upper()}", "LLM_BACKEND"):
        value = os.getenv(var, "").strip().lower()
        if value and value != AUTO:
            return value, f"env:{var}"
    return AUTO, "default"


def effective(provider: str, scope: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
    """{"backend", "backend_source", "base_url", "base_url_source"} for ``provider`` in ``scope``
    (default: the run or request in progress). Sources: project | workspace | env:<VAR> | default."""
    provider = (provider or "").strip().lower()
    scope = scope or current_scope_ids()
    levels = _rows(scope).get(provider, {}) if scope else {}
    out: Dict[str, Any] = {"backend": AUTO, "backend_source": "default", "base_url": "", "base_url_source": "default"}
    for level, label in (("project", "project"), ("shared", "workspace")):
        row = levels.get(level)
        if not row:
            continue
        if out["backend_source"] == "default" and (row["backend"] or AUTO) != AUTO:
            out["backend"], out["backend_source"] = row["backend"], label
        if out["base_url_source"] == "default" and row["base_url"]:
            out["base_url"], out["base_url_source"] = row["base_url"], label
    if out["backend_source"] == "default":
        out["backend"], out["backend_source"] = _env_backend(provider)
    return out


def rows_for(tenant_id: str, project_id: str) -> Dict[str, Dict[str, Optional[Dict[str, Any]]]]:
    return _rows((tenant_id, project_id))


def _validate(provider: str, backend: str, base_url: str, allowed_backends: List[str]) -> Tuple[str, str, str]:
    provider = (provider or "").strip().lower()
    backend = (backend or AUTO).strip().lower()
    base_url = (base_url or "").strip().rstrip("/")
    if not provider:
        raise SettingsError("provider is required")
    if backend != AUTO and backend not in allowed_backends:
        raise SettingsError(f"'{backend}' can't serve {provider} (choose from: {', '.join([AUTO, *allowed_backends])})")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise SettingsError("base URL must start with http:// or https://")
    return provider, backend, base_url


def _existing(conn, tenant_id: str, project_id: Optional[str], provider: str):
    return conn.execute(
        "SELECT id, backend, base_url FROM llm_settings WHERE tenant_id = ? AND provider = ? AND "
        + ("project_id IS NULL" if project_id is None else "project_id = ?"),
        (tenant_id, provider) + (() if project_id is None else (project_id,)),
    ).fetchone()


def set_setting(tenant_id: str, project_id: Optional[str], user_id: str, provider: str,
                backend: Optional[str], base_url: Optional[str], allowed_backends: List[str]) -> Dict[str, Any]:
    """Create or update the row for ``provider`` at this scope (project_id None = workspace).
    ``None`` keeps a field's saved value. A row that ends up setting nothing ("auto", no base
    URL) is removed instead."""
    provider = (provider or "").strip().lower()
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    try:
        existing = _existing(conn, tenant_id, project_id, provider)
        if backend is None:
            backend = existing["backend"] if existing else AUTO
        if base_url is None:
            base_url = existing["base_url"] if existing else ""
        provider, backend, base_url = _validate(provider, backend, base_url, allowed_backends)
        if backend == AUTO and not base_url:
            if existing:
                conn.execute("DELETE FROM llm_settings WHERE id = ?", (existing["id"],))
                conn.commit()
            clear_cache()
            return {"provider": provider, "backend": AUTO, "base_url": ""}
        if existing:
            conn.execute("UPDATE llm_settings SET backend = ?, base_url = ?, updated_by = ?, updated_at = ? WHERE id = ?",
                         (backend, base_url, user_id, now, existing["id"]))
        else:
            conn.execute(
                "INSERT INTO llm_settings (id, tenant_id, project_id, provider, backend, base_url, updated_by, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"llms_{uuid.uuid4().hex[:16]}", tenant_id, project_id, provider, backend, base_url, user_id, now, now),
            )
        conn.commit()
    finally:
        conn.close()
    clear_cache()
    return {"provider": provider, "backend": backend, "base_url": base_url}


def clear_setting(tenant_id: str, project_id: Optional[str], provider: str) -> None:
    provider = (provider or "").strip().lower()
    conn = get_db_connection()
    try:
        conn.execute(
            "DELETE FROM llm_settings WHERE tenant_id = ? AND provider = ? AND "
            + ("project_id IS NULL" if project_id is None else "project_id = ?"),
            (tenant_id, provider) + (() if project_id is None else (project_id,)),
        )
        conn.commit()
    finally:
        conn.close()
    clear_cache()
