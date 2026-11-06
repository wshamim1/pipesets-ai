"""
Shared state across replicas (services/shared_state.py): the same contract on every backend —
memory, database, and redis when TEST_REDIS_URL is set — limits and lockouts that hold across
processes, and cancel signals that stop jobs and Master Agent runs wherever they run.
"""

import asyncio
import os
import time

import pytest

from helpers import hdr
from services import api_keys, jobs, shared_state
from services.request_context import RequestContext

REDIS_URL = os.getenv("TEST_REDIS_URL")


def _backends():
    yield pytest.param(shared_state.MemoryStore, id="memory")
    yield pytest.param(shared_state.DatabaseStore, id="database")
    yield pytest.param(lambda: shared_state.RedisStore(REDIS_URL, prefix="pipesets-test:"), id="redis",
                       marks=pytest.mark.skipif(not REDIS_URL, reason="TEST_REDIS_URL not set"))


@pytest.fixture(params=list(_backends()))
def store(request):
    s = request.param()
    s.clear()
    yield s
    s.clear()


@pytest.fixture
def backend(env):
    """Use the database backend app-wide for one test (what a multi-replica install runs)."""
    shared_state.use(shared_state.DatabaseStore())
    shared_state.store().clear()
    yield shared_state.store()
    shared_state.store().clear()
    shared_state.use(None)


# ── The contract ──────────────────────────────────────────────────────────────

def test_a_limit_refuses_without_counting(store):
    assert [store.add("k", 60, 2).allowed for _ in range(3)] == [True, True, False]
    refused = store.add("k", 60, 2)
    assert refused.count == 2 and 1 <= refused.retry_after <= 61, "refused hits aren't recorded"
    assert store.peek("k", 60).count == 2


def test_without_a_limit_every_hit_counts(store):
    assert [store.add("u", 60).count for _ in range(3)] == [1, 2, 3]
    assert all(store.add("u", 60).allowed for _ in range(2))


def test_windows_slide_and_reset(store):
    store.add("w", 0.3)
    store.add("w", 0.3)
    time.sleep(0.35)
    assert store.peek("w", 0.3).count == 0, "old hits fall out of the window"
    store.add("r", 60)
    store.reset("r")
    assert store.peek("r", 60).count == 0
    assert store.peek("other", 60).count == 0


def test_flags_expire(store):
    assert not store.has_flag("f")
    store.set_flag("f", 0.3)
    store.set_flag("f", 0.3)   # setting twice is fine
    assert store.has_flag("f")
    time.sleep(0.35)
    assert not store.has_flag("f")
    store.set_flag("g", 60)
    store.clear_flag("g")
    assert not store.has_flag("g")
    store.purge()


def test_database_and_redis_are_shared_between_processes():
    """Two store objects stand in for two replicas."""
    a, b = shared_state.DatabaseStore(), shared_state.DatabaseStore()
    a.clear()
    assert a.add("shared", 60, 2).allowed and b.add("shared", 60, 2).allowed
    assert not a.add("shared", 60, 2).allowed, "the second replica's hit counted"
    b.set_flag("cancel:x", 60)
    assert a.has_flag("cancel:x")
    a.clear()


def test_backend_selection(env):
    env.delenv("REDIS_URL", raising=False)
    env.delenv("PIPESETS_SHARED_STATE", raising=False)
    assert shared_state.backend_name() == "memory"
    env.setenv("REDIS_URL", "redis://localhost:6379/0")
    assert shared_state.backend_name() == "redis", "auto picks redis when it's configured"
    env.setenv("PIPESETS_SHARED_STATE", "database")
    assert shared_state.backend_name() == "database"
    env.setenv("PIPESETS_SHARED_STATE", "carrier-pigeon")
    with pytest.raises(ValueError):
        shared_state.backend_name()
    env.delenv("PIPESETS_SHARED_STATE")
    env.delenv("REDIS_URL")


# ── Limits that hold across replicas ──────────────────────────────────────────

