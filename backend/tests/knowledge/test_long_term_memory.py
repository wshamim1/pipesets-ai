"""
Conversation memory scoped by tenant / project, and long-term memory (services/long_term_memory.py):
the opt-in, extraction (rules and model) with PII redaction, recall into later sessions, the
inspector API — and the C1 exit criterion: an agent recalls a preference stated in an earlier session.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from db import get_db_connection
from helpers import hdr, run_jobs
from services import api_keys, jobs, llm_runner
from services import long_term_memory as ltm
from services.request_context import RequestContext

sent = []   # the messages each model call received, newest last


class _Usage:
    def as_dict(self):
        return {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


class _Chunk:
    def __init__(self, text):
        self.text, self.tool_calls, self.thinking_blocks, self.finish_reason = text, [], [], None


class _FakeStream:
    """A local model: answers "ok" and records what it was sent."""
    usage, cost_usd, backend = _Usage(), 0.0, "fake"

    async def __aiter__(self):
        yield _Chunk("ok")


@pytest.fixture(scope="module", autouse=True)
def _fake_model(env):
    async def start(cfg, messages, tools=None, tool_choice=None):
        sent.append(messages)
        return _FakeStream(), cfg, 1, False

    async def no_model(*a, **kw):
        return None   # as without a reachable model: the rules read the turn
    env.setattr(llm_runner, "_start_stream_with_policy", start)
    env.setattr(ltm, "model_facts", no_model)


def _flow(long_term=True, **memory):
    return {"nodes": [{"id": "llm", "type": "llm", "data": {"label": "a", "provider": "ollama", "model": "llama3"}},
                      {"id": "mem", "type": "memory", "data": {"label": "m", "strategy": "sliding_window",
                                                               "token_budget": 4000, "session_id": "default",
                                                               "long_term": long_term, **memory}}],
            "edges": [{"id": "e", "source": "mem", "target": "llm"}]}


@pytest.fixture(scope="module")
def app_id(client):
    aid = client.post("/api/apps", headers=hdr(), json={"name": "Remembers", "description": "",
                                                        "flow_data": _flow()}).json()["id"]
    assert client.post(f"/api/apps/{aid}/publish", headers=hdr()).status_code == 200
    return aid


@pytest.fixture(scope="module")
def key():
    plaintext, _ = api_keys.create_key(RequestContext(tenant_id="tenant_demo", project_id="proj_research",
                                                      user_id="user_admin"), "ltm", rate_limit_rpm=0)
    return plaintext


def _ask(client, key, app_id, prompt, session, user=None):
    body = {"prompt": prompt, "stream": False, "session_id": session, **({"user": user} if user else {})}
    r = client.post(f"/v1/apps/{app_id}/run", json=body, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    return " ".join(str(m.get("content")) for m in sent[-1])   # what the model was sent


def _turn_on(client, on=True):
    r = client.put("/api/memory/long-term/settings", headers=hdr(), json={"enabled": on})
    assert r.status_code == 200, r.text


# ── Conversation memory is scoped ─────────────────────────────────────────────

def test_the_same_session_id_in_two_projects_is_two_histories(client):
    for project, text in (("proj_research", "research says hi"), ("proj_support", "support says hi")):
        r = client.post("/api/memory/shared-id/add", headers=hdr(project=project),
                        json={"role": "user", "content": text})
        assert r.status_code == 200, r.text
    research = client.get("/api/memory/shared-id", headers=hdr()).json()["messages"]
    support = client.get("/api/memory/shared-id", headers=hdr(project="proj_support")).json()["messages"]
    assert [m["content"] for m in research] == ["research says hi"]
    assert [m["content"] for m in support] == ["support says hi"]
    assert "shared-id" not in {s["session_id"] for s in client.get("/api/memory", headers=hdr("user_viewer",
                                                                    project="proj_research")).json().get("sessions", [])}


def test_deleting_a_message_works_by_position(client):
    for text in ("one", "two", "three"):
        client.post("/api/memory/positions/add", headers=hdr(), json={"role": "user", "content": text})
    assert client.delete("/api/memory/positions/messages/1", headers=hdr()).status_code == 200
    assert [m["content"] for m in client.get("/api/memory/positions", headers=hdr()).json()["messages"]] == ["one", "three"]


def test_runs_only_see_their_projects_history(client, key, app_id):
    _ask(client, key, app_id, "my order number is 42", session="cust-1")
    assert "my order number is 42" in _ask(client, key, app_id, "what was my order?", session="cust-1")
    stored = client.get("/api/memory/cust-1", headers=hdr(project="proj_support")).json()["messages"]
    assert stored == [], "another project's same session id is empty"


def _age(session, hours):
    """Backdate a session's stored turns, as if they were sent ``hours`` ago."""
    when = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db_connection() as conn:
        conn.execute("UPDATE memory_messages SET created_at = ? WHERE session_id = ?", (when, session))
        conn.commit()


