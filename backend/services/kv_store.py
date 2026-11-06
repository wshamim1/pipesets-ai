"""
kv_store.py — a key-value store agents read and write through the ``key_value_store`` tool.

Entries are JSON values in ``kv_entries`` (migration 0019), keyed by tenant / project, a namespace
chosen on the node, a subject and a key. The subject is the run's end user (``Who.user``: the
signed-in user on the canvas, ``user`` on /v1, MCP and the SDK) for per-user entries, or "" for
entries shared across the project. A run with no end user (schedules, webhooks) can only use shared
entries.

An entry may expire (``ttl_seconds``): expired entries are never returned and are deleted by a
periodic loop (``kv_store.purge``, hourly). Forgetting an end user in the long-term memory inspector
deletes their entries too.

Limits keep one runaway agent from filling the DB: keys up to MAX_KEY_CHARS, values up to
MAX_VALUE_BYTES of JSON, MAX_KEYS live entries per namespace and subject.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from db import IntegrityError, get_db_connection
from services import jobs

logger = logging.getLogger("pipesets-ai-backend")

MAX_KEY_CHARS = 200
MAX_VALUE_BYTES = 64 * 1024
MAX_KEYS = 1000
MAX_TTL_SECONDS = 365 * 86400
MAX_LIST = 100


class StoreError(ValueError):
    """A request the store refuses (bad key, value too large, store full) — the message is for the model."""


def _ts(dt: Optional[datetime] = None) -> str:
    """Fixed-width UTC timestamp: compares correctly as text (as in services/jobs.py)."""
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _check_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        raise StoreError("key is required")
    if len(key) > MAX_KEY_CHARS:
        raise StoreError(f"key is longer than {MAX_KEY_CHARS} characters")
    return key


def _live(now: str) -> Tuple[str, Tuple[str, ...]]:
    return "(expires_at IS NULL OR expires_at > ?)", (now,)


def get(tenant_id: str, project_id: str, namespace: str, subject: str, key: str) -> Tuple[bool, Any]:
    """(found, value) for one key."""
    key = _check_key(key)
    live, live_args = _live(_ts())
    conn = get_db_connection()
    try:
        row = conn.execute(f"SELECT value FROM kv_entries WHERE tenant_id = ? AND project_id = ? AND namespace = ? "
                           f"AND subject = ? AND key = ? AND {live}",
                           (tenant_id, project_id, namespace, subject, key, *live_args)).fetchone()
    finally:
        conn.close()
    return (True, json.loads(row["value"])) if row else (False, None)


def put(tenant_id: str, project_id: str, namespace: str, subject: str, key: str, value: Any,
        ttl_seconds: Optional[float] = None, keep_expiry: bool = False) -> Optional[str]:
    """Store ``value`` under ``key`` (replacing it); returns when it expires, None for never.
    ``keep_expiry`` (the inspector editing a value): an existing entry keeps its expiry unless
    ``ttl_seconds`` is given."""
    key = _check_key(key)
    data = json.dumps(value, ensure_ascii=False)
    if len(data.encode("utf-8")) > MAX_VALUE_BYTES:
        raise StoreError(f"value is larger than {MAX_VALUE_BYTES // 1024} KB of JSON")
    if ttl_seconds is not None and not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise StoreError(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")
    now = datetime.now(timezone.utc)
    stamp = _ts(now)
    expires = _ts(now + timedelta(seconds=ttl_seconds)) if ttl_seconds else None
    scope = (tenant_id, project_id, namespace, subject)
    live, live_args = _live(stamp)
    conn = get_db_connection()
    try:
        # Expired entries in this namespace don't count toward the limit and would block the insert
        conn.execute("DELETE FROM kv_entries WHERE tenant_id = ? AND project_id = ? AND namespace = ? "
                     "AND subject = ? AND expires_at <= ?", (*scope, stamp))
        if keep_expiry and not ttl_seconds:
            row = conn.execute("SELECT expires_at FROM kv_entries WHERE tenant_id = ? AND project_id = ? "
                               "AND namespace = ? AND subject = ? AND key = ?", (*scope, key)).fetchone()
            expires = row["expires_at"] if row else None
        updated =conn.execute("UPDATE kv_entries SET value = ?, expires_at = ?, updated_at = ? WHERE tenant_id = ? "
                               "AND project_id = ? AND namespace = ? AND subject = ? AND key = ?",
                               (data, expires, stamp, *scope, key)).rowcount
        if not updated:
            count = conn.execute(f"SELECT COUNT(*) AS n FROM kv_entries WHERE tenant_id = ? AND project_id = ? "
                                 f"AND namespace = ? AND subject = ? AND {live}", (*scope, *live_args)).fetchone()["n"]
            if count >= MAX_KEYS:
                raise StoreError(f"the store already holds {MAX_KEYS} keys here; delete some first")
            try:
                conn.execute("INSERT INTO kv_entries (tenant_id, project_id, namespace, subject, key, value, "
                             "expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (*scope, key, data, expires, stamp, stamp))
            except IntegrityError:   # written by a concurrent call since the update: last write wins
                conn.rollback()
                conn.execute("UPDATE kv_entries SET value = ?, expires_at = ?, updated_at = ? WHERE tenant_id = ? "
                             "AND project_id = ? AND namespace = ? AND subject = ? AND key = ?",
                             (data, expires, stamp, *scope, key))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return expires


def delete(tenant_id: str, project_id: str, namespace: str, subject: str, key: str) -> bool:
    key = _check_key(key)
    conn = get_db_connection()
    try:
        n = conn.execute("DELETE FROM kv_entries WHERE tenant_id = ? AND project_id = ? AND namespace = ? "
                         "AND subject = ? AND key = ?", (tenant_id, project_id, namespace, subject, key)).rowcount
        conn.commit()
        return n == 1
    finally:
        conn.close()


def list_keys(tenant_id: str, project_id: str, namespace: str, subject: str, prefix: str = "",
              limit: int = MAX_LIST) -> List[Dict[str, Any]]:
    """Live keys (with when they were updated and expire), sorted by key."""
    live, live_args = _live(_ts())
    like = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    conn = get_db_connection()
    try:
        rows = conn.execute(f"SELECT key, updated_at, expires_at FROM kv_entries WHERE tenant_id = ? AND project_id = ? "
                            f"AND namespace = ? AND subject = ? AND key LIKE ? ESCAPE '\\' AND {live} "
                            f"ORDER BY key LIMIT ?",
                            (tenant_id, project_id, namespace, subject, like, *live_args,
                             max(1, min(int(limit), MAX_LIST)))).fetchall()
    finally:
        conn.close()
    return [{"key": r["key"], "updated_at": r["updated_at"], "expires_at": r["expires_at"]} for r in rows]


MAX_INSPECT = 500


def list_subjects(tenant_id: str, project_id: str) -> List[Dict[str, Any]]:
    """The inspector's user list: each subject with live entries ("" = shared), with its namespaces."""
    live, live_args = _live(_ts())
    conn = get_db_connection()
    try:
        rows = conn.execute(f"SELECT subject, namespace, COUNT(*) AS n, MAX(updated_at) AS last FROM kv_entries "
                            f"WHERE tenant_id = ? AND project_id = ? AND {live} GROUP BY subject, namespace",
                            (tenant_id, project_id, *live_args)).fetchall()
    finally:
        conn.close()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        s = out.setdefault(r["subject"], {"subject": r["subject"], "entries": 0, "namespaces": [], "last_updated": ""})
        s["entries"] += int(r["n"])
        s["namespaces"].append(r["namespace"])
        s["last_updated"] = max(s["last_updated"], r["last"] or "")
    for s in out.values():
        s["namespaces"].sort()
    # Shared first, then the most recently updated users
    users = sorted((s for s in out.values() if s["subject"]), key=lambda s: s["last_updated"], reverse=True)
    return ([out[""]] if "" in out else []) + users


