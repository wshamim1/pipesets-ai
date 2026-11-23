"""
audit_stream.py — stream a workspace's audit log to its own systems (SIEM / log platform).

A tenant adds sinks in Settings → Audit log → Streaming:

* ``webhook``    — POST a JSON batch ``{"source", "tenant_id", "events": [...]}``. With a secret, the body is
                   signed: ``X-Pipesets-Signature: sha256=<hex HMAC-SHA256 of the body>``.
* ``splunk_hec`` — Splunk HTTP Event Collector (``…/services/collector/event``), ``Authorization: Splunk <token>``,
                   one ``{"time", "source", "sourcetype": "pipesets:audit", "event"}`` object per entry.
* ``datadog``    — Datadog Logs intake (``https://http-intake.logs.<site>/api/v2/logs``), ``DD-API-KEY``.

Delivery is at-least-once and in order. Each sink keeps a cursor — the (created_at, id) of the last entry it
delivered — and a periodic loop (``audit.stream``, every AUDIT_STREAM_INTERVAL_SECONDS, 10 by default) sends
what came after it, up to BATCH entries per round. A failed POST leaves the cursor where it was and retries
with exponential backoff (up to an hour), so an outage at the receiver loses nothing. Entries younger than
LAG_SECONDS wait one round, so one written late by another replica isn't skipped.

URL and token are sealed; every URL passes the outbound SSRF guard (EXTERNAL_AGENT_ALLOWED_HOSTS lets a
private Splunk through). Receivers should de-duplicate on the entry ``id``.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from db import get_db_connection
from services import jobs, secret_store
from services.external_agent import validate_endpoint

log = logging.getLogger(__name__)

KINDS = {"webhook": "Webhook (JSON)", "splunk_hec": "Splunk HEC", "datadog": "Datadog Logs"}
DATADOG_DEFAULT = "https://http-intake.logs.datadoghq.com/api/v2/logs"
BATCH = 500
LAG_SECONDS = 5
MAX_BACKOFF = 3600
TIMEOUT = 15.0
FIELDS = ("id", "created_at", "actor", "action", "target_id", "outcome", "status", "method", "path", "project_id", "ip")


class SinkError(ValueError):
    """Bad sink settings; the message is for the user."""


def interval() -> float:
    return float(os.getenv("AUDIT_STREAM_INTERVAL_SECONDS", "10"))


def _now() -> datetime:
    return datetime.utcnow()


# ── Sinks ─────────────────────────────────────────────────────────────────────

def _public(row) -> Dict[str, Any]:
    url = secret_store.open_sealed(row["url"]) or ""
    u = urlparse(url)
    return {"id": row["id"], "name": row["name"], "kind": row["kind"], "kind_label": KINDS.get(row["kind"], row["kind"]),
            "url": f"{u.scheme}://{u.netloc}{u.path}" if u.netloc else "",   # no query string: it may hold a key
            "token_set": bool(row["token"]), "enabled": bool(row["enabled"]), "delivered": row["delivered"],
            "last_delivered_at": row["last_delivered_at"], "last_error": row["last_error"],
            "failures": row["failures"], "next_attempt_at": row["next_attempt_at"] or None,
            "cursor_at": row["cursor_at"] or None, "created_at": row["created_at"], "updated_at": row["updated_at"]}


def _check_url(kind: str, url: str) -> str:
    url = (url or "").strip() or (DATADOG_DEFAULT if kind == "datadog" else "")
    u = urlparse(url)
    local = u.hostname in ("localhost", "127.0.0.1")
    if not u.netloc or u.scheme not in ("https", "http") or (u.scheme == "http" and not local):
        raise SinkError("The URL must be https:// (http only for localhost).")
    return url


def list_sinks(tenant_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        return [_public(r) for r in conn.execute("SELECT * FROM audit_sinks WHERE tenant_id = ? ORDER BY created_at",
                                                 (tenant_id,)).fetchall()]
    finally:
        conn.close()


def _row(conn, sink_id: str, tenant_id: str):
    return conn.execute("SELECT * FROM audit_sinks WHERE id = ? AND tenant_id = ?", (sink_id, tenant_id)).fetchone()


def create_sink(tenant_id: str, user_id: str, name: str, kind: str, url: str, token: str = "",
                start: str = "now") -> Dict[str, Any]:
    if kind not in KINDS:
        raise SinkError(f"kind must be one of {', '.join(KINDS)}.")
    if kind in ("splunk_hec", "datadog") and not token.strip():
        raise SinkError("Enter the " + ("HEC token." if kind == "splunk_hec" else "Datadog API key."))
    if start not in ("now", "all"):
        raise SinkError("start must be now or all.")
    url = _check_url(kind, url)
    now = _now().isoformat()
    sink_id = f"sink_{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        cursor = ("", "")
        if start == "now":    # only what happens from now on
            last = conn.execute("SELECT created_at, id FROM audit_log WHERE tenant_id = ? "
                                "ORDER BY created_at DESC, id DESC LIMIT 1", (tenant_id,)).fetchone()
            cursor = (last["created_at"], last["id"]) if last else ("", "")
        conn.execute(
            "INSERT INTO audit_sinks (id, tenant_id, name, kind, url, token, enabled, cursor_at, cursor_id, "
            "created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
            (sink_id, tenant_id, (name or KINDS[kind]).strip()[:200], kind, secret_store.seal(url, tenant_id),
             secret_store.seal(token.strip(), tenant_id) if token.strip() else "", cursor[0], cursor[1],
             user_id, now, now))
        conn.commit()
        return _public(_row(conn, sink_id, tenant_id))
    finally:
        conn.close()


def update_sink(sink_id: str, tenant_id: str, name: Optional[str] = None, url: Optional[str] = None,
                token: Optional[str] = None, enabled: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = _row(conn, sink_id, tenant_id)
        if not row:
            return None
        sets: Dict[str, Any] = {}
        if name is not None and name.strip():
            sets["name"] = name.strip()[:200]
        if url is not None and url.strip():
            sets["url"] = secret_store.seal(_check_url(row["kind"], url), tenant_id)
        if token is not None and token.strip():
            sets["token"] = secret_store.seal(token.strip(), tenant_id)
        if enabled is not None:
            sets["enabled"] = 1 if enabled else 0
            if enabled:          # resuming: try now
                sets.update(failures=0, next_attempt_at="", last_error="")
        sets["updated_at"] = _now().isoformat()
        conn.execute(f"UPDATE audit_sinks SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                     (*sets.values(), sink_id))
        conn.commit()
        return _public(_row(conn, sink_id, tenant_id))
    finally:
        conn.close()


def delete_sink(sink_id: str, tenant_id: str) -> bool:
    conn = get_db_connection()
    try:
        n = conn.execute("DELETE FROM audit_sinks WHERE id = ? AND tenant_id = ?", (sink_id, tenant_id)).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


# ── Formats ───────────────────────────────────────────────────────────────────

def _epoch(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()   # stored as naive UTC
    except ValueError:
        return 0.0


def build_request(kind: str, url: str, token: str, tenant_id: str,
                  events: List[Dict[str, Any]]) -> Tuple[str, bytes, Dict[str, str]]:
    """(url, body, headers) for one batch."""
    events = [{**e, "tenant_id": tenant_id} for e in events]
    headers = {"User-Agent": "Pipesets-Audit-Stream/1"}
    if kind == "splunk_hec":
        body = "\n".join(json.dumps({"time": _epoch(e["created_at"]), "source": "pipesets", "sourcetype": "pipesets:audit",
                                     "event": e}) for e in events).encode()
        headers.update({"Authorization": f"Splunk {token}", "Content-Type": "application/json"})
    elif kind == "datadog":
        body = json.dumps([{"ddsource": "pipesets", "service": "pipesets", "ddtags": f"tenant:{tenant_id},kind:audit",
                            "message": f"{e['action']} {e['outcome']} by {e['actor'] or 'system'}", **e}
                           for e in events]).encode()
        headers.update({"DD-API-KEY": token, "Content-Type": "application/json"})
    else:
        body = json.dumps({"source": "pipesets", "type": "audit", "tenant_id": tenant_id, "events": events}).encode()
        headers["Content-Type"] = "application/json"
        if token:
            headers["X-Pipesets-Signature"] = "sha256=" + hmac.new(token.encode(), body, hashlib.sha256).hexdigest()
    return url, body, headers


async def _post(url: str, body: bytes, headers: Dict[str, str]) -> None:
    try:
        await validate_endpoint(url)
    except ValueError as e:
        raise RuntimeError(str(e))
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
        r = await client.post(url, content=body, headers=headers)
    if not 200 <= r.status_code < 300:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")


# ── Delivery ──────────────────────────────────────────────────────────────────

def _pending(conn, row) -> List[Dict[str, Any]]:
    until = (_now() - timedelta(seconds=LAG_SECONDS)).isoformat()
    rows = conn.execute(
        f"SELECT {', '.join(FIELDS)} FROM audit_log WHERE tenant_id = ? AND created_at <= ? "
        "AND (created_at > ? OR (created_at = ? AND id > ?)) ORDER BY created_at, id LIMIT ?",
        (row["tenant_id"], until, row["cursor_at"], row["cursor_at"], row["cursor_id"], BATCH)).fetchall()
    return [dict(r) for r in rows]


async def deliver(sink_id: str) -> int:
    """Send one batch for a sink; returns how many entries were delivered (0 when nothing was due)."""
    def load():
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT * FROM audit_sinks WHERE id = ?", (sink_id,)).fetchone()
            return (dict(row), _pending(conn, row)) if row else (None, [])
        finally:
            conn.close()

    row, events = await asyncio.to_thread(load)
    if not row or not events:
        return 0
    url = secret_store.unseal(row["url"])
    token = secret_store.unseal(row["token"]) if row["token"] else ""
    now = _now()
    try:
        await _post(*build_request(row["kind"], url, token, row["tenant_id"], events))
    except Exception as e:
        failures = row["failures"] + 1
        retry = now + timedelta(seconds=min(10 * 2 ** (failures - 1), MAX_BACKOFF))
        await asyncio.to_thread(_save, sink_id, {"failures": failures, "next_attempt_at": retry.isoformat(),
                                                 "last_error": f"{now.isoformat()[:19]}Z {type(e).__name__}: {e}"[:500]})
        log.warning("Audit sink %s failed (%d in a row): %s", sink_id, failures, e)
        return 0
    last = events[-1]
    # Only move forward from the cursor this batch started at (a concurrent round can't move it back)
    await asyncio.to_thread(_save, sink_id, {"cursor_at": last["created_at"], "cursor_id": last["id"],
                                             "failures": 0, "next_attempt_at": "", "last_error": "",
                                             "last_delivered_at": now.isoformat(),
                                             "delivered": row["delivered"] + len(events)},
                            (row["cursor_at"], row["cursor_id"]))
    return len(events)


def _save(sink_id: str, fields: Dict[str, Any], expect_cursor: Optional[Tuple[str, str]] = None) -> None:
    conn = get_db_connection()
    try:
        where, args = "id = ?", [sink_id]
        if expect_cursor:
            where += " AND cursor_at = ? AND cursor_id = ?"
            args += list(expect_cursor)
        conn.execute(f"UPDATE audit_sinks SET {', '.join(f'{k} = ?' for k in fields)} WHERE {where}",
                     (*fields.values(), *args))
        conn.commit()
    finally:
        conn.close()


async def deliver_due() -> int:
    """One round over every enabled sink whose backoff has passed (the periodic loop)."""
    def due():
        conn = get_db_connection()
        try:
            return [r[0] for r in conn.execute("SELECT id FROM audit_sinks WHERE enabled = 1 AND "
                                               "(next_attempt_at = '' OR next_attempt_at <= ?)",
                                               (_now().isoformat(),)).fetchall()]
        finally:
            conn.close()

    total = 0
    for sink_id in await asyncio.to_thread(due):
        try:
            # Drain the backlog a few batches per round, then let other work run
            for _ in range(10):
                n = await deliver(sink_id)
                total += n
                if n < BATCH:
                    break
        except Exception:
            log.exception("Audit sink %s round failed", sink_id)
    return total


async def send_test(sink_id: str, tenant_id: str, user_id: str) -> Dict[str, Any]:
    """POST one synthetic ``audit_sink.test`` event; doesn't move the cursor."""
    conn = get_db_connection()
    try:
        row = _row(conn, sink_id, tenant_id)
    finally:
        conn.close()
    if not row:
        raise LookupError("Sink not found")
    event = {"id": f"test_{uuid.uuid4().hex[:12]}", "created_at": _now().isoformat(), "actor": user_id,
             "action": "audit_sink.test", "target_id": sink_id, "outcome": "success", "status": 200, "method": "POST",
             "path": f"/api/audit-log/sinks/{sink_id}/test", "project_id": "", "ip": ""}
    try:
        await _post(*build_request(row["kind"], secret_store.unseal(row["url"]),
                                   secret_store.unseal(row["token"]) if row["token"] else "", tenant_id, [event]))
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"[:300]}
    return {"ok": True, "detail": f"Delivered a test event to {KINDS[row['kind']]}."}


@jobs.periodic("audit.stream", interval())
async def _stream() -> None:
    await deliver_due()
