"""
webhooks.py — run published pipelines when an outside system calls a URL.

Each webhook has a secret URL token (``POST /v1/hooks/{token}``). Only its SHA-256 hash is
stored; the token is shown once at creation or rotation. Optionally the webhook also has a
signing secret, and then every call must carry an HMAC-SHA256 of the raw body in
``X-Hub-Signature-256`` (GitHub's header) or ``X-Pipesets-Signature``, as ``sha256=<hex>``.
The signing secret is stored sealed (``enc://``, see services/secret_store.py).

Prompt template
---------------
The run's prompt is the webhook's ``prompt_template`` with placeholders filled from the call:

  {{body}}               the whole body (pretty-printed when it is JSON)
  {{body.a.b}}           a field of a JSON body; list items by index ({{body.commits.0.message}})
  {{query.x}}            a query-string parameter

Missing fields render as empty text. A template that renders empty is rejected (422).

Run behaviour matches schedules (see services/scheduler.py): the latest published version
runs as the webhook's owner (who last saved it), so ACLs, budgets and middleware apply, and
failed / paused runs go to notification channels. Calls are accepted with 202 and queued as a
job (kind ``webhook.run``); failed or crashed runs are retried ``retries`` times, as for
schedules. At most MAX_INFLIGHT runs per webhook are queued or running at once, across all
replicas (more get 429).

Env: WEBHOOK_MAX_INFLIGHT (5), WEBHOOK_MAX_BODY_BYTES (262144).
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import uuid
from typing import Any, Dict, Mapping, Optional

from db import get_db_connection
from services import jobs, notifier, scheduler

logger = logging.getLogger("pipesets-ai-backend")

TOKEN_PREFIX = "whk_"
MAX_INFLIGHT = int(os.getenv("WEBHOOK_MAX_INFLIGHT", "5"))
MAX_BODY_BYTES = int(os.getenv("WEBHOOK_MAX_BODY_BYTES", str(256 * 1024)))
PREVIEW_CHARS = 2000
SIGNATURE_HEADERS = ("x-hub-signature-256", "x-pipesets-signature", "x-uaf-signature")  # x-uaf-*: pre-rename senders
DEFAULT_TEMPLATE = "{{body}}"
JOB_KIND = "webhook.run"

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][\w\-]*(?:\.[\w\-]+)*)\s*\}\}")


# ── Tokens + signatures ───────────────────────────────────────────────────────

def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def signature_ok(secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
    expected = sign(secret, body)
    for h in SIGNATURE_HEADERS:
        got = headers.get(h)
        if got and hmac.compare_digest(got.strip(), expected):
            return True
    return False


# ── Prompt template ───────────────────────────────────────────────────────────

def parse_body(raw: bytes) -> Any:
    """The body as JSON when it parses, else as text."""
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text) if text.strip() else ""
    except json.JSONDecodeError:
        return text


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, indent=2, ensure_ascii=False)
    return str(v)


def _lookup(root: Any, path: list) -> Any:
    cur = root
    for part in path:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def render_prompt(template: str, body: Any, query: Mapping[str, str]) -> str:
    def repl(m: "re.Match[str]") -> str:
        head, *rest = m.group(1).split(".")
        if head == "body":
            return _as_text(_lookup(body, rest))
        if head == "query" and len(rest) == 1:
            return query.get(rest[0], "")
        return m.group(0)   # unknown placeholder: leave it visible
    return _PLACEHOLDER.sub(repl, template or DEFAULT_TEMPLATE).strip()


# ── Run bookkeeping ───────────────────────────────────────────────────────────

def find_by_token(token: str) -> Optional[Dict[str, Any]]:
    if not token.startswith(TOKEN_PREFIX):
        return None
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM webhooks WHERE token_hash = ?", (hash_token(token),)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def dedupe_key(webhook_id: str) -> str:
    return f"webhook:{webhook_id}"


def launch(hook: Dict[str, Any], trigger: str, prompt: str, payload_preview: str) -> str:
    """Record a call and queue its job, in one transaction; returns the webhook_runs id.
    Callers check ``inflight`` against MAX_INFLIGHT first. ``hook["owner_user_id"]`` is who
    the run acts as."""
    run_row_id = f"whrun_{uuid.uuid4().hex[:12]}"
    now = scheduler.now_iso()
    conn = get_db_connection()
    try:
        job_id = jobs.enqueue(
            JOB_KIND, {"webhook_id": hook["id"], "run_row_id": run_row_id, "prompt": prompt,
                       "owner_user_id": hook["owner_user_id"]},
            tenant_id=hook["tenant_id"], project_id=hook["project_id"], dedupe_key=dedupe_key(hook["id"]),
            max_attempts=jobs.attempts_for(hook.get("retries")), conn=conn,
        )
        conn.execute(
            "INSERT INTO webhook_runs (id, webhook_id, tenant_id, project_id, app_id, trigger, status, job_id, "
            "payload_preview, started_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
            (run_row_id, hook["id"], hook["tenant_id"], hook["project_id"], hook["app_id"], trigger, job_id,
             payload_preview[:PREVIEW_CHARS] or None, now),
        )
        conn.execute("UPDATE webhooks SET last_triggered_at = ? WHERE id = ?", (now, hook["id"]))
        conn.commit()
    finally:
        conn.close()
    jobs.wake_workers()
    return run_row_id


def _finish_run(hook: Dict[str, Any], run_row_id: str, version: int, res: Dict[str, Any]) -> None:
    status, error = res["status"], res.get("error")
    meta = res.get("meta") or {}
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE webhook_runs SET status = ?, app_version = ?, run_id = ?, output_preview = ?, error = ?, "
            "latency_ms = ?, cost_usd = ?, finished_at = ? WHERE id = ?",
            (status, version, res.get("run_id"), (res.get("output") or "")[:PREVIEW_CHARS] or None, error,
             int(res.get("latency_ms") or 0), float(meta.get("cost_usd") or 0.0), scheduler.now_iso(), run_row_id),
        )
        conn.execute("UPDATE webhooks SET last_status = ?, last_error = ? WHERE id = ?",
                     (status, error if status == "failed" else None, hook["id"]))
        conn.commit()
    finally:
        conn.close()


def _load(webhook_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


# ── Execution ─────────────────────────────────────────────────────────────────

def inflight(webhook_id: str) -> int:
    """Calls of this webhook queued, running or waiting to retry, on any worker."""
    return jobs.active_count(dedupe_key(webhook_id))


async def _record(hook: Dict[str, Any], run_row_id: str, version: int, res: Dict[str, Any]) -> None:
    await asyncio.to_thread(_finish_run, hook, run_row_id, version, res)
    await asyncio.to_thread(notifier.notify_run_outcome, "webhook", hook, version, res)


async def _on_dead(payload: Dict[str, Any], job: jobs.Job, error: str) -> None:
    hook = await asyncio.to_thread(_load, payload["webhook_id"])
    if hook:
        await _record(hook, payload["run_row_id"], 0, scheduler.crashed_result(error))


@jobs.handler(JOB_KIND, on_dead=_on_dead)
async def _run_job(payload: Dict[str, Any], job: jobs.Job) -> None:
    """One attempt of one call; retried like a schedule's (see scheduler._run_job)."""
    hook = await asyncio.to_thread(_load, payload["webhook_id"])
    if hook is None:
        return   # deleted since it was called
    hook["owner_user_id"] = payload.get("owner_user_id") or hook["owner_user_id"]
    version, res = await scheduler.run_attempt("webhook_runs", hook, payload["run_row_id"], payload["prompt"], job)
    await _record(hook, payload["run_row_id"], version, res)
    if scheduler.retryable(res):
        raise scheduler.RunFailed(res.get("error") or "Run failed")