def test_an_api_key_limit_counts_every_replica(client, backend):
    key, rec = api_keys.create_key(RequestContext(tenant_id="tenant_demo", project_id="proj_research",
                                                  user_id="user_admin"), "shared", rate_limit_rpm=2)
    other_replica = shared_state.DatabaseStore()
    other_replica.add(f"rl:key:{rec['id']}", 60, 2)   # one request served elsewhere
    auth = {"Authorization": f"Bearer {key}"}
    assert client.get("/v1/apps", headers=auth).status_code == 200
    r = client.get("/v1/apps", headers=auth)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_a_login_lockout_counts_every_replica(client, backend):
    other_replica = shared_state.DatabaseStore()
    for _ in range(10):
        other_replica.add("login:locked@example.com", 15 * 60)
    r = client.post("/api/auth/login", json={"email": "locked@example.com", "password": "whatever-123"})
    assert r.status_code == 429


# ── Cancelling jobs ───────────────────────────────────────────────────────────

buried = []


async def _record_burial(payload, job, error):
    buried.append((payload["n"], error))


@jobs.handler("test.long", on_dead=_record_burial)
async def _long(payload, job):
    await asyncio.sleep(payload.get("sleep", 10))


@pytest.fixture
def fast_cancel(env):
    env.setenv("CANCEL_POLL_SECONDS", "0.05")
    buried.clear()


def test_a_queued_job_is_cancelled_at_once(client, fast_cancel):
    job_id = jobs.enqueue("test.long", {"n": 1}, tenant_id="tenant_demo", project_id="proj_research",
                          delay_seconds=3600)
    r = client.post(f"/api/jobs/{job_id}/cancel", headers=hdr())
    assert r.status_code == 200 and r.json()["status"] == "dead"
    job = jobs.get(job_id)
    assert job["status"] == "dead" and job["last_error"] == "Cancelled by user_admin"
    assert buried == [(1, "Cancelled by user_admin")], "the source records it as cancelled"
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=hdr()).status_code == 409, "already dead"


def test_a_running_job_is_stopped_by_its_worker(fast_cancel):
    job_id = jobs.enqueue("test.long", {"n": 2}, tenant_id="tenant_demo", project_id="proj_research")

    async def go():
        w = jobs.Worker(kinds=["test.long"])
        run = asyncio.create_task(w.drain())
        while jobs.get(job_id)["status"] != "running":
            await asyncio.sleep(0.02)
        t0 = time.monotonic()
        assert await asyncio.to_thread(jobs.cancel, job_id, "tenant_demo", "proj_research", "x") is None
        await asyncio.wait_for(run, 5)
        return time.monotonic() - t0

    took = asyncio.run(go())
    assert took < 2, f"stopped in {took:.2f}s, not after the 10 s handler"
    job = jobs.get(job_id)
    assert job["status"] == "dead" and job["last_error"] == "Cancelled"
    assert buried == [(2, "Cancelled")]
    assert not shared_state.has_flag(jobs.cancel_flag(job_id)), "flag cleared once handled"


# ── Cancelling Master Agent runs ──────────────────────────────────────────────

def test_a_running_agent_run_is_cancelled_by_request(client, env, fast_cancel):
    from routers import agents
    from routers.agents import MasterAgentRunRequest, request_cancel, run_master

    async def slow_steps(req, cp, record_goal):
        await asyncio.sleep(10)

    env.setattr(agents, "_execute_master", slow_steps)
    ctx = RequestContext(tenant_id="tenant_demo", project_id="proj_research", user_id="user_admin")

    async def go():
        req = MasterAgentRunRequest(goal="take your time", run_id="run-cancel-me", provider="mock", model="mock-gpt-4")
        run = asyncio.create_task(run_master(req, ctx))
        await asyncio.sleep(0.1)
        assert await asyncio.to_thread(request_cancel, "run-cancel-me", "tenant_demo", "proj_research") == "cancelling"
        return await asyncio.wait_for(run, 5)

    res = asyncio.run(go())
    assert res.status == "cancelled" and res.error == "Cancelled by request"
    row = client.get("/api/agents/runs/run-cancel-me", headers=hdr()).json()
    assert row["status"] == "cancelled" and not row["resumable"]
    assert not shared_state.has_flag(agents.cancel_flag("run-cancel-me"))


def test_cancel_endpoints(client):
    assert client.post("/api/agents/runs/nope/cancel", headers=hdr()).status_code == 404
    assert client.post("/api/agents/runs/run-cancel-me/cancel", headers=hdr()).status_code == 409, "finished"
    key, _ = api_keys.create_key(RequestContext(tenant_id="tenant_demo", project_id="proj_research",
                                                user_id="user_admin"), "cancel", rate_limit_rpm=0)
    r = client.post("/v1/runs/nope/cancel", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 404
