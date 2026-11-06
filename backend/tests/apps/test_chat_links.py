"""Public chat links: creating and managing links, the visitor's session, streaming answers that only
carry the answer, memory per conversation, limits, revoking and the audit trail. The tests are steps
of one scenario, in order."""
import json

import pytest

from db import get_db_connection
from helpers import hdr, mock_flow
from services import chat_links, secret_store, shared_state

ADMIN = hdr()
state = {}   # ids and tokens created by earlier steps


def events(r):
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def answer(r):
    return "".join(e["text"] for e in events(r) if e["type"] == "token")


def chat(client, token, message, session=None):
    return client.post(f"/v1/chat/{token}/message", json={"session": session or state["session"], "message": message})


@pytest.fixture(scope="module")
def app_id(client):
    return client.post("/api/apps", json={"name": "Support bot", "flow_data": mock_flow("bot")}, headers=ADMIN).json()["id"]


def test_a_draft_pipeline_cant_be_shared(client, app_id):
    r = client.post("/api/chat-links", json={"app_id": app_id}, headers=ADMIN)
    assert r.status_code == 409


def test_create_a_link_for_a_published_pipeline(client, app_id):
    assert client.post(f"/api/apps/{app_id}/publish", headers=ADMIN).status_code == 200
    r = client.post("/api/chat-links", json={"app_id": app_id, "greeting": "Hi! Ask me anything."}, headers=ADMIN)
    assert r.status_code == 201
    link = r.json()
    assert link["token"].startswith("pc_") and link["active"]
    assert link["name"] == "Support bot chat" and link["access"] == "public"
    assert link["rate_limit_per_min"] == chat_links.DEFAULT_LIMITS["rate_limit_per_min"]
    assert "token_hash" not in link and "token_sealed" not in link
    state.update(link=link, token=link["token"])


def test_the_token_is_not_stored_in_plaintext(client):
    conn = get_db_connection()
    try:
        row = dict(conn.execute("SELECT * FROM chat_links WHERE id = ?", (state["link"]["id"],)).fetchone())
    finally:
        conn.close()
    assert state["token"] not in json.dumps(row)
    assert secret_store.is_sealed(row["token_sealed"])
    # ... and the builder can still copy the link again
    listed = client.get("/api/chat-links", params={"app_id": state["link"]["app_id"]}, headers=ADMIN).json()
    assert [l["token"] for l in listed] == [state["token"]]


