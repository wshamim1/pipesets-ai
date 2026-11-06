"""
jobs.py — durable background work: a queue in the app database, worked by any number of workers.

Work nobody waits on in a request — scheduled and webhook runs, notifications — is a job: a row
in ``jobs`` with a kind, a JSON payload and a status. Workers in the API process (embedded) or
in their own processes (``python manage.py worker``) claim jobs from the same table, so work
survives restarts and spreads across replicas.

Lifecycle
---------
    queued ──claim──▶ running ──handler returns──▶ done
                         ├──handler raises──▶ queued again after a backoff, or dead after max_attempts
                         └──worker dies─────▶ its lease expires; the next claim retries it (or marks it dead)

``max_attempts`` 0 means retry until it succeeds. Sources that let users choose (schedules,
webhooks) store a number of *retries*; ``attempts_for`` converts it (-1 = until success).

* A claim is a conditional UPDATE on (id, status, attempts), so on every database exactly one
  worker wins a job. ``attempts`` is also the fencing token: a worker that lost its job can't
  complete or fail it afterwards.
* A running job holds a lease (``locked_until``) its worker renews every LEASE_SECONDS / 3.
  A worker that stops renewing (crash, kill, partition) loses the job once the lease expires.
* Handlers may run more than once for one job (a crash after the work, before ``done``).
* Dead jobs stay for the dead-letter view (Automation → Jobs); ``retry`` queues one again,
  ``discard`` drops it. A handler's ``on_dead`` hook runs when a crash used up the last attempt,
  so the source can record the failure.
* Finished jobs are purged after JOB_KEEP_DONE_DAYS, dead ones after JOB_KEEP_DEAD_DAYS.
* ``cancel`` stops a job from any replica: a queued one goes straight to dead; for a running one
  it sets a flag (services/shared_state.py) that its worker checks every CANCEL_POLL_SECONDS, then
  stops the handler and buries the job (its ``on_dead`` hook records "Cancelled").

Periodic work (the scheduler tick, sweepers, purges) registers with ``@periodic`` and runs in one
process of the deployment per period: every process checks a few times a period and the first to
find the turn due takes it (``take_turn`` on a row in ``leases``). ``start_background`` starts
these loops and the embedded worker; ``python manage.py worker`` starts them too.

Env: PIPESETS_WORKER (embedded | external | off; default embedded), WORKER_CONCURRENCY (4),
WORKER_POLL_SECONDS (2), JOB_LEASE_SECONDS (60), JOB_MAX_RETRIES (2; -1 = until success),
JOB_BACKOFF_SECONDS (30; ×4 per retry), JOB_BACKOFF_MAX_SECONDS (3600), JOB_KEEP_DONE_DAYS (7),
JOB_KEEP_DEAD_DAYS (30), CANCEL_POLL_SECONDS (2).
"""

import asyncio
import json
import logging
import os
import random
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set

from db import IntegrityError, get_db_connection

logger = logging.getLogger("pipesets-ai-backend")

STATUSES = ("queued", "running", "done", "dead")


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def lease_seconds() -> float:
    return _env_float("JOB_LEASE_SECONDS", 60)


def worker_mode() -> str:
    """embedded: a worker runs inside each API process (one-box installs, the desktop app).
    external: API processes only enqueue; run ``python manage.py worker`` separately.
    off: nothing works the queue in this process."""
    mode = os.getenv("PIPESETS_WORKER", "embedded").strip().lower()
    return mode if mode in ("embedded", "external", "off") else "embedded"


def _ts(dt: Optional[datetime] = None) -> str:
    """Fixed-width UTC timestamp with microseconds: compares correctly as text."""
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _after(seconds: float) -> str:
    return _ts(datetime.now(timezone.utc) + timedelta(seconds=seconds))


def backoff_seconds(attempts: int) -> float:
    """Delay before retry number ``attempts``: 30 s, 2 min, 8 min … capped at an hour, ±20 % jitter."""
    base = _env_float("JOB_BACKOFF_SECONDS", 30) * 4 ** min(max(0, attempts - 1), 20)
    return min(base, _env_float("JOB_BACKOFF_MAX_SECONDS", 3600)) * random.uniform(0.8, 1.2)


MAX_RETRIES = 10   # the most a user can pick; -1 (until success) has no limit


def default_retries() -> int:
    return max(-1, min(int(os.getenv("JOB_MAX_RETRIES", "2")), MAX_RETRIES))


