"""
notifier.py — tell people when an unattended run needs attention.

Scheduled and webhook-triggered runs have nobody watching them, so their outcomes are
sent to the project's notification channels (``notification_channels`` table):

  run.failed             a run errored, timed out or was blocked by a budget / middleware
  run.paused             a Master Agent run stopped at a Human Gate and waits for approval
  gate.escalated         a Human Gate's review timed out with on_timeout=escalate (services/gates.py)
  schedule.auto_paused   a schedule turned itself off after max_failures failures in a row

Channel kinds
-------------
* ``slack``   — Slack incoming-webhook URL; receives ``{"text": ...}``.
* ``webhook`` — any HTTPS endpoint; receives the JSON event (``event``, ``data``, ``sent_at``).

URLs are credentials (a Slack webhook URL is enough to post), so they are stored sealed.

Each delivery — one event to one channel — is a job (kind ``notify.deliver``): a failed POST
is retried with backoff (JOB_MAX_RETRIES), then the job goes to the dead-letter view. The last
outcome is stored on the channel (last_sent_at / last_error) so the UI can show a broken URL.
Notifications never block or fail the run that caused them.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from db import get_db_connection
from services import jobs, secret_store
from services.scheduler import now_iso

logger = logging.getLogger("pipesets-ai-backend")

EVENTS = ("run.failed", "run.paused", "gate.escalated", "schedule.auto_paused")
TIMEOUT_SECONDS = 10.0
JOB_KIND = "notify.deliver"


def _channels_for(tenant_id: str, project_id: str, app_id: Optional[str], event: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM notification_channels WHERE tenant_id = ? AND project_id = ? AND enabled = 1 "
            "AND (app_id IS NULL OR app_id = ?)",
            (tenant_id, project_id, app_id or ""),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            events = json.loads(r["events"] or "[]")
        except json.JSONDecodeError:
            events = []
        if event in events:
            out.append(dict(r))
    return out


def _record(channel_id: str, error: Optional[str]) -> None:
    conn = get_db_connection()
    try:
        conn.execute("UPDATE notification_channels SET last_sent_at = ?, last_error = ? WHERE id = ?",
                     (now_iso(), error, channel_id))
        conn.commit()
    finally:
        conn.close()


def slack_text(event: str, data: Dict[str, Any]) -> str:
    """One readable Slack message for an event."""
    source = f"{data.get('source', 'run')} “{data.get('source_name') or data.get('source_id') or '?'}”"
    app = data.get("app_name") or data.get("app_id") or "pipeline"
    version = f" v{data['app_version']}" if data.get("app_version") else ""
    if event == "run.failed":
        head = f":x: *{app}*{version} failed ({source})"
    elif event == "run.paused":
        head = f":raised_hand: *{app}*{version} is waiting for approval at a Human Gate ({source})"
    elif event == "gate.escalated":
        head = f":rotating_light: *{app}*{version}: review at a Human Gate timed out and needs a reviewer ({source})"
    elif event == "schedule.auto_paused":
        head = f":double_vertical_bar: Schedule “{data.get('source_name')}” for *{app}* was paused after repeated failures"
    elif event == "test":
        head = ":white_check_mark: Test notification from Pipesets AI"
    else:
        head = f"{event}: *{app}*"
    lines = [head]
    if data.get("error"):
        lines.append(f"> {str(data['error'])[:500]}")
    gate = data.get("pending_gate") or {}
    if isinstance(gate, dict) and (gate.get("label") or gate.get("message")):
        lines.append(f"> Gate: {gate.get('label') or gate.get('message')}")
    if data.get("run_id"):
        lines.append(f"Run id: `{data['run_id']}`")
    return "\n".join(lines)


async def deliver(channel: Dict[str, Any], event: str, data: Dict[str, Any]) -> Optional[str]:
    """POST one event to one channel. Returns an error message, or None on success."""
    if channel["kind"] == "slack":
        payload: Dict[str, Any] = {"text": slack_text(event, data)}
    else:
        payload = {"event": event, "data": data, "sent_at": now_iso()}
    error: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            r = await client.post(secret_store.open_sealed(channel["url"]), json=payload,
                                  headers={"User-Agent": "pipesets-ai/notifier"})
        if r.status_code >= 400:
            error = f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    if error:
        logger.warning(f"Notification '{event}' to channel {channel['id']} failed: {error}")
    await asyncio.to_thread(_record, channel["id"], error)
    return error


class DeliveryFailed(Exception):
    """The channel refused or didn't answer; the job is retried."""


def _channel(channel_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM notification_channels WHERE id = ?", (channel_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


@jobs.handler(JOB_KIND)
async def _deliver_job(payload: Dict[str, Any], job: jobs.Job) -> None:
    channel = await asyncio.to_thread(_channel, payload["channel_id"])
    if not channel or not channel["enabled"]:
        return   # deleted or turned off since
    error = await deliver(channel, payload["event"], payload["data"])
    if error:
        raise DeliveryFailed(error)


def queue_event(event: str, tenant_id: str, project_id: str, app_id: Optional[str], data: Dict[str, Any]) -> int:
    """Queue one delivery job per channel that wants ``event``; returns how many. Never raises."""
    try:
        channels = _channels_for(tenant_id, project_id, app_id, event)
        for ch in channels:
            jobs.enqueue(JOB_KIND, {"channel_id": ch["id"], "event": event, "data": data},
                         tenant_id=tenant_id, project_id=project_id)
        return len(channels)
    except Exception:
        logger.exception(f"Queueing notification '{event}' failed")
        return 0


def notify_run_outcome(source: str, source_row: Dict[str, Any], version: int, res: Dict[str, Any]) -> None:
    """Map a finished unattended run to run.failed / run.paused (completed runs send nothing).
    Sync DB work: call through asyncio.to_thread from async code."""
    status = res.get("status")
    event = {"failed": "run.failed", "paused": "run.paused"}.get(status or "")
    if not event:
        return
    queue_event(event, source_row["tenant_id"], source_row["project_id"], source_row["app_id"], {
        "source": source, "source_id": source_row["id"], "source_name": source_row.get("name"),
        "app_id": source_row["app_id"], "app_name": res.get("app_name"), "app_version": version or None,
        "status": status, "run_id": res.get("run_id"), "error": res.get("error"),
        "pending_gate": res.get("pending_gate"),
        "output_preview": (res.get("output") or "")[:500] or None,
    })