def test_visitor_starts_a_session(client):
    r = client.post(f"/v1/chat/{state['token']}/session", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Support bot" and body["greeting"] == "Hi! Ask me anything."
    assert not body["resumed"]
    state["session"] = body["session"]
    # Coming back with the same session continues it
    again = client.post(f"/v1/chat/{state['token']}/session", json={"session": state["session"]}).json()
    assert again["resumed"] and again["session"] == state["session"]


def test_the_page_shows_pipeline_details_and_starter_prompts(client, app_id):
    flow = {"nodes": [
        {"id": "m", "type": "master_agent", "data": {"label": "Coordinator", "provider": "mock", "model": "mock-gpt-4",
                                                    "system_prompt": "SECRET INSTRUCTIONS"}},
        {"id": "a", "type": "child_agent", "data": {"role": "Researcher", "kind": "llm", "provider": "openai",
                                                   "model": "gpt-4o"}},
        {"id": "w", "type": "tool", "data": {"label": "Weather", "toolId": "weather", "toolType": "tool"}},
        {"id": "q", "type": "tool", "data": {"label": "Database Query (SQL)", "toolId": "mcp_database", "toolType": "mcp"}},
        {"id": "c", "type": "connection", "data": {"label": "Prod DB", "status_msg": "reached db.internal:5432"}},
        {"id": "r", "type": "retriever", "data": {"collection_name": "hr_private_docs"}},
    ], "edges": []}
    app = client.post("/api/apps", json={"name": "Crew", "description": "Answers weather and data questions.",
                                         "flow_data": flow}, headers=ADMIN).json()
    assert client.post(f"/api/apps/{app['id']}/publish", headers=ADMIN).status_code == 200
    link = client.post("/api/chat-links", headers=ADMIN, json={
        "app_id": app["id"], "starter_prompts": ["What's the weather in Oslo?", "  ", "How many orders today?"],
    }).json()
    assert link["show_details"] and link["starter_prompts"] == ["What's the weather in Oslo?", "How many orders today?"]

    body = client.post(f"/v1/chat/{link['token']}/session", json={}).json()
    assert body["starter_prompts"] == link["starter_prompts"]
    about = body["about"]
    assert about["description"] == "Answers weather and data questions."
    assert about["pipeline_id"] == app["id"] and about["version"] == 1
    assert about["models"] == ["mock-gpt-4 (Simulated)", "gpt-4o (OpenAI)"]
    assert about["agents"] == ["Coordinator", "Researcher"]
    assert about["tools"] == ["Weather"] and about["mcp_servers"] == ["Database Query (SQL)"]
    assert about["answers_from_documents"]
    page = json.dumps(body)
    for private in ("SECRET INSTRUCTIONS", "db.internal", "hr_private_docs", "Prod DB"):
        assert private not in page

    # The builder can hide the details; the prompts stay
    client.patch(f"/api/chat-links/{link['id']}", json={"show_details": False}, headers=ADMIN)
    body = client.post(f"/v1/chat/{link['token']}/session", json={}).json()
    assert body["about"] is None and body["starter_prompts"] == link["starter_prompts"]
    assert client.post("/api/chat-links", headers=ADMIN,
                       json={"app_id": app["id"], "starter_prompts": ["x"] * 7}).status_code == 422
    client.delete(f"/api/chat-links/{link['id']}", headers=ADMIN)


def test_unknown_or_forged_tokens_and_sessions(client):
    assert client.post("/v1/chat/pc_nope/session", json={}).status_code == 404
    assert client.post("/v1/chat/whk_nope/session", json={}).status_code == 404
    r = chat(client, state["token"], "hi", session="not-a-session")
    assert r.status_code == 401
    # A session made for another link is refused too
    other = chat_links.new_session({"id": "chat_other"})
    assert chat(client, state["token"], "hi", session=other).status_code == 401


def test_visitor_chats_and_sees_only_the_answer(client):
    r = chat(client, state["token"], "What are your opening hours?")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    evs = events(r)
    assert answer(r)
    assert {e["type"] for e in evs} <= {"token", "error", "done"}, "no trace, meta or run ids for visitors"
    assert evs[-1]["type"] == "done"


def test_the_conversation_is_remembered_without_a_memory_node(client):
    chat(client, state["token"], "And on Sundays?")
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT session_id, role, content FROM memory_messages WHERE session_id LIKE ? ORDER BY id",
                            (f"chat:{state['link']['id']}:%",)).fetchall()
    finally:
        conn.close()
    assert len({r["session_id"] for r in rows}) == 1
    assert [r["content"] for r in rows if r["role"] == "user"] == ["What are your opening hours?", "And on Sundays?"]


def test_each_visitor_has_their_own_conversation(client):
    other = client.post(f"/v1/chat/{state['token']}/session", json={}).json()["session"]
    assert other != state["session"]
    chat(client, state["token"], "Hello from someone else", session=other)
    conn = get_db_connection()
    try:
        sessions = conn.execute("SELECT DISTINCT session_id FROM memory_messages WHERE session_id LIKE ?",
                                (f"chat:{state['link']['id']}:%",)).fetchall()
    finally:
        conn.close()
    assert len(sessions) == 2


def test_message_count_is_kept(client):
    link = client.get("/api/chat-links", params={"app_id": state["link"]["app_id"]}, headers=ADMIN).json()[0]
    assert link["message_count"] == 3 and link["last_used_at"]


