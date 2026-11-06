"""Slack, Airtable, Trello, HubSpot, Stripe and Linear against a fake HTTP server shaped like each
vendor's documented API — request method, path, query, auth and body, and how responses are
parsed. No network or vendor accounts needed.
"""
import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

import tools

calls = []


def ok(body):
    return httpx.Response(200, json=body)


def slack(request, path, q, body):
    if request.headers.get("authorization") != "Bearer xoxb-good":
        return ok({"ok": False, "error": "invalid_auth"})
    if path == "/api/chat.postMessage":
        if body["channel"] == "#secret":
            return ok({"ok": False, "error": "not_in_channel"})
        return ok({"ok": True, "channel": "C0123456789", "ts": "1730000000.000100"})
    if path == "/api/conversations.list":
        if not q.get("cursor"):
            return ok({"ok": True, "channels": [{"id": "C0AAAAAAAAA", "name": "random"}],
                       "response_metadata": {"next_cursor": "page2"}})
        return ok({"ok": True, "channels": [{"id": "C0123456789", "name": "general"}], "response_metadata": {"next_cursor": ""}})
    if path == "/api/conversations.history":
        assert q["channel"] == "C0123456789"
        return ok({"ok": True, "messages": [  # newest first
            {"user": "U2", "text": "Deploy done", "ts": "1730000200.000000", "reply_count": 2},
            {"user": "U1", "text": "Starting deploy", "ts": "1730000100.000000"}]})
    if path == "/api/conversations.replies":
        return ok({"ok": True, "messages": [{"user": "U2", "text": "Deploy done", "ts": q["ts"]},
                                            {"user": "U1", "text": "🎉", "ts": "1730000300.000000"}]})
    if path == "/api/users.info":
        return ok({"ok": True, "user": {"name": q["user"].lower(), "profile": {"display_name": {"U1": "ana", "U2": "raj"}[q["user"]]}}})


def airtable(request, path, q, body):
    if request.headers.get("authorization") != "Bearer pat-good":
        return httpx.Response(401, json={"error": {"type": "AUTHENTICATION_REQUIRED", "message": "Authentication required"}})
    if path == "/v0/appBASE/Missing%20Table":
        return httpx.Response(404, json={"error": "NOT_FOUND"})
    assert path == "/v0/appBASE/Customer%20List", path
    records = [{"id": "rec1", "fields": {"Name": "Ada Lovelace", "Status": "Active"}},
               {"id": "rec2", "fields": {"Name": "Alan Turing", "Status": "Churned", "Tags": ["vip"]}}]
    if request.method == "POST":
        assert body["typecast"] is True
        return ok({"records": [{"id": "rec9", "fields": body["records"][0]["fields"]}]})
    if "filterByFormula" in q:
        assert q["filterByFormula"] == 'SEARCH(LOWER("tur\\"ing"), LOWER({Name} & ""))'
        return ok({"records": records[1:]})
    return ok({"records": records})


def trello(request, path, q, body):
    if q.get("key") != "tkey" or q.get("token") != "ttok":
        return httpx.Response(401, text="invalid key")
    if path == "/1/search":
        assert q["modelTypes"] == "cards" and q["idBoards"] == "b1"
        return ok({"cards": [{"name": "Fix login bug", "desc": "Users get 500", "due": "2026-11-02T12:00:00Z",
                              "shortUrl": "https://trello.com/c/abc"}]})
    if path == "/1/lists/l1/cards":
        return ok([{"name": "Card A", "shortUrl": "https://trello.com/c/a"}, {"name": "Card B", "shortUrl": "https://trello.com/c/b"}])
    if path == "/1/cards" and request.method == "POST":
        assert q["idList"] == "l1" and q["desc"] == "Steps:\n1. open"
        return ok({"name": q["name"], "shortUrl": "https://trello.com/c/new"})


def hubspot(request, path, q, body):
    if request.headers.get("authorization") != "Bearer pat-hub":
        return httpx.Response(401, json={"status": "error", "message": "Authentication credentials not found."})
    if path == "/crm/v3/objects/contacts/search":
        assert body["query"] == "ada" and "email" in body["properties"]
        return ok({"total": 1, "results": [{"id": "51", "properties": {
            "firstname": "Ada", "lastname": "Lovelace", "email": "ada@example.com", "jobtitle": "CTO"}}]})
    if path == "/crm/v3/objects/deals/search":
        return ok({"total": 0, "results": []})
    if path == "/crm/v3/objects/contacts" and request.method == "POST":
        if body["properties"]["email"] == "dupe@example.com":
            return httpx.Response(409, json={"message": "Contact already exists. Existing ID: 77"})
        return httpx.Response(201, json={"id": "99", "properties": body["properties"]})


