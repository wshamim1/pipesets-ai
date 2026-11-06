"""
scheduler.py — run published pipelines on a cron schedule.

A periodic loop (services/jobs.py ``@periodic``: one process of the deployment per turn) polls
the ``schedules`` table every POLL_SECONDS. A due schedule is also claimed with a conditional
UPDATE on ``next_run_at``, so even overlapping ticks fire it exactly once. Missed firings
(server was down) run once on the next tick, not once per missed slot.

Run behaviour
-------------
* Runs go through the same path as ``POST /v1/apps/{id}/run`` (non-streaming) and act
  as the schedule's owner — the user who last saved it — so ACLs, budgets and
  middleware nodes all apply as usual.
* Each run uses the pipeline's latest *published* version (its snapshot), so a draft
  being edited never runs and never breaks the schedule.
* Provider keys: node-level keys on the flow, then the server's environment
  (OPENAI_API_KEY, ...). There is no browser to forward keys from.
* Each firing is a job (services/jobs.py, kind ``schedule.run``), so it survives restarts and
  any worker can run it. A firing is skipped while the schedule's previous one is still queued,
  running or waiting to retry — on any replica.
* A failed or crashed run is retried ``retries`` times with backoff (-1 = until it succeeds).
  Not retried: runs refused by a guardrail or budget, rejected at a Human Gate, or that can't
  start (pipeline unpublished, deleted, nothing to run) — a retry can't fix those.
* At most MAX_CONCURRENT runs execute at once per process (plus the worker's own limit).
* After ``max_failures`` failed firings in a row the schedule pauses itself (0 = never); a
  firing counts once, after its last attempt.
* Failed and Human-Gate-paused runs, and auto-pauses, are sent to the project's
  notification channels (services/notifier.py).

Env: SCHEDULER_ENABLED (default true), SCHEDULER_POLL_SECONDS (30),
SCHEDULER_MAX_CONCURRENT (3), SCHEDULER_MIN_INTERVAL_SECONDS (300).
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from db import get_db_connection
from services import jobs

logger = logging.getLogger("pipesets-ai-backend")

POLL_SECONDS = float(os.getenv("SCHEDULER_POLL_SECONDS", "30"))
MAX_CONCURRENT = int(os.getenv("SCHEDULER_MAX_CONCURRENT", "3"))
MIN_INTERVAL_SECONDS = int(os.getenv("SCHEDULER_MIN_INTERVAL_SECONDS", "300"))
PREVIEW_CHARS = 2000
JOB_KIND = "schedule.run"

# A failed run with one of these errors was refused, not broken: retrying can't help.
_PERMANENT_ERRORS = ("[Guardrail", "Blocked by guardrail", "Budget exceeded", "Rejected at human gate",
                     "can't pause inside a nested pipeline", "Prompt cannot be empty")

_semaphore: Optional[asyncio.Semaphore] = None


def scheduler_enabled() -> bool:
    return os.getenv("SCHEDULER_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


# ── Time + cron helpers ───────────────────────────────────────────────────────

def utc_iso(dt: datetime) -> str:
    """UTC timestamp that sorts correctly as text and parses as UTC in browsers."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return utc_iso(datetime.now(timezone.utc))


def next_runs(cron: str, tz: str, count: int = 1, after: Optional[datetime] = None) -> List[datetime]:
    """The next ``count`` firings of ``cron`` evaluated in timezone ``tz``."""
    base = (after or datetime.now(timezone.utc)).astimezone(ZoneInfo(tz))
    it = croniter(cron, base)
    return [it.get_next(datetime) for _ in range(count)]


def validate_schedule(cron: str, tz: str) -> None:
    """Raise ValueError with a user-facing message when cron or timezone is unusable."""
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown timezone '{tz}' — use an IANA name like 'UTC' or 'Europe/London'")
    if len(cron.split()) != 5 or not croniter.is_valid(cron):
        raise ValueError(f"Invalid cron expression '{cron}' — expected 5 fields: minute hour day month weekday")
    # Sample a window of firings: catches "*/1 * * * *" and lists like "0,1 * * * *".
    times = next_runs(cron, tz, 12)
    gap = min((b - a).total_seconds() for a, b in zip(times, times[1:]))
    if gap < MIN_INTERVAL_SECONDS:
        raise ValueError(f"Runs at most every {MIN_INTERVAL_SECONDS // 60} minutes — this cron fires every {int(gap // 60) or '<1'} min")