def list_entries(tenant_id: str, project_id: str, subject: str, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
    """One subject's live entries with their values, by namespace and key (at most MAX_INSPECT)."""
    live, live_args = _live(_ts())
    sql = (f"SELECT namespace, key, value, expires_at, created_at, updated_at FROM kv_entries WHERE tenant_id = ? "
           f"AND project_id = ? AND subject = ? AND {live}")
    args: Tuple[Any, ...] = (tenant_id, project_id, subject, *live_args)
    if namespace:
        sql, args = sql + " AND namespace = ?", args + (namespace,)
    conn = get_db_connection()
    try:
        rows = conn.execute(sql + " ORDER BY namespace, key LIMIT ?", (*args, MAX_INSPECT)).fetchall()
    finally:
        conn.close()
    return [{"namespace": r["namespace"], "key": r["key"], "value": json.loads(r["value"]),
             "expires_at": r["expires_at"], "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]


def forget(tenant_id: str, project_id: str, subject: str) -> int:
    """Delete every entry belonging to one end user, in all namespaces."""
    if not subject:
        return 0
    conn = get_db_connection()
    try:
        n = conn.execute("DELETE FROM kv_entries WHERE tenant_id = ? AND project_id = ? AND subject = ?",
                         (tenant_id, project_id, subject)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def purge_expired() -> int:
    conn = get_db_connection()
    try:
        n = conn.execute("DELETE FROM kv_entries WHERE expires_at <= ?", (_ts(),)).rowcount
        conn.commit()
    finally:
        conn.close()
    if n:
        logger.info(f"Purged {n} expired key-value entries")
    return n


@jobs.periodic("kv_store.purge", 3600)
async def _purge() -> None:
    await asyncio.to_thread(purge_expired)