def attempts_for(retries: Optional[int]) -> int:
    """max_attempts for a number of retries: 2 → 3 attempts; -1 → 0 (until success)."""
    retries = default_retries() if retries is None else retries
    return 0 if retries < 0 else retries + 1


# ── Handlers ──────────────────────────────────────────────────────────────────

@dataclass
class Job:
    id: str
    kind: str
    payload: Dict[str, Any]
    attempts: int           # including the current one
    max_attempts: int
    tenant_id: str = ""
    project_id: str = ""
    abandoned_error: Optional[str] = None   # set when a crash used up the last attempt

    @property
    def final(self) -> bool:
        """No retry follows if this attempt fails."""
        return bool(self.max_attempts) and self.attempts >= self.max_attempts


@dataclass
class Handler:
    fn: Callable[[Dict[str, Any], Job], Awaitable[None]]
    max_attempts: Optional[int]
    on_dead: Optional[Callable[[Dict[str, Any], Job, str], Awaitable[None]]] = None


_handlers: Dict[str, Handler] = {}

# Modules that register handlers and periodic loops; a worker imports them so it knows every kind.
HANDLER_MODULES = ("services.scheduler", "services.webhooks", "services.notifier", "services.gates",
                   "services.audit", "services.shared_state", "services.long_term_memory", "services.kv_store",
                   "services.model_routing", "services.batches")


def handler(kind: str, max_attempts: Optional[int] = None, on_dead=None):
    """Register ``async def fn(payload, job)`` for ``kind``; raising fails the attempt.
    ``max_attempts`` defaults to JOB_MAX_RETRIES + 1 (read when a job is queued);
    ``async def on_dead(payload, job, error)`` runs when a crash used up the last attempt."""
    def register(fn):
        _handlers[kind] = Handler(fn, max_attempts, on_dead)
        return fn
    return register


def load_handlers() -> List[str]:
    import importlib
    for name in HANDLER_MODULES:
        importlib.import_module(name)
    return sorted(_handlers)


# ── Queue operations (sync DB work; call through asyncio.to_thread from async code) ─

def enqueue(kind: str, payload: Dict[str, Any], *, tenant_id: str = "", project_id: str = "",
            dedupe_key: Optional[str] = None, delay_seconds: float = 0, max_attempts: Optional[int] = None,
            conn=None) -> str:
    """Queue a job; returns its id. Pass ``conn`` to queue it in the caller's transaction
    (the caller commits). Workers in this process are woken right away."""
    if max_attempts is None:
        h = _handlers.get(kind)
        max_attempts = h.max_attempts if h and h.max_attempts is not None else attempts_for(None)
    job_id = f"job_{uuid.uuid4().hex}"
    now = _ts()
    own = conn is None
    conn = conn or get_db_connection()
    try:
        conn.execute(
            "INSERT INTO jobs (id, kind, payload, status, attempts, max_attempts, run_after, dedupe_key, "
            "tenant_id, project_id, created_at, updated_at) VALUES (?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, kind, json.dumps(payload), max_attempts, _after(delay_seconds) if delay_seconds else now,
             dedupe_key, tenant_id, project_id, now, now),
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    if own:
        _wake_local_workers()   # with the caller's conn, the caller wakes them after commit
    return job_id