def next_run_iso(cron: str, tz: str) -> str:
    return utc_iso(next_runs(cron, tz, 1)[0])


# ── Run bookkeeping (sync DB work) ────────────────────────────────────────────

def _insert_run(sched: Dict[str, Any], trigger: str, status: str = "running", error: Optional[str] = None) -> str:
    run_row_id = f"srun_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO schedule_runs (id, schedule_id, tenant_id, project_id, app_id, trigger, status, error, "
            "started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_row_id, sched["id"], sched["tenant_id"], sched["project_id"], sched["app_id"], trigger, status,
             error, now, None if status == "running" else now),
        )
        conn.commit()
    finally:
        conn.close()
    return run_row_id


def _finish_run(sched: Dict[str, Any], run_row_id: str, version: int, res: Dict[str, Any]) -> bool:
    """Record the outcome; returns True when this failure auto-paused the schedule."""
    status, error = res["status"], res.get("error")
    auto_paused = False
    meta = res.get("meta") or {}
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE schedule_runs SET status = ?, app_version = ?, run_id = ?, output_preview = ?, error = ?, "
            "latency_ms = ?, cost_usd = ?, finished_at = ? WHERE id = ?",
            (status, version, res.get("run_id"), (res.get("output") or "")[:PREVIEW_CHARS] or None, error,
             int(res.get("latency_ms") or 0), float(meta.get("cost_usd") or 0.0), now_iso(), run_row_id),
        )
        if status == "failed":
            conn.execute(
                "UPDATE schedules SET consecutive_failures = consecutive_failures + 1, last_status = ?, last_error = ? "
                "WHERE id = ?", (status, error, sched["id"]),
            )
            row = conn.execute("SELECT consecutive_failures, max_failures FROM schedules WHERE id = ?",
                               (sched["id"],)).fetchone()
            if row and row["max_failures"] and row["consecutive_failures"] >= row["max_failures"]:
                conn.execute(
                    "UPDATE schedules SET enabled = 0, next_run_at = NULL, last_error = ? WHERE id = ?",
                    (f"Paused after {row['consecutive_failures']} failed runs in a row. Last error: {error}", sched["id"]),
                )
                logger.warning(f"Schedule {sched['id']} paused after {row['consecutive_failures']} failures")
                auto_paused = True
        else:
            conn.execute(
                "UPDATE schedules SET consecutive_failures = 0, last_status = ?, last_error = NULL WHERE id = ?",
                (status, sched["id"]),
            )
        conn.commit()
    finally:
        conn.close()
    return auto_paused


def _published_version(source: Dict[str, Any]) -> int:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT version FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (source["app_id"], source["tenant_id"], source["project_id"]),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise LookupError("Pipeline no longer exists")
    if not row["version"]:
        raise ValueError("Pipeline has never been published — publish it to run it automatically")
    return int(row["version"])