def test_session_ttl_drops_turns_older_than_it():
    who = ltm.Who("tenant_demo", "proj_research")
    ltm.append_messages(who, "ttl-unit", [("user", "old turn", 2)])
    _age("ttl-unit", 5)
    ltm.append_messages(who, "ttl-unit", [("user", "new turn", 2)])

    assert [m["content"] for m in ltm.load_messages(who, "ttl-unit", max_age_hours=1)] == ["new turn"]
    assert len(ltm.load_messages(who, "ttl-unit")) == 2, "no TTL keeps everything"
    assert ltm.session_ttl_hours({"session_ttl_hours": 24}) == 24
    assert ltm.session_ttl_hours({"session_ttl_hours": 0}) is None
    assert ltm.session_ttl_hours({"session_ttl_hours": "soon"}) is None
    assert ltm.session_ttl_hours(None) is None


def test_runs_ignore_turns_older_than_the_session_ttl(client, key):
    aid = client.post("/api/apps", headers=hdr(), json={"name": "Forgets", "description": "",
                                                        "flow_data": _flow(long_term=False, session_ttl_hours=1)}).json()["id"]
    assert client.post(f"/api/apps/{aid}/publish", headers=hdr()).status_code == 200

    _ask(client, key, aid, "my order number is 77", session="ttl-run")
    assert "my order number is 77" in _ask(client, key, aid, "what was my order?", session="ttl-run")
    _age("ttl-run", 2)
    assert "my order number is 77" not in _ask(client, key, aid, "what was my order?", session="ttl-run")
    stored = client.get("/api/memory/ttl-run", headers=hdr()).json()["messages"]
    assert any(m["content"] == "my order number is 77" for m in stored), "expired turns stay in the inspector"


# ── Opt-in ────────────────────────────────────────────────────────────────────

def test_long_term_memory_is_off_until_the_workspace_turns_it_on(client, key, app_id):
    assert client.get("/api/memory/long-term/settings", headers=hdr()).json() == {"enabled": False, "can_change": True}
    _ask(client, key, app_id, "I prefer tea", session="s-off", user="early")
    run_jobs()
    assert ltm.list_facts("tenant_demo", "proj_research", "early") == []
    assert not [j for j in jobs.list_jobs("tenant_demo", "proj_research", "done") if j["kind"] == ltm.JOB_KIND]
    assert client.put("/api/memory/long-term/settings", headers=hdr("user_analyst"),
                      json={"enabled": True}).status_code == 403, "a workspace owner decides"
    _turn_on(client)


# ── The exit criterion ────────────────────────────────────────────────────────

def test_a_preference_from_an_earlier_session_is_recalled(client, key, app_id):
    _turn_on(client)
    _ask(client, key, app_id, "Hi! I'm vegetarian and I prefer metric units.", session="alice-monday", user="alice")
    run_jobs()   # the memory.extract job
    facts = [f["content"] for f in ltm.list_facts("tenant_demo", "proj_research", "alice")]
    assert "Is vegetarian" in facts and "Likes metric units" in facts, facts

    context = _ask(client, key, app_id, "What should I cook tonight?", session="alice-friday", user="alice")
    assert "Is vegetarian" in context, "a new session still knows the preference"
    assert "Hi! I'm vegetarian" not in context, "the earlier conversation itself isn't replayed"

    bob = _ask(client, key, app_id, "What should I cook tonight?", session="bob-friday", user="bob")
    assert "vegetarian" not in bob, "facts belong to their own user"
    nobody = _ask(client, key, app_id, "What should I cook tonight?", session="anon")
    assert "vegetarian" not in nobody, "no user, no long-term memory"


def test_facts_are_redacted_and_deduplicated(client, key, app_id, env):
    async def model(cfg, user_text, assistant_text, known):
        return ["Email is carol@example.com", "Likes green tea", "Likes green tea"]
    env.setattr(ltm, "model_facts", model)
    _ask(client, key, app_id, "remember me", session="carol-1", user="carol")
    _ask(client, key, app_id, "remember me again", session="carol-2", user="carol")
    run_jobs()
    facts = [f["content"] for f in ltm.list_facts("tenant_demo", "proj_research", "carol")]
    assert sorted(facts) == ["Email is [PII:email]", "Likes green tea"], facts

    async def no_model(*a, **kw):
        return None
    env.setattr(ltm, "model_facts", no_model)