def active_count(dedupe_key: str) -> int:
    """Jobs with this key that are queued or running, on any worker."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE dedupe_key = ? AND status IN ('queued', 'running')",
                           (dedupe_key,)).fetchone()
    finally:
        conn.close()
    return int(row["n"])


def claim(worker_id: str, kinds: Iterable[str]) -> Optional[Job]:
    """Take the next due job of one of ``kinds``: a queued one whose time has come, or a running
    one whose worker stopped renewing its lease. None when there is nothing to do."""
    kinds = tuple(kinds)
    if not kinds:
        return None
    now = _ts()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE ((status = 'queued' AND run_after <= ?) OR (status = 'running' AND locked_until < ?)) "
            f"AND kind IN ({', '.join('?' for _ in kinds)}) ORDER BY run_after, created_at LIMIT 10",
            (now, now, *kinds),
        ).fetchall()
        for row in rows:
            abandoned = row["status"] == "running"
            error = f"Worker {row['locked_by']} stopped before the job finished" if abandoned else row["last_error"]
            # A crash on the last attempt: take the job without a new attempt, so the worker can run
            # the handler's on_dead hook and then mark it dead.
            exhausted = abandoned and bool(row["max_attempts"]) and row["attempts"] >= row["max_attempts"]
            cur = conn.execute(
                "UPDATE jobs SET status = 'running', attempts = ?, locked_by = ?, locked_until = ?, "
                "last_error = ?, updated_at = ? "
                "WHERE id = ? AND status = ? AND attempts = ? AND (status = 'queued' OR locked_until < ?)",
                (row["attempts"] + (0 if exhausted else 1), worker_id, _after(lease_seconds()), error, now,
                 row["id"], row["status"], row["attempts"], now),
            )
            conn.commit()
            if cur.rowcount == 1:
                return Job(id=row["id"], kind=row["kind"], payload=json.loads(row["payload"] or "{}"),
                           attempts=row["attempts"] + (0 if exhausted else 1), max_attempts=row["max_attempts"],
                           tenant_id=row["tenant_id"], project_id=row["project_id"],
                           abandoned_error=error if exhausted else None)
    finally:
        conn.close()
    return None


def _fenced_update(job: Job, worker_id: str, sets: str, params: tuple) -> bool:
    """Update ``job`` only while this worker still holds this attempt of it."""
    conn = get_db_connection()
    try:
        cur = conn.execute(
            f"UPDATE jobs SET {sets}, updated_at = ? WHERE id = ? AND status = 'running' AND attempts = ? AND locked_by = ?",
            (*params, _ts(), job.id, job.attempts, worker_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def heartbeat(job: Job, worker_id: str) -> bool:
    """Renew the lease; False means the job was taken over and this worker must stop."""
    return _fenced_update(job, worker_id, "locked_until = ?", (_after(lease_seconds()),))


def complete(job: Job, worker_id: str) -> bool:
    return _fenced_update(job, worker_id, "status = 'done', locked_by = NULL, locked_until = NULL, finished_at = ?",
                          (_ts(),))


def fail(job: Job, worker_id: str, error: str, dead: bool = False) -> str:
    """Record a failed attempt: queued again after a backoff, or dead (``dead`` forces it).
    Returns the new status."""
    error = error[:2000]
    if job.final or dead:
        ok = _fenced_update(job, worker_id, "status = 'dead', locked_by = NULL, locked_until = NULL, "
                                            "last_error = ?, finished_at = ?", (error, _ts()))
        status = "dead"
    else:
        ok = _fenced_update(job, worker_id, "status = 'queued', locked_by = NULL, locked_until = NULL, "
                                            "last_error = ?, run_after = ?", (error, _after(backoff_seconds(job.attempts))))
        status = "queued"
    if not ok:
        return "lost"
    log = logger.warning if status == "dead" else logger.info
    log(f"Job {job.id} ({job.kind}) attempt {job.attempts}/{job.max_attempts or '∞'} failed → {status}: {error}")
    return status


def retry(job_id: str, tenant_id: str, project_id: str) -> bool:
    """Queue a dead job again with a fresh set of attempts (dead-letter view)."""
    now = _ts()
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "UPDATE jobs SET status = 'queued', attempts = 0, run_after = ?, finished_at = NULL, updated_at = ? "
            "WHERE id = ? AND tenant_id = ? AND project_id = ? AND status = 'dead'",
            (now, now, job_id, tenant_id, project_id),
        )
        conn.commit()
        ok = cur.rowcount == 1
    finally:
        conn.close()
    if ok:
        _wake_local_workers()
    return ok


def discard(job_id: str, tenant_id: str, project_id: str) -> bool:
    """Drop a dead job for good (dead-letter view)."""
    conn = get_db_connection()
    try:
        cur = conn.execute("DELETE FROM jobs WHERE id = ? AND tenant_id = ? AND project_id = ? AND status = 'dead'",
                           (job_id, tenant_id, project_id))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


CANCEL_FLAG_SECONDS = 24 * 3600   # a pending cancel outlives any lease, so a takeover still sees it


def cancel_flag(job_id: str) -> str:
    return f"cancel:job:{job_id}"


def cancel(job_id: str, tenant_id: str, project_id: str, reason: str) -> Optional[Job]:
    """Stop a queued or running job. Returns the job when it was queued (now dead, so the caller
    runs its handler's on_dead), None when it was running (its worker stops it) — raises
    LookupError when there is no queued or running job with that id in the project."""
    from services import shared_state   # lazy: shared_state registers a periodic loop here

    now = _ts()
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ? AND tenant_id = ? AND project_id = ? "
                           "AND status IN ('queued', 'running')", (job_id, tenant_id, project_id)).fetchone()
        if not row:
            raise LookupError(job_id)
        if row["status"] == "queued":
            cur = conn.execute("UPDATE jobs SET status = 'dead', last_error = ?, finished_at = ?, updated_at = ? "
                               "WHERE id = ? AND status = 'queued' AND attempts = ?",
                               (reason[:2000], now, now, job_id, row["attempts"]))
            conn.commit()
            if cur.rowcount == 1:
                return Job(id=row["id"], kind=row["kind"], payload=json.loads(row["payload"] or "{}"),
                           attempts=row["attempts"], max_attempts=row["max_attempts"],
                           tenant_id=row["tenant_id"], project_id=row["project_id"], abandoned_error=reason)
            # claimed meanwhile: cancel it as a running job
    finally:
        conn.close()
    shared_state.set_flag(cancel_flag(job_id), CANCEL_FLAG_SECONDS)
    return None


async def bury_cancelled(job: Job, reason: str) -> None:
    """Run the handler's on_dead for a job cancelled while queued."""
    h = _handlers.get(job.kind)
    if h and h.on_dead:
        try:
            await h.on_dead(job.payload, job, reason)
        except Exception:
            logger.exception(f"on_dead for cancelled job {job.id} ({job.kind}) failed")


def get(job_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_jobs(tenant_id: str, project_id: str, status: str, limit: int = 100) -> List[Dict[str, Any]]:
    """A project's jobs in one status, most recently changed first."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE tenant_id = ? AND project_id = ? AND status = ? ORDER BY updated_at DESC LIMIT ?",
            (tenant_id, project_id, status, limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def counts(tenant_id: str, project_id: str) -> Dict[str, int]:
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs WHERE tenant_id = ? AND project_id = ? "
                            "GROUP BY status", (tenant_id, project_id)).fetchall()
    finally:
        conn.close()
    return {s: 0 for s in STATUSES} | {r["status"]: int(r["n"]) for r in rows}


def purge_finished() -> Dict[str, int]:
    """Delete done jobs older than JOB_KEEP_DONE_DAYS and dead ones older than JOB_KEEP_DEAD_DAYS
    (0 keeps them). Returns {status: jobs deleted}."""
    deleted: Dict[str, int] = {}
    conn = get_db_connection()
    try:
        for status, var, default in (("done", "JOB_KEEP_DONE_DAYS", 7), ("dead", "JOB_KEEP_DEAD_DAYS", 30)):
            days = _env_float(var, default)
            if days > 0:
                cur = conn.execute("DELETE FROM jobs WHERE status = ? AND finished_at < ?",
                                   (status, _after(-days * 86400)))
                deleted[status] = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    if any(deleted.values()):
        logger.info(f"Purged finished jobs: {deleted}")
    return deleted


# ── Leases for singleton loops ────────────────────────────────────────────────

def _take_lease(name: str, holder: str, seconds: float, renew: bool) -> bool:
    now = _ts()
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "UPDATE leases SET holder = ?, expires_at = ? WHERE name = ? AND (expires_at < ?"
            + (" OR holder = ?)" if renew else ")"),
            (holder, _after(seconds), name, now, *((holder,) if renew else ())),
        )
        conn.commit()
        if cur.rowcount == 1:
            return True
        if conn.execute("SELECT 1 FROM leases WHERE name = ?", (name,)).fetchone():
            return False
        try:
            conn.execute("INSERT INTO leases (name, holder, expires_at) VALUES (?, ?, ?)",
                         (name, holder, _after(seconds)))
            conn.commit()
            return True
        except IntegrityError:   # another process inserted it first
            conn.rollback()
            return False
    finally:
        conn.close()


def acquire_lease(name: str, holder: str, seconds: float) -> bool:
    """Take or renew the named lease. True while ``holder`` owns it; it lapses after ``seconds``
    unless renewed, and then any process can take it."""
    return _take_lease(name, holder, seconds, renew=True)


def take_turn(name: str, holder: str, seconds: float) -> bool:
    """True for the first process to ask once the last turn (of any holder) is ``seconds`` old."""
    return _take_lease(name, holder, seconds, renew=False)


def release_lease(name: str, holder: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM leases WHERE name = ? AND holder = ?", (name, holder))
        conn.commit()
    finally:
        conn.close()


# ── Periodic loops ────────────────────────────────────────────────────────────

@dataclass
class Periodic:
    name: str
    seconds: float
    fn: Callable[[], Awaitable[Any]]
    enabled: Callable[[], bool]


_periodic: Dict[str, Periodic] = {}
_process_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


def periodic(name: str, seconds: float, enabled: Callable[[], bool] = lambda: True):
    """Register ``async def fn()`` to run about every ``seconds`` in one process of the
    deployment (see ``every``). ``enabled`` is checked when the loops start."""
    def register(fn):
        _periodic[name] = Periodic(name, seconds, fn, enabled)
        return fn
    return register


async def every(name: str, seconds: float, fn: Callable[[], Awaitable[Any]]) -> None:
    """Run ``fn`` about every ``seconds`` until cancelled, taking turns with the other processes
    (``take_turn``): one of them runs it per period. Checks a few times a period, so a process
    that stops only skips its turn. A run longer than the period may overlap the next one."""
    check = max(0.05, min(seconds / 3, 60))
    while True:
        try:
            if await asyncio.to_thread(take_turn, f"every:{name}", _process_id, seconds):
                await fn()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"Periodic '{name}' failed")
        await asyncio.sleep(check * random.uniform(0.8, 1.2))


@periodic("jobs.purge", 3600)
async def _purge() -> None:
    await asyncio.to_thread(purge_finished)


# ── Worker ────────────────────────────────────────────────────────────────────

_local_workers: Set["Worker"] = set()


def wake_workers() -> None:
    """After committing jobs queued with ``enqueue(conn=...)``."""
    _wake_local_workers()


def _wake_local_workers() -> None:
    """Let workers in this process claim a new job now instead of at their next poll.
    Safe from any thread (enqueue runs in request threads and asyncio.to_thread)."""
    for w in list(_local_workers):
        w.wake()


class Worker:
    """Claims jobs and runs their handlers, at most ``concurrency`` at a time."""

    def __init__(self, concurrency: Optional[int] = None, kinds: Optional[Iterable[str]] = None,
                 poll_seconds: Optional[float] = None, worker_id: Optional[str] = None):
        self.id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.concurrency = concurrency or int(os.getenv("WORKER_CONCURRENCY", "4"))
        self.poll_seconds = poll_seconds if poll_seconds is not None else _env_float("WORKER_POLL_SECONDS", 2)
        self._kinds = tuple(kinds) if kinds is not None else None
        self._tasks: Set[asyncio.Task] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._wake: Optional[asyncio.Event] = None
        self._stopping = False
        self._cancelled: Dict[str, str] = {}   # job id -> reason, for jobs stopped by a cancel

    @property
    def kinds(self) -> tuple:
        return self._kinds if self._kinds is not None else tuple(_handlers)

    def wake(self) -> None:
        if self._loop and self._wake and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._wake.set)

    async def _fill(self) -> int:
        """Claim jobs until every slot is busy or nothing is due; returns how many started."""
        started = 0
        while not self._stopping and len(self._tasks) < self.concurrency:
            job = await asyncio.to_thread(claim, self.id, self.kinds)
            if job is None:
                break
            task = asyncio.create_task(self._run_job(job), name=f"job:{job.id}")
            self._tasks.add(task)
            task.add_done_callback(self._job_done)
            started += 1
        return started

    def _job_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if self._wake:
            self._wake.set()   # a slot is free

    async def _run_job(self, job: Job) -> None:
        h = _handlers[job.kind]
        if job.abandoned_error is not None:
            await self._bury(job, h)
            return
        from services import telemetry

        work = asyncio.current_task()
        beat = asyncio.create_task(self._heartbeat(job, work))
        t0, outcome = time.monotonic(), "lost"
        try:
            with telemetry.job_span(job):
                await h.fn(job.payload, job)
        except asyncio.CancelledError:
            reason = self._cancelled.pop(job.id, None)
            if reason is None:
                # Shutting down, or the job was taken over: leave the row as it is. Its lease
                # expires and the next claim retries it.
                raise
            work.uncancel()
            await self._bury(job, h, reason)
            outcome = "cancelled"
        except Exception as e:  # noqa: BLE001 — any handler error fails this attempt
            logger.exception(f"Job {job.id} ({job.kind}) raised")
            status = await asyncio.to_thread(fail, job, self.id, f"{type(e).__name__}: {e}")
            outcome = {"queued": "retry", "dead": "dead"}.get(status, "lost")
        else:
            if await asyncio.to_thread(complete, job, self.id):
                outcome = "done"
            else:
                logger.warning(f"Job {job.id} finished after its lease was taken over; outcome not recorded")
        finally:
            beat.cancel()
            telemetry.record_job(job.kind, outcome, time.monotonic() - t0)

    async def _bury(self, job: Job, h: Handler, reason: Optional[str] = None) -> None:
        """A crash used up the job's last attempt, or it was cancelled: let the source record it,
        then mark it dead."""
        error = reason or job.abandoned_error or "Worker stopped before the job finished"
        if h.on_dead:
            try:
                await h.on_dead(job.payload, job, error)
            except Exception:
                logger.exception(f"on_dead for job {job.id} ({job.kind}) failed")
        await asyncio.to_thread(fail, job, self.id, error, reason is not None)
        if reason is not None:
            from services import shared_state
            await asyncio.to_thread(shared_state.clear_flag, cancel_flag(job.id))

    async def _heartbeat(self, job: Job, work: Optional[asyncio.Task]) -> None:
        """Renew the lease every lease / 3; between renewals, check for a cancel."""
        from services import shared_state

        renew_every = lease_seconds() / 3
        poll = min(renew_every, _env_float("CANCEL_POLL_SECONDS", 2))
        last = asyncio.get_running_loop().time()
        while True:
            await asyncio.sleep(poll)
            if await asyncio.to_thread(shared_state.has_flag, cancel_flag(job.id)):
                logger.info(f"Job {job.id} ({job.kind}) cancelled")
                self._cancelled[job.id] = "Cancelled"
                if work:
                    work.cancel()
                return
            if asyncio.get_running_loop().time() - last < renew_every:
                continue
            last = asyncio.get_running_loop().time()
            if not await asyncio.to_thread(heartbeat, job, self.id):
                logger.warning(f"Lost the lease on job {job.id}; stopping it here")
                if work:
                    work.cancel()
                return

    def _start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        _local_workers.add(self)

    async def run(self) -> None:
        """Work the queue until ``stop``."""
        self._start()
        logger.info(f"Worker {self.id} started ({self.concurrency} slots; kinds: {', '.join(self.kinds) or 'none'})")
        try:
            while not self._stopping:
                self._wake.clear()
                try:
                    await self._fill()
                except Exception:
                    logger.exception("Worker poll failed")
                try:
                    await asyncio.wait_for(self._wake.wait(), self.poll_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            _local_workers.discard(self)

    async def drain(self) -> None:
        """Run until nothing is due and nothing is running (tests, ``manage.py worker --once``)."""
        self._start()
        try:
            while True:
                await self._fill()
                if not self._tasks:
                    return
                await asyncio.wait(set(self._tasks), return_when=asyncio.FIRST_COMPLETED)
        finally:
            _local_workers.discard(self)

    async def stop(self, grace_seconds: float = 10) -> None:
        """Stop claiming; give running jobs ``grace_seconds`` to finish, then cancel them
        (they are retried elsewhere once their leases expire)."""
        self._stopping = True
        if self._wake:
            self._wake.set()
        if self._tasks:
            _, pending = await asyncio.wait(set(self._tasks), timeout=grace_seconds)
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


# ── Background work in this process ──────────────────────────────────────────

_embedded: Optional[Worker] = None
_embedded_task: Optional[asyncio.Task] = None
_periodic_tasks: List[asyncio.Task] = []


def start_periodic() -> List[str]:
    """Start every enabled periodic loop; returns their names."""
    load_handlers()
    names = [p.name for p in _periodic.values() if p.enabled()]
    for name in names:
        p = _periodic[name]
        _periodic_tasks.append(asyncio.create_task(every(p.name, p.seconds, p.fn), name=f"every:{name}"))
    return names


async def stop_periodic() -> None:
    for t in _periodic_tasks:
        t.cancel()
    await asyncio.gather(*_periodic_tasks, return_exceptions=True)
    _periodic_tasks.clear()


def start_background() -> None:
    """In the API process: periodic loops, and a worker unless PIPESETS_WORKER=external / off."""
    global _embedded, _embedded_task
    logger.info(f"Periodic loops: {', '.join(start_periodic()) or 'none'}")
    if worker_mode() != "embedded":
        logger.info(f"Embedded worker off (PIPESETS_WORKER={worker_mode()})")
        return
    _embedded = Worker()
    _embedded_task = asyncio.create_task(_embedded.run())


async def stop_background() -> None:
    global _embedded, _embedded_task
    await stop_periodic()
    if _embedded and _embedded_task:
        await _embedded.stop()
        _embedded_task.cancel()
        await asyncio.gather(_embedded_task, return_exceptions=True)
    _embedded, _embedded_task = None, None