def stripe(request, path, q, body):
    if request.headers.get("authorization") != "Bearer rk_test_good":
        return httpx.Response(401, json={"error": {"message": "Invalid API Key provided", "type": "invalid_request_error"}})
    if path == "/v1/customers" and q.get("email") == "ada@example.com":
        return ok({"data": [{"id": "cus_A", "name": "Ada", "email": "ada@example.com", "created": 1730000000}]})
    if path == "/v1/customers" and q.get("email") == "ghost@example.com":
        return ok({"data": []})
    if path == "/v1/customers/search":
        assert q["query"] == 'name~"Ada" OR email~"Ada"'
        return ok({"data": [{"id": "cus_A", "name": "Ada", "email": "ada@example.com"}]})
    if path == "/v1/payment_intents":
        assert q["customer"] == "cus_A"
        return ok({"data": [{"id": "pi_1", "amount": 129900, "currency": "usd", "status": "succeeded", "created": 1730000000},
                            {"id": "pi_2", "amount": 5000, "currency": "jpy", "status": "requires_payment_method", "created": 1730000000}]})
    if path == "/v1/subscriptions":
        assert q["status"] == "all" and "customer" not in q
        return ok({"data": [{"id": "sub_1", "status": "active", "customer": "cus_A", "cancel_at_period_end": True,
                             "items": {"data": [{"price": {"unit_amount": 2000, "currency": "eur", "recurring": {"interval": "month"}}}]}}]})
    if path == "/v1/balance":
        return ok({"available": [{"amount": 1050, "currency": "usd"}], "pending": [{"amount": 0, "currency": "usd"}]})


def linear(request, path, q, body):
    if request.headers.get("authorization") != "lin_api_good":
        return httpx.Response(400, json={"errors": [{"message": "Authentication required, not authenticated",
                                                     "extensions": {"code": "AUTHENTICATION_ERROR"}}]})
    query, v = body["query"], body["variables"]
    if "searchIssues" in query:
        return ok({"data": {"searchIssues": {"nodes": [{"identifier": "ENG-7", "title": "Checkout is slow", "url": "https://linear.app/x/issue/ENG-7",
                                                        "priorityLabel": "High", "updatedAt": "2026-10-29T10:00:00Z",
                                                        "state": {"name": "In Progress"}, "assignee": {"name": "Ana"}}]}}})
    if "issue(id:" in query:
        if v["id"] == "ENG-404":
            return ok({"errors": [{"message": "Entity not found: Issue"}], "data": None})
        return ok({"data": {"issue": {"identifier": "ENG-7", "title": "Checkout is slow", "description": "p95 is 2s",
                                      "url": "https://linear.app/x/issue/ENG-7", "state": {"name": "In Progress"},
                                      "team": {"key": "ENG"}, "labels": {"nodes": [{"name": "perf"}]},
                                      "comments": {"nodes": [{"body": "Profiling now", "createdAt": "2026-10-29", "user": {"name": "Raj"}}]}}}})
    if "teams(filter" in query:
        return ok({"data": {"teams": {"nodes": [{"id": "team-uuid", "key": v["key"], "name": "Engineering"}] if v["key"] == "ENG" else []}}})
    if "issueCreate" in query:
        assert v["input"] == {"teamId": "team-uuid", "title": "Add retries", "description": "To the webhook"}
        return ok({"data": {"issueCreate": {"success": True, "issue": {"identifier": "ENG-8", "title": "Add retries",
                                                                        "url": "https://linear.app/x/issue/ENG-8"}}}})


VENDORS = {"slack.com": slack, "api.airtable.com": airtable, "api.trello.com": trello, "api.hubapi.com": hubspot,
           "api.stripe.com": stripe, "api.linear.app": linear}


def handler(request: httpx.Request) -> httpx.Response:
    calls.append(request)
    q = {k: v[0] for k, v in parse_qs(request.url.query.decode(), keep_blank_values=True).items()}
    body = json.loads(request.content) if request.content and request.headers.get("content-type", "").startswith("application/json") else {}
    res = VENDORS[request.url.host](request, request.url.raw_path.decode().split("?")[0], q, body)
    return res if res is not None else httpx.Response(404, json={"message": f"unexpected {request.method} {request.url}"})


@pytest.fixture(autouse=True)
def vendors(monkeypatch):
    real = httpx.AsyncClient

    class FakeClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


def run(tool, inp, cfg, args=None):
    calls.clear()
    return asyncio.run(tools.execute(tool, inp, cfg, args))


def test_slack():
    cfg = {"bot_token": "xoxb-good", "channel": "#general"}
    assert run("slack", "Release v2 is live", cfg) == "[Slack] Posted to #general (ts 1730000000.000100)."
    assert json.loads(calls[0].content) == {"channel": "#general", "text": "Release v2 is live"}
    out = run("slack", "", {**cfg, "action": "history"})
    assert out.index("ana: Starting deploy") < out.index("raj: Deploy done"), "oldest first"
    assert "2 replies (thread_ts 1730000200.000000)" in out
    assert [c.url.path for c in calls[:2]] == ["/api/conversations.list"] * 2, "the name is looked up across pages"
    thread = run("slack", "", {**cfg, "action": "history", "thread_ts": "1730000200.000000"})
    assert "ana: 🎉" in thread
    # the model chooses the action and thread, never the channel
    run("slack", "", cfg, {"text": "On it", "thread_ts": "1730000200.000000"})
    assert json.loads(calls[0].content) == {"channel": "#general", "text": "On it", "thread_ts": "1730000200.000000"}
    assert "invite it with /invite" in run("slack", "hi", {**cfg, "channel": "#secret"})
    assert run("slack", "hi", {**cfg, "bot_token": "xoxb-bad"}) == "[Slack] The bot_token is invalid."
    assert "Set a channel" in run("slack", "hi", {"bot_token": "xoxb-good"})