def test_limits(client):
    lid = state["link"]["id"]
    r = client.patch(f"/api/chat-links/{lid}", json={"max_message_chars": 10, "max_turns": 3,
                                                    "rate_limit_per_min": 0, "title": "Help desk"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["title"] == "Help desk"
    assert chat(client, state["token"], "x" * 11).status_code == 413
    # This session has sent 2 messages; the third is the last one allowed
    assert chat(client, state["token"], "one more").status_code == 200
    r = chat(client, state["token"], "too many")
    assert r.status_code == 429 and "start a new chat" in r.json()["detail"]

    shared_state.store().clear()   # earlier steps' messages are still in this minute's window
    client.patch(f"/api/chat-links/{lid}", json={"max_turns": 0, "rate_limit_per_min": 1}, headers=ADMIN)
    fresh = client.post(f"/v1/chat/{state['token']}/session", json={}).json()["session"]
    assert chat(client, state["token"], "first", session=fresh).status_code == 200
    r = chat(client, state["token"], "second", session=fresh)
    assert r.status_code == 429 and r.headers.get("retry-after")

    shared_state.store().clear()
    client.patch(f"/api/chat-links/{lid}", json={"rate_limit_per_min": 0, "daily_message_cap": 1}, headers=ADMIN)
    assert chat(client, state["token"], "today", session=fresh).status_code == 200
    assert chat(client, state["token"], "again", session=fresh).status_code == 429


def test_unpublished_pipeline_makes_the_chat_unavailable(client, app_id):
    shared_state.store().clear()
    client.patch(f"/api/chat-links/{state['link']['id']}", json={"daily_message_cap": 0}, headers=ADMIN)
    assert client.post(f"/api/apps/{app_id}/edit", headers=ADMIN).status_code == 200
    assert client.post(f"/v1/chat/{state['token']}/session", json={}).status_code == 503
    assert client.post(f"/api/apps/{app_id}/publish", headers=ADMIN).status_code == 200
    assert client.post(f"/v1/chat/{state['token']}/session", json={}).status_code == 200


def test_links_are_scoped_to_their_project(client):
    other = hdr(project="proj_other")
    assert client.patch(f"/api/chat-links/{state['link']['id']}", json={"title": "x"}, headers=other).status_code == 404
    assert client.delete(f"/api/chat-links/{state['link']['id']}", headers=other).status_code == 404


def test_a_new_url_replaces_the_old_one(client):
    r = client.post(f"/api/chat-links/{state['link']['id']}/rotate", headers=ADMIN)
    assert r.status_code == 200
    link = r.json()
    assert link["token"] != state["token"] and link["message_count"] > 0  # the history stays
    assert client.post(f"/v1/chat/{state['token']}/session", json={}).status_code == 404
    # visitors keep their conversation: the session belongs to the link, not its URL
    assert chat(client, link["token"], "still you?").status_code == 200
    state["token"] = link["token"]
    assert client.post(f"/api/chat-links/{link['id']}/rotate", headers=hdr(project="proj_other")).status_code == 404


def test_revoke_stops_the_link_on_the_next_message(client):
    r = client.delete(f"/api/chat-links/{state['link']['id']}", headers=ADMIN)
    assert r.status_code == 200
    assert chat(client, state["token"], "still there?").status_code == 404
    assert client.post(f"/v1/chat/{state['token']}/session", json={}).status_code == 404
    listed = client.get("/api/chat-links", params={"app_id": state["link"]["app_id"]}, headers=ADMIN).json()[0]
    assert not listed["active"] and "token" not in listed
    assert client.delete(f"/api/chat-links/{state['link']['id']}", headers=ADMIN).status_code == 404


def test_link_changes_are_audited(client):
    conn = get_db_connection()
    try:
        actions = {r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()}
    finally:
        conn.close()
    assert {"chat_link.create", "chat_link.update", "chat_link.rotate", "chat_link.revoke"} <= actions