def test_typed_keys_never_go_into_the_job(env):
    from models import LLMConfig
    who = ltm.Who("tenant_demo", "proj_research", "dave")
    cfg = LLMConfig(provider="openai", model="gpt-4o-mini")
    plain = ltm.queue_extraction(who, cfg, None, "hi", "ok", "sk-live-abcdef1234567890")
    ref = ltm.queue_extraction(who, cfg, None, "hi", "ok", "secret://openai-prod")
    assert jobs.get(plain)["payload"].find("sk-live") == -1
    assert '"api_key": "secret://openai-prod"' in jobs.get(ref)["payload"]
    for job_id in (plain, ref):
        jobs.discard(job_id, "tenant_demo", "proj_research")   # not dead; just don't run them
    from db import get_db_connection
    conn = get_db_connection()
    conn.execute("DELETE FROM jobs WHERE kind = ?", (ltm.JOB_KIND,))
    conn.commit()
    conn.close()


def test_recall_ranks_by_the_prompt_past_recall_k():
    who = ltm.Who("tenant_demo", "proj_research", "erin")
    ltm.add_facts(who, [f"Likes hobby number {i}" for i in range(12)] + ["Has a golden retriever named Max"])
    picked = ltm.recall(who, "Any tips for my golden retriever?", k=3)
    assert len(picked) == 3 and picked[0] == "Has a golden retriever named Max"


def test_rules_pick_up_plain_statements():
    facts = ltm.rule_facts("Call me Sam. My name is Sam Lee. I live in Berlin, I work at Acme and "
                           "I hate cilantro. Please always answer in bullet points.")
    for expected in ("Prefers to be called Sam", "Their name is Sam Lee", "Lives in Berlin", "Works at Acme",
                     "Dislikes cilantro", "Asked: Please always answer in bullet points"):
        assert expected in facts, (expected, facts)
    assert ltm.rule_facts("What's the weather like?") == []


def test_runs_without_a_person_have_no_long_term_memory():
    from services.pipeline_runner import RunScope, current_scope
    token = current_scope.set(RunScope(tenant_id="tenant_demo", project_id="proj_research", user_id="owner"))
    try:
        who = ltm.current()
        assert who.user == "" and not ltm.active({"long_term": True}, who), "schedules and webhooks set no end user"
    finally:
        current_scope.reset(token)


# ── Inspector ─────────────────────────────────────────────────────────────────

def test_inspect_add_delete_and_forget(client):
    users = {u["subject"] for u in client.get("/api/memory/long-term/users", headers=hdr()).json()["users"]}
    assert "alice" in users
    r = client.post("/api/memory/long-term/facts", headers=hdr(), json={"user": "alice", "content": "Is left-handed"})
    assert r.status_code == 201
    assert client.post("/api/memory/long-term/facts", headers=hdr(),
                       json={"user": "alice", "content": "is left-handed!"}).status_code == 409, "same fact"
    facts = client.get("/api/memory/long-term/facts?user=alice", headers=hdr()).json()["facts"]
    manual = next(f for f in facts if f["content"] == "Is left-handed")
    assert manual["source"] == "manual"
    assert client.delete(f"/api/memory/long-term/facts/{manual['id']}", headers=hdr()).status_code == 200
    assert client.get("/api/memory/long-term/facts?user=alice",
                      headers=hdr(project="proj_support")).json()["facts"] == [], "another project sees none"
    assert client.delete("/api/memory/long-term/users/alice", headers=hdr()).json()["deleted"] >= 2
    assert client.get("/api/memory/long-term/facts?user=alice", headers=hdr()).json()["facts"] == []
    assert client.delete("/api/memory/long-term/users/alice", headers=hdr("user_viewer",
                                                                          project="proj_support")).status_code == 403

    from db import get_db_connection
    conn = get_db_connection()
    try:
        actions = {r["action"] for r in conn.execute("SELECT action FROM audit_log WHERE action LIKE 'memory.%'")}
    finally:
        conn.close()
    assert {"memory.settings", "memory.add_fact", "memory.delete_fact", "memory.forget_user"} <= actions


def test_the_extraction_job_skips_a_workspace_that_turned_it_off(client):
    _turn_on(client, False)
    job = jobs.Job(id="x", kind=ltm.JOB_KIND, payload={}, attempts=1, max_attempts=1)
    payload = {"tenant_id": "tenant_demo", "project_id": "proj_research", "user": "frank", "user_text": "I like jazz",
               "assistant_text": "ok", "provider": "mock"}
    asyncio.run(jobs._handlers[ltm.JOB_KIND].fn(payload, job))
    assert ltm.list_facts("tenant_demo", "proj_research", "frank") == []
    _turn_on(client)
    asyncio.run(jobs._handlers[ltm.JOB_KIND].fn(payload, job))
    assert [f["content"] for f in ltm.list_facts("tenant_demo", "proj_research", "frank")] == ["Likes jazz"]