def test_airtable():
    cfg = {"api_token": "pat-good", "base_id": "appBASE", "table": "Customer List"}
    out = run("airtable", "vip", cfg)
    assert "rec2" in out and "rec1" not in out, "text matched across every field"
    out = run("airtable", 'tur"ing', {**cfg, "search_field": "Name"})
    assert "Alan Turing" in out and calls[0].url.params["maxRecords"] == "10"
    assert "2 record(s) in the table" in run("airtable", "", cfg)
    created = run("airtable", '{"Name": "Grace", "Status": "Active"}', {**cfg, "action": "create"})
    assert created.startswith("[Airtable] Created record rec9") and "Name: Grace" in created
    assert "JSON object of fields" in run("airtable", "Grace", {**cfg, "action": "create"})
    assert "Base or table not found" in run("airtable", "", {**cfg, "table": "Missing Table"})
    assert run("airtable", "", {**cfg, "api_token": "nope"}) == "[Airtable] The api_token is invalid."


def test_trello():
    cfg = {"api_key": "tkey", "token": "ttok", "board_id": "b1", "list_id": "l1"}
    out = run("trello", "login", cfg)
    assert "Fix login bug · due 2026-11-02" in out and "Users get 500" in out
    assert "2 card(s)" in run("trello", "", {**cfg, "action": "list"})
    assert run("trello", "Write tests\nSteps:\n1. open", {**cfg, "action": "create"}) == \
        "[Trello] Created card 'Write tests'\nhttps://trello.com/c/new"
    assert "Set list_id" in run("trello", "x", {**cfg, "list_id": "", "action": "create"})
    assert "invalid" in run("trello", "x", {**cfg, "token": "bad"})


def test_hubspot():
    cfg = {"access_token": "pat-hub"}
    out = run("hubspot", "ada", cfg)
    assert "Ada Lovelace (id 51) · ada@example.com · CTO" in out
    assert "No deals match" in run("hubspot", "big", {**cfg, "object": "deals"})
    out = run("hubspot", "new@example.com", {**cfg, "action": "create"})
    assert out.startswith("[HubSpot] Created contact") and json.loads(calls[0].content) == {"properties": {"email": "new@example.com"}}
    assert "already exists" in run("hubspot", '{"email": "dupe@example.com"}', {**cfg, "action": "create"})
    assert "invalid or expired" in run("hubspot", "ada", {"access_token": "x"})
    assert "object is one of" in run("hubspot", "ada", {**cfg, "object": "tickets"})


def test_stripe():
    cfg = {"api_key": "rk_test_good"}
    assert "Ada (cus_A) · ada@example.com" in run("stripe", "ada@example.com", cfg)
    assert "cus_A" in run("stripe", "Ada", cfg)
    out = run("stripe", "ada@example.com", {**cfg, "action": "payments"})
    assert "1,299.00 USD · succeeded" in out and "5,000 JPY" in out, "zero-decimal currencies aren't divided"
    assert "No customer with email" in run("stripe", "ghost@example.com", {**cfg, "action": "invoices"})
    subs = run("stripe", "", {**cfg, "action": "subscriptions"})
    assert "20.00 EUR/month" in subs and "cancels at period end" in subs
    assert run("stripe", "", {**cfg, "action": "balance"}) == "[Stripe] Balance\nAvailable: 10.50 USD\nPending: 0.00 USD"
    assert all(c.method == "GET" for c in calls), "read-only"
    assert run("stripe", "", {"api_key": "sk_bad"}) == "[Stripe] The api_key is invalid."


def test_linear():
    cfg = {"api_key": "lin_api_good", "team_key": "ENG"}
    assert "ENG-7 Checkout is slow · In Progress · High · Ana" in run("linear", "checkout", cfg)
    read = run("linear", "eng-7", cfg)
    assert "Labels: perf" in read and "Raj (2026-10-29): Profiling now" in read
    assert run("linear", "ENG-404", cfg) == "[Linear] Entity not found: Issue"
    assert run("linear", "create: Add retries\nTo the webhook", cfg) == \
        "[Linear] Created ENG-8: Add retries\nhttps://linear.app/x/issue/ENG-8"
    assert "No team with key OPS" in run("linear", "create: X", {**cfg, "team_key": "ops"})
    assert run("linear", "x", {"api_key": "lin_api_bad"}) == "[Linear] The api_key is invalid."