def mark_orphaned_runs(table: str) -> int:
    """Close run rows (schedule_runs / webhook_runs) that no job will ever finish: rows from before
    runs were jobs, or whose job was deleted. Rows with a live job are left to it, so this is safe
    with other replicas running."""
    conn = get_db_connection()
    try:
        cur = conn.execute(
            f"UPDATE {table} SET status = 'interrupted', error = 'Server stopped before the run finished', "
            "finished_at = ? WHERE status IN ('queued', 'running', 'retrying') AND (job_id IS NULL OR job_id NOT IN "
            "(SELECT id FROM jobs WHERE status IN ('queued', 'running')))", (now_iso(),),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def mark_interrupted_runs() -> int:
    return mark_orphaned_runs("schedule_runs")


def _set_run(table: str, run_row_id: str, **fields: Any) -> None:
    conn = get_db_connection()
    try:
        conn.execute(f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                     (*fields.values(), run_row_id))
        conn.commit()
    finally:
        conn.close()


# ── Execution ─────────────────────────────────────────────────────────────────

async def run_published(source: Dict[str, Any], prompt: str, timeout_ms: int,
                        run_id: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    """Run the latest published version of ``source["app_id"]`` as ``source["owner_user_id"]``.

    Shared by schedules and webhooks. Returns (version, result) in the shape of
    routers.v1._collect; never raises — errors come back as status "failed". The run is
    checkpointed under ``run_id``; when an earlier attempt with that id stopped part-way, this
    one resumes it, so finished model and tool calls aren't repeated.
    """
    from routers.v1 import V1RunRequest, _collect, _provider_keys, _run_events  # lazy: routers import services
    from services.pipeline_runner import RunScope, _load_published_app

    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    res: Dict[str, Any] = {"status": "failed", "error": None, "output": "", "meta": {}, "latency_ms": 0}
    version = 0
    try:
        scope = RunScope(tenant_id=source["tenant_id"], project_id=source["project_id"],
                         user_id=source["owner_user_id"],
                         provider_keys=_provider_keys({}, (source["tenant_id"], source["project_id"])),
                         batch=source.get("batch_name") or "")
        version = await asyncio.to_thread(_published_version, source)
        app = await asyncio.to_thread(_load_published_app, source["app_id"], scope, version)
        types = {n.get("type") for n in app["flow"].get("nodes", [])}
        if not types & {"llm", "master_agent"}:
            raise ValueError(f"Pipeline '{app['name']}' has no LLM or Master Agent node to run")
        body = V1RunRequest(prompt=prompt, stream=False, timeout_ms=int(timeout_ms))
        async with _semaphore:
            res = await _collect(app, _run_events(app, body, scope, run_id), body.timeout_ms)
    except (LookupError, ValueError, PermissionError) as e:   # unpublished, deleted, nothing to run, no access
        logger.warning(f"Automated run of {source['app_id']} ({source['id']}) can't start: {e}")
        res["error"], res["permanent"] = str(e), True
    except Exception as e:
        logger.warning(f"Automated run of {source['app_id']} ({source['id']}) failed: {e}")
        res["error"] = str(e)
    return version, res


class RunFailed(Exception):
    """A run failed in a way a retry may fix. Raised from a job handler so the queue retries it."""


def retryable(res: Dict[str, Any]) -> bool:
    if res.get("status") != "failed" or res.get("permanent"):
        return False
    return not any(marker in (res.get("error") or "") for marker in _PERMANENT_ERRORS)


async def run_attempt(table: str, source: Dict[str, Any], run_row_id: str, prompt: str,
                      job: jobs.Job) -> Tuple[int, Dict[str, Any]]:
    """One attempt of a schedule / webhook run. A failure a retry may fix, with attempts left,
    marks the run row 'retrying' and raises RunFailed; otherwise returns (version, result)
    for the caller to record."""
    await asyncio.to_thread(_set_run, table, run_row_id, status="running", attempts=job.attempts)
    version, res = await run_published(source, prompt, source["timeout_ms"], run_id=run_row_id)
    if retryable(res) and not job.final:
        await asyncio.to_thread(_set_run, table, run_row_id, status="retrying", error=res.get("error"),
                                latency_ms=int(res.get("latency_ms") or 0))
        raise RunFailed(res.get("error") or "Run failed")
    return version, res


def crashed_result(error: str) -> Dict[str, Any]:
    """The outcome to record when a crash used up a run's last attempt."""
    return {"status": "failed", "error": error, "output": "", "meta": {}, "latency_ms": 0}


def _load(schedule_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


async def _record(sched: Dict[str, Any], run_row_id: str, version: int, res: Dict[str, Any]) -> None:
    """Record a firing's final outcome and queue its notifications."""
    from services import notifier

    auto_paused = await asyncio.to_thread(_finish_run, sched, run_row_id, version, res)
    await asyncio.to_thread(notifier.notify_run_outcome, "schedule", sched, version, res)
    if auto_paused:
        await asyncio.to_thread(
            notifier.queue_event, "schedule.auto_paused", sched["tenant_id"], sched["project_id"], sched["app_id"], {
                "source": "schedule", "source_id": sched["id"], "source_name": sched.get("name"),
                "app_id": sched["app_id"], "app_name": res.get("app_name"), "error": res.get("error"),
            })


async def _on_dead(payload: Dict[str, Any], job: jobs.Job, error: str) -> None:
    sched = await asyncio.to_thread(_load, payload["schedule_id"])
    if sched:
        await _record(sched, payload["run_row_id"], 0, crashed_result(error))


@jobs.handler(JOB_KIND, on_dead=_on_dead)
async def _run_job(payload: Dict[str, Any], job: jobs.Job) -> None:
    """One attempt of one firing. Raises RunFailed when it should be retried, or — on the last
    attempt — after recording the failure, so the job ends up in the dead-letter view."""
    sched = await asyncio.to_thread(_load, payload["schedule_id"])
    if sched is None:
        return   # deleted since it was queued
    sched["owner_user_id"] = payload.get("owner_user_id") or sched["owner_user_id"]
    version, res = await run_attempt("schedule_runs", sched, payload["run_row_id"], sched["prompt"], job)
    await _record(sched, payload["run_row_id"], version, res)
    if retryable(res):
        raise RunFailed(res.get("error") or "Run failed")


def dedupe_key(schedule_id: str) -> str:
    return f"schedule:{schedule_id}"


def is_running(schedule_id: str) -> bool:
    """A firing of this schedule is queued, running or waiting to retry, on any worker."""
    return jobs.active_count(dedupe_key(schedule_id)) > 0


def launch(sched: Dict[str, Any], trigger: str) -> str:
    """Record a firing and queue its job, in one transaction; returns the schedule_runs id.
    ``sched["owner_user_id"]`` is who the run acts as."""
    run_row_id = f"srun_{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        job_id = jobs.enqueue(
            JOB_KIND, {"schedule_id": sched["id"], "run_row_id": run_row_id, "owner_user_id": sched["owner_user_id"]},
            tenant_id=sched["tenant_id"], project_id=sched["project_id"], dedupe_key=dedupe_key(sched["id"]),
            max_attempts=jobs.attempts_for(sched.get("retries")), conn=conn,
        )
        conn.execute(
            "INSERT INTO schedule_runs (id, schedule_id, tenant_id, project_id, app_id, trigger, status, job_id, "
            "started_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
            (run_row_id, sched["id"], sched["tenant_id"], sched["project_id"], sched["app_id"], trigger, job_id,
             now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    jobs.wake_workers()
    return run_row_id


# ── Polling loop ──────────────────────────────────────────────────────────────

def _claim_due() -> List[Tuple[Dict[str, Any], bool]]:
    """Claim every due schedule by advancing its next_run_at. Returns [(schedule, overlaps)]."""
    now = datetime.now(timezone.utc)
    conn = get_db_connection()
    claimed: List[Tuple[Dict[str, Any], bool]] = []
    try:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ? "
            "ORDER BY next_run_at", (utc_iso(now),),
        ).fetchall()
        for row in rows:
            sched = dict(row)
            try:
                nxt: Optional[str] = utc_iso(next_runs(sched["cron"], sched["timezone"], 1, now)[0])
                enabled = 1
            except Exception as e:   # cron/timezone made invalid outside the API
                nxt, enabled = None, 0
                sched["_error"] = f"Paused: invalid schedule ({e})"
            cur = conn.execute(
                "UPDATE schedules SET next_run_at = ?, last_run_at = ?, enabled = ? "
                "WHERE id = ? AND enabled = 1 AND next_run_at = ?",
                (nxt, utc_iso(now), enabled, sched["id"], sched["next_run_at"]),
            )
            conn.commit()
            if cur.rowcount != 1:
                continue   # another replica claimed it, or it was edited meanwhile
            if not enabled:
                conn.execute("UPDATE schedules SET last_status = 'failed', last_error = ? WHERE id = ?",
                             (sched["_error"], sched["id"]))
                conn.commit()
                continue
            claimed.append((sched, is_running(sched["id"])))
    finally:
        conn.close()
    return claimed


@jobs.periodic("scheduler.tick", POLL_SECONDS, enabled=scheduler_enabled)
async def _tick() -> None:
    for sched, overlaps in await asyncio.to_thread(_claim_due):
        if overlaps:
            await asyncio.to_thread(_insert_run, sched, "schedule", "skipped", "Previous run still in progress")
            continue
        await asyncio.to_thread(launch, sched, "schedule")


@jobs.periodic("runs.orphans", 300)
async def _close_orphaned_runs() -> None:
    for table in ("schedule_runs", "webhook_runs"):
        await asyncio.to_thread(mark_orphaned_runs, table)
