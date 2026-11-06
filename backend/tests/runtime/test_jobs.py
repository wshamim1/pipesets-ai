"""
The durable job queue (services/jobs.py): claims, retries, leases, crash recovery.

Workers here are driven with ``drain`` or ``claim`` directly; nothing starts the app's lifespan.
Runs against SQLite, and Postgres when TEST_DATABASE_URL is set (CI's postgres leg).
"""

import asyncio
import time
from collections import Counter

import pytest

from db import get_db_connection
from services import jobs

ran: Counter = Counter()
failures_left: Counter = Counter()


@jobs.handler("test.ok")
async def _ok(payload, job):
    ran[payload["n"]] += 1


@jobs.handler("test.flaky", max_attempts=3)
async def _flaky(payload, job):
    ran[payload["n"]] += 1
    if failures_left[payload["n"]] > 0:
        failures_left[payload["n"]] -= 1
        raise RuntimeError(f"boom {job.attempts}")


@jobs.handler("test.slow")
async def _slow(payload, job):
    ran[payload["n"]] += 1
    await asyncio.sleep(payload.get("sleep", 0.05))


buried = []


@jobs.handler("test.buried", on_dead=lambda payload, job, error: _bury(payload, error))
async def _never_finishes(payload, job):
    ran[payload["n"]] += 1


async def _bury(payload, error):
    buried.append((payload["n"], error))


@pytest.fixture(autouse=True)
def _fast(env):
    env.setenv("JOB_BACKOFF_SECONDS", "0")
    ran.clear()
    failures_left.clear()
    buried.clear()
    conn = get_db_connection()
    conn.execute("DELETE FROM jobs")
    conn.execute("DELETE FROM leases")
    conn.commit()
    conn.close()


def _drain(*workers):
    async def go():
        await asyncio.gather(*(w.drain() for w in workers))
    asyncio.run(go())


def test_a_job_runs_once_and_is_done():
    job_id = jobs.enqueue("test.ok", {"n": 1}, tenant_id="t", project_id="p")
    _drain(jobs.Worker(kinds=["test.ok"]))
    row = jobs.get(job_id)
    assert ran[1] == 1 and row["status"] == "done" and row["attempts"] == 1 and row["finished_at"]
    assert row["locked_by"] is None and row["locked_until"] is None


def test_failures_are_retried_with_backoff_then_succeed(env):
    failures_left[2] = 2
    job_id = jobs.enqueue("test.flaky", {"n": 2})
    _drain(jobs.Worker(kinds=["test.flaky"]))
    row = jobs.get(job_id)
    assert ran[2] == 3 and row["status"] == "done" and row["attempts"] == 3
    assert "boom 2" in row["last_error"], "the last failure stays visible"


def test_backoff_delays_the_retry(env):
    env.setenv("JOB_BACKOFF_SECONDS", "60")
    failures_left[3] = 1
    job_id = jobs.enqueue("test.flaky", {"n": 3})
    _drain(jobs.Worker(kinds=["test.flaky"]))
    row = jobs.get(job_id)
    assert ran[3] == 1 and row["status"] == "queued" and row["run_after"] > jobs._after(40)
    assert jobs.claim("w", ["test.flaky"]) is None, "not due yet"
    env.setenv("JOB_BACKOFF_SECONDS", "0")


def test_exhausted_attempts_make_a_dead_job_that_retry_revives():
    failures_left[4] = 3
    job_id = jobs.enqueue("test.flaky", {"n": 4}, tenant_id="t", project_id="p")
    _drain(jobs.Worker(kinds=["test.flaky"]))
    row = jobs.get(job_id)
    assert ran[4] == 3 and row["status"] == "dead" and "boom 3" in row["last_error"]

    assert not jobs.retry(job_id, "t", "other-project"), "scoped to its project"
    assert jobs.retry(job_id, "t", "p")
    _drain(jobs.Worker(kinds=["test.flaky"]))
    row = jobs.get(job_id)
    assert ran[4] == 4 and row["status"] == "done" and row["attempts"] == 1


def test_competing_workers_run_each_job_exactly_once():
    ids = [jobs.enqueue("test.slow", {"n": i, "sleep": 0.01}) for i in range(40)]
    _drain(*(jobs.Worker(kinds=["test.slow"], concurrency=3, worker_id=f"w{i}") for i in range(4)))
    assert set(ran) == set(range(40)) and set(ran.values()) == {1}
    assert {jobs.get(i)["status"] for i in ids} == {"done"}


def test_a_dead_workers_job_is_taken_over_after_its_lease(env):
    env.setenv("JOB_LEASE_SECONDS", "0.3")
    job_id = jobs.enqueue("test.ok", {"n": 5})
    crashed = jobs.claim("crashed-worker", ["test.ok"])   # claimed, then the worker "dies"
    assert crashed and crashed.attempts == 1
    assert jobs.claim("w2", ["test.ok"]) is None, "still leased"
    time.sleep(0.4)
    _drain(jobs.Worker(kinds=["test.ok"], worker_id="w2"))
    row = jobs.get(job_id)
    assert ran[5] == 1 and row["status"] == "done" and row["attempts"] == 2
    assert "crashed-worker stopped" in row["last_error"]
    assert not jobs.complete(crashed, "crashed-worker"), "the old attempt can't overwrite the outcome"
    env.setenv("JOB_LEASE_SECONDS", "60")


def test_a_crash_on_the_last_attempt_makes_it_dead_and_tells_the_source(env):
    env.setenv("JOB_LEASE_SECONDS", "0.2")
    job_id = jobs.enqueue("test.buried", {"n": 6}, max_attempts=2)
    for worker in ("w1", "w2"):
        assert jobs.claim(worker, ["test.buried"]) is not None
        time.sleep(0.3)
    _drain(jobs.Worker(kinds=["test.buried"], worker_id="w3"))
    row = jobs.get(job_id)
    assert row["status"] == "dead" and row["attempts"] == 2 and "w2 stopped" in row["last_error"]
    assert ran[6] == 0, "not run a third time"
    assert buried == [(6, row["last_error"])], "on_dead hook ran once"
    env.setenv("JOB_LEASE_SECONDS", "60")


def test_zero_max_attempts_retries_until_it_succeeds():
    failures_left[14] = 7
    job_id = jobs.enqueue("test.flaky", {"n": 14}, max_attempts=0)
    _drain(jobs.Worker(kinds=["test.flaky"]))
    row = jobs.get(job_id)
    assert ran[14] == 8 and row["status"] == "done" and row["attempts"] == 8


def test_retry_settings(env):
    assert jobs.attempts_for(0) == 1 and jobs.attempts_for(3) == 4 and jobs.attempts_for(-1) == 0
    env.setenv("JOB_MAX_RETRIES", "5")
    assert jobs.attempts_for(None) == 6
    assert jobs.get(jobs.enqueue("test.ok", {"n": 15}))["max_attempts"] == 6, "server default when queued"
    env.setenv("JOB_MAX_RETRIES", "2")
    env.setenv("JOB_BACKOFF_SECONDS", "30")
    assert 24 <= jobs.backoff_seconds(1) <= 36 and 96 <= jobs.backoff_seconds(2) <= 144
    assert jobs.backoff_seconds(50) <= 3600 * 1.2, "capped (JOB_BACKOFF_MAX_SECONDS)"
    env.setenv("JOB_BACKOFF_SECONDS", "0")


def test_heartbeats_keep_a_long_job_leased(env):
    env.setenv("JOB_LEASE_SECONDS", "0.3")
    jobs.enqueue("test.slow", {"n": 7, "sleep": 0.8})

    async def go():
        a = jobs.Worker(kinds=["test.slow"], worker_id="a")
        task = asyncio.create_task(a.drain())
        await asyncio.sleep(0.5)                 # past one lease length
        assert await asyncio.to_thread(jobs.claim, "b", ["test.slow"]) is None, "renewed, not abandoned"
        await task
    asyncio.run(go())
    assert ran[7] == 1
    env.setenv("JOB_LEASE_SECONDS", "60")


def test_a_worker_that_loses_its_lease_stops_the_job(env):
    env.setenv("JOB_LEASE_SECONDS", "0.3")
    job_id = jobs.enqueue("test.slow", {"n": 8, "sleep": 2})

    async def go():
        a = jobs.Worker(kinds=["test.slow"], worker_id="a")
        task = asyncio.create_task(a.drain())
        await asyncio.sleep(0.05)
        conn = get_db_connection()   # another worker took it over (e.g. after a long GC pause)
        conn.execute("UPDATE jobs SET locked_by = 'b', attempts = attempts + 1 WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        await asyncio.wait_for(task, 1.5)
    asyncio.run(go())
    assert jobs.get(job_id)["locked_by"] == "b", "a's cancelled attempt left b's claim alone"
    env.setenv("JOB_LEASE_SECONDS", "60")


def test_stop_leaves_unfinished_jobs_for_another_worker():
    job_id = jobs.enqueue("test.slow", {"n": 9, "sleep": 5})

    async def go():
        w = jobs.Worker(kinds=["test.slow"])
        task = asyncio.create_task(w.run())
        await asyncio.sleep(0.2)
        await w.stop(grace_seconds=0.1)
        await asyncio.wait_for(task, 2)
    asyncio.run(go())
    assert jobs.get(job_id)["status"] == "running", "left for lease expiry, not marked done or failed"


def test_enqueue_in_the_callers_transaction_rolls_back_with_it():
    conn = get_db_connection()
    job_id = jobs.enqueue("test.ok", {"n": 10}, conn=conn)
    conn.rollback()
    conn.close()
    assert jobs.get(job_id) is None


def test_dedupe_key_counts_queued_and_running_only():
    a = jobs.enqueue("test.ok", {"n": 11}, dedupe_key="schedule:s1")
    jobs.enqueue("test.ok", {"n": 12}, dedupe_key="schedule:s2")
    assert jobs.active_count("schedule:s1") == 1
    _drain(jobs.Worker(kinds=["test.ok"]))
    assert jobs.get(a)["status"] == "done" and jobs.active_count("schedule:s1") == 0


def test_a_worker_only_claims_its_kinds():
    job_id = jobs.enqueue("test.ok", {"n": 13})
    _drain(jobs.Worker(kinds=["test.flaky"]))
    assert jobs.get(job_id)["status"] == "queued"


def test_a_lease_has_one_holder_at_a_time():
    assert jobs.acquire_lease("scheduler", "a", 0.3)
    assert not jobs.acquire_lease("scheduler", "b", 0.3)
    assert jobs.acquire_lease("scheduler", "a", 0.3), "the holder renews"
    time.sleep(0.4)
    assert jobs.acquire_lease("scheduler", "b", 0.3), "lapsed, so b takes it"
    assert not jobs.acquire_lease("scheduler", "a", 0.3)
    jobs.release_lease("scheduler", "b")
    assert jobs.acquire_lease("scheduler", "a", 0.3)
