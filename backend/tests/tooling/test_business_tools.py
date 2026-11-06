"""Business Apps tools (Jira, Confluence, Notion, Zendesk, PagerDuty) against a fake HTTP
server shaped like each vendor's documented API — request method, path, query, auth and body,
and how responses are parsed. Plus the offline utilities. No network or vendor accounts needed.
"""
import asyncio
import base64
import json

import httpx
import pytest

import tools

calls = []


def basic(user, pw):
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


def handler(request: httpx.Request) -> httpx.Response:
    calls.append(request)
    host, path, q = request.url.host, request.url.path, request.url.params
    body = json.loads(request.content) if request.content else {}

    if host == "acme.atlassian.net":
        if request.headers.get("authorization") != basic("me@acme.com", "atl-token"):
            return httpx.Response(401, json={"errorMessages": ["unauthorized"]})
        if path == "/rest/api/3/search/jql":
            return httpx.Response(200, json={"issues": [{"key": "OPS-7", "fields": {
                "summary": "Checkout latency spike", "status": {"name": "In Progress"}, "assignee": {"displayName": "Ana"},
                "priority": {"name": "High"}, "updated": "2026-10-25T10:00:00.000+0000", "issuetype": {"name": "Bug"}}}]})
        if path == "/rest/api/3/issue/OPS-7":
            return httpx.Response(200, json={"key": "OPS-7", "fields": {
                "summary": "Checkout latency spike", "status": {"name": "In Progress"}, "issuetype": {"name": "Bug"},
                "priority": {"name": "High"}, "assignee": {"displayName": "Ana"}, "reporter": {"displayName": "Raj"},
                "created": "2026-10-20T09:00:00.000+0000", "updated": "2026-10-25T10:00:00.000+0000",
                "description": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": "p95 went from 300ms to 2s after deploy."}]}]},
                "comment": {"total": 1, "comments": [{"author": {"displayName": "Ana"}, "created": "2026-10-24T08:00:00.000+0000",
                                                      "body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [
                                                          {"type": "text", "text": "Rolling back."}]}]}}]}}})
        if path == "/rest/api/3/issue/NOPE-1":
            return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})
        if path == "/rest/api/3/issue" and request.method == "POST":
            return httpx.Response(201, json={"id": "10042", "key": "OPS-42", "self": "…"})
        if path == "/wiki/rest/api/search":
            return httpx.Response(200, json={"_links": {"base": "https://acme.atlassian.net/wiki"}, "results": [{
                "content": {"id": "98765", "title": "On-call runbook"}, "url": "/spaces/ENG/pages/98765/On-call+runbook",
                "excerpt": "How to @@@hl@@@roll back@@@endhl@@@ a <b>deploy</b>", "resultGlobalContainer": {"title": "Engineering"},
                "friendlyLastModified": "yesterday"}]})
        if path == "/wiki/rest/api/content/98765":
            return httpx.Response(200, json={"title": "On-call runbook", "space": {"name": "Engineering"}, "version": {"number": 7},
                                             "body": {"storage": {"value": "<h1>Rollback</h1><p>Run <code>deploy --undo</code>.</p>"}},
                                             "_links": {"base": "https://acme.atlassian.net/wiki", "webui": "/spaces/ENG/pages/98765"}})

    if host == "api.notion.com":
        if request.headers.get("authorization") != "Bearer secret_notion" or request.headers.get("notion-version") != "2022-06-28":
            return httpx.Response(401, json={"code": "unauthorized", "message": "API token is invalid."})
        title = {"title": {"type": "title", "title": [{"plain_text": "Launch plan"}]}}
        if path == "/v1/search":
            return httpx.Response(200, json={"results": [{"object": "page", "properties": title, "url": "https://www.notion.so/Launch-plan-1a2b",
                                                          "last_edited_time": "2026-10-24T12:00:00.000Z"}]})
        if path == "/v1/pages/0123456789abcdef0123456789abcdef":
            return httpx.Response(200, json={"properties": title, "url": "https://www.notion.so/Launch-plan-0123456789abcdef0123456789abcdef"})
        if path == "/v1/blocks/0123456789abcdef0123456789abcdef/children":
            rt = lambda t: {"rich_text": [{"plain_text": t}]}  # noqa: E731
            return httpx.Response(200, json={"has_more": False, "results": [
                {"type": "heading_2", "heading_2": rt("Goals")}, {"type": "bulleted_list_item", "bulleted_list_item": rt("Ship v2")},
                {"type": "to_do", "to_do": {**rt("Book venue"), "checked": True}}]})
        if path == "/v1/pages/ffffffffffffffffffffffffffffffff":
            return httpx.Response(404, json={"code": "object_not_found", "message": "Could not find page"})
        if path == "/v1/pages" and request.method == "POST":
            return httpx.Response(200, json={"url": "https://www.notion.so/Retro-notes-abc"})

    if host == "acme.zendesk.com":
        if request.headers.get("authorization") != basic("agent@acme.com/token", "zd-token"):
            return httpx.Response(401, json={"error": "Couldn't authenticate you"})
        if path == "/api/v2/search.json":
            return httpx.Response(200, json={"results": [{"id": 512, "subject": "Refund not received", "status": "open",
                                                          "priority": "high", "updated_at": "2026-10-25T09:00:00Z"}]})
        if path == "/api/v2/tickets/512.json":
            return httpx.Response(200, json={"ticket": {"id": 512, "subject": "Refund not received", "status": "open", "priority": "high",
                                                        "created_at": "2026-10-22T09:00:00Z", "updated_at": "2026-10-25T09:00:00Z",
                                                        "tags": ["billing"], "description": "I was promised a refund last week."}})
        if path == "/api/v2/tickets/512/comments.json":
            return httpx.Response(200, json={"comments": [{"public": False, "created_at": "2026-10-25T09:00:00Z", "plain_body": "Escalated to finance."}]})
        if path == "/api/v2/tickets.json" and request.method == "POST":
            return httpx.Response(201, json={"ticket": {"id": 777}})

    if host == "events.pagerduty.com" and path == "/v2/enqueue":
        if body.get("routing_key") != "R0UT1NG":
            return httpx.Response(400, json={"status": "invalid event", "errors": ["Invalid routing key"]})
        return httpx.Response(202, json={"status": "success", "dedup_key": body.get("dedup_key") or "dk-123"})
    if host == "api.pagerduty.com" and path == "/incidents":
        if request.headers.get("authorization") != "Token token=pd-rest":
            return httpx.Response(401, json={"error": {"message": "Invalid token"}})
        return httpx.Response(200, json={"incidents": [{"incident_number": 31, "status": "triggered", "urgency": "high",
                                                        "title": "DB CPU 98%", "service": {"summary": "Payments"},
                                                        "created_at": "2026-10-26T07:30:00Z", "html_url": "https://acme.pagerduty.com/incidents/X"}]})
    if host == "airflow.acme.io":
        if request.headers.get("authorization") != basic("admin", "af-pass"):
            return httpx.Response(401, json={"detail": "Unauthorized"})
        if path == "/api/v1/health":
            return httpx.Response(200, json={"metadatabase": {"status": "healthy"},
                                             "scheduler": {"status": "unhealthy", "latest_scheduler_heartbeat": "2026-10-26T06:00:00+00:00"}})
        if path == "/api/v1/importErrors":
            return httpx.Response(200, json={"total_entries": 2, "import_errors": [
                {"filename": "/dags/broken.py", "timestamp": "2026-10-26T07:00:00",
                 "stack_trace": "Traceback (most recent call last):\n  File \"/dags/broken.py\", line 3\nModuleNotFoundError: No module named 'pandas'"}]})
        if path == "/api/v1/dags/etl_daily/dagRuns/scheduled__2026-10-26/taskInstances/load/logs/3":
            assert request.headers["accept"] == "text/plain"
            return httpx.Response(200, text="starting\n" + "noise\n" * 2000 + "psycopg2.OperationalError: connection refused\n")
        if path == "/api/v1/dags/okdag/dagRuns":
            return httpx.Response(200, json={"dag_runs": [{"dag_run_id": "r1", "state": "success"}]})
        if path == "/api/v1/dags/okdag/dagRuns/r1/taskInstances":
            return httpx.Response(200, json={"task_instances": [{"task_id": "t", "state": "success", "try_number": 1}]})
        if path == "/api/v1/dags":
            return httpx.Response(200, json={"dags": [{"dag_id": "etl_daily", "is_paused": False, "next_dagrun": "2026-10-27T00:00:00+00:00"},
                                                      {"dag_id": "old_job", "is_paused": True, "next_dagrun": None}]})
        if path == "/api/v1/dags/etl_daily/dagRuns" and request.method == "GET":
            return httpx.Response(200, json={"dag_runs": [{"dag_run_id": "scheduled__2026-10-26", "state": "failed",
                                                           "start_date": "2026-10-26T00:00:01+00:00", "end_date": "2026-10-26T00:05:00+00:00"}]})
        if path == "/api/v1/dags/etl_daily/dagRuns" and request.method == "POST":
            return httpx.Response(200, json={"dag_run_id": "manual__2026-10-27", "state": "queued", "conf": body.get("conf")})
        if path == "/api/v1/dags/etl_daily/dagRuns/scheduled__2026-10-26/taskInstances":
            return httpx.Response(200, json={"task_instances": [{"task_id": "extract", "state": "success", "try_number": 1, "end_date": "2026-10-26T00:02:00+00:00"},
                                                                {"task_id": "load", "state": "failed", "try_number": 3, "end_date": "2026-10-26T00:05:00+00:00"}]})
        if path.startswith("/api/v1/dags/missing"):
            return httpx.Response(404, json={"detail": "DAG not found"})
    return httpx.Response(599, json={"error": f"unexpected request {request.method} {request.url}"})


@pytest.fixture
def vendors(monkeypatch):
    """Every httpx.AsyncClient talks to the fake vendor APIs above."""
    real = httpx.AsyncClient

    class FakeClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


def run(tool, inp, cfg):
    calls.clear()
    return asyncio.run(tools.execute(tool, inp, cfg))


ATL = {"base_url": "acme.atlassian.net", "email": "me@acme.com", "api_token": "atl-token"}
NOTION = {"api_token": "secret_notion"}
ZD = {"subdomain": "https://acme.zendesk.com", "email": "agent@acme.com", "api_token": "zd-token"}


def test_jira(vendors):
    out = run("jira", "checkout slow", {**ATL, "project_key": "OPS"})
    req = calls[0]
    assert req.url.path == "/rest/api/3/search/jql"
    assert req.url.params["jql"] == 'text ~ "checkout slow" AND project = "OPS" ORDER BY updated DESC'
    assert "OPS-7 [In Progress] Checkout latency spike" in out and "Ana" in out
    assert "https://acme.atlassian.net/browse/OPS-7" in out

    run("jira", "status = Open AND assignee = currentUser()", ATL)
    assert calls[0].url.params["jql"] == "status = Open AND assignee = currentUser()", "JQL passed through"

    out = run("jira", "ops-7", ATL)
    assert calls[0].url.path == "/rest/api/3/issue/OPS-7"
    assert "p95 went from 300ms to 2s" in out and "Ana (2026-10-24): Rolling back." in out, "ADF → text"

    out = run("jira", "create: Add retry to payment webhook\nFailures spike when the bank API is slow.",
              {**ATL, "project_key": "OPS", "issue_type": "Bug"})
    sent = json.loads(calls[0].content)["fields"]
    assert sent["project"] == {"key": "OPS"} and sent["summary"] == "Add retry to payment webhook"
    assert sent["issuetype"] == {"name": "Bug"}
    assert sent["description"]["content"][0]["content"][0]["text"] == "Failures spike when the bank API is slow."
    assert "Created OPS-42" in out
    assert "project_key" in run("jira", "create: x", ATL)
    assert "Not found" in run("jira", "NOPE-1", ATL)
    assert "Authentication failed" in run("jira", "x", {**ATL, "api_token": "wrong"})
    assert "required in config" in run("jira", "x", {})


def test_confluence(vendors):
    out = run("confluence", "roll back deploy", {**ATL, "space_key": "ENG"})
    assert calls[0].url.params["cql"] == 'type = page AND text ~ "roll back deploy" AND space = "ENG"'
    assert "On-call runbook — Engineering" in out and "How to roll back a deploy" in out
    assert "https://acme.atlassian.net/wiki/spaces/ENG/pages/98765/On-call+runbook" in out

    out = run("confluence", "https://acme.atlassian.net/wiki/spaces/ENG/pages/98765/On-call+runbook", ATL)
    assert calls[0].url.path == "/wiki/rest/api/content/98765"
    assert "Rollback" in out and "deploy --undo" in out and "version 7" in out


def test_notion(vendors):
    out = run("notion", "launch", NOTION)
    sent = json.loads(calls[0].content)
    assert calls[0].url.path == "/v1/search" and sent["query"] == "launch"
    assert sent["filter"] == {"property": "object", "value": "page"}
    assert "Launch plan" in out and "notion.so" in out

    out = run("notion", "https://www.notion.so/acme/Launch-plan-0123456789abcdef0123456789abcdef", NOTION)
    assert "## Goals" in out and "- Ship v2" in out and "[x] Book venue" in out
    assert "## Goals" in run("notion", "01234567-89ab-cdef-0123-456789abcdef", NOTION), "dashed UUIDs work"
    assert "share it with your integration" in run("notion", "ffffffffffffffffffffffffffffffff", NOTION)

    out = run("notion", "create: Retro notes\nWhat went well.\n\nWhat to improve.",
              {**NOTION, "parent_page_id": "https://www.notion.so/Team-0123456789abcdef0123456789abcdef"})
    sent = json.loads(calls[0].content)
    assert sent["parent"] == {"page_id": "0123456789abcdef0123456789abcdef"}
    assert sent["properties"]["title"]["title"][0]["text"]["content"] == "Retro notes"
    assert len(sent["children"]) == 2, "one paragraph per block"
    assert "Retro-notes" in out
    assert "parent_page_id" in run("notion", "create: x", NOTION)


def test_zendesk(vendors):
    out = run("zendesk", "refund", ZD)
    assert calls[0].url.path == "/api/v2/search.json" and calls[0].url.params["query"] == "type:ticket refund"
    assert "#512 [open] Refund not received" in out and "https://acme.zendesk.com/agent/tickets/512" in out

    out = run("zendesk", "#512", ZD)
    assert "I was promised a refund" in out and "internal (2026-10-25): Escalated to finance." in out

    out = run("zendesk", "create: Can't log in\nPassword reset email never arrives.", {**ZD, "priority": "high"})
    assert json.loads(calls[0].content)["ticket"] == {
        "subject": "Can't log in", "comment": {"body": "Password reset email never arrives."}, "priority": "high"}
    assert "Created ticket #777" in out


def test_pagerduty(vendors):
    out = run("pagerduty", "Checkout error rate above 5%", {"routing_key": "R0UT1NG", "severity": "critical"})
    sent = json.loads(calls[0].content)
    assert sent["event_action"] == "trigger"
    assert sent["payload"] == {"summary": "Checkout error rate above 5%", "source": "pipesets-ai", "severity": "critical"}
    assert "dk-123" in out

    run("pagerduty", "dk-123", {"routing_key": "R0UT1NG", "action": "resolve"})
    assert json.loads(calls[0].content) == {"routing_key": "R0UT1NG", "event_action": "resolve", "dedup_key": "dk-123"}
    assert "Invalid routing key" in run("pagerduty", "x", {"routing_key": "bad"})

    out = run("pagerduty", "", {"action": "list", "api_token": "pd-rest"})
    assert calls[0].url.params.get_list("statuses[]") == ["triggered", "acknowledged"]
    assert "#31 [triggered, high urgency] DB CPU 98%" in out
    assert "api_token" in run("pagerduty", "", {"action": "list"})


AF = {"base_url": "https://airflow.acme.io/", "username": "admin", "password": "af-pass"}


def test_airflow(vendors):
    out = run("airflow", "", AF)
    assert "etl_daily [active]" in out and "old_job [paused]" in out

    out = run("airflow", "etl_daily", {**AF, "action": "dag_runs"})
    assert "scheduled__2026-10-26 [failed]" in out

    out = run("airflow", "etl_daily", {**AF, "action": "task_instances"})  # latest run is looked up
    assert "load [failed] try 3" in out and "extract [success]" in out

    assert "disabled" in run("airflow", "etl_daily", {**AF, "action": "trigger"})
    assert len(calls) == 0, "nothing is sent while triggering is off"
    out = run("airflow", "etl_daily", {**AF, "action": "trigger", "allow_trigger": True, "conf": {"day": "x"}})
    assert json.loads(calls[0].content) == {"conf": {"day": "x"}}
    assert "manual__2026-10-27 is queued" in out

    assert "Authentication failed" in run("airflow", "", {**AF, "password": "nope"})
    assert "Not found" in run("airflow", "missing", {**AF, "action": "dag_runs"})
    assert "DAG id" in run("airflow", "", {**AF, "action": "dag_runs"})
    assert "base_url" in run("airflow", "", {"base_url": ""})


def test_airflow_task_logs(vendors):
    out = run("airflow_task_logs", "etl_daily", {**AF, "max_chars": 800})   # latest run, first failed task, its last try
    assert "etl_daily / scheduled__2026-10-26 / load, try 3 (last 800 of" in out
    assert out.rstrip().endswith("connection refused") and "starting" not in out, "the tail is kept"
    assert len(out) < 1000

    assert "No failed tasks" in run("airflow_task_logs", "okdag", AF)
    assert "isn't in" in run("airflow_task_logs", "etl_daily", {**AF, "task_id": "nope"})
    assert "Provide the DAG id" in run("airflow_task_logs", "", AF)
    assert "Authentication failed" in run("airflow_task_logs", "etl_daily", {**AF, "password": "x"})


def test_airflow_import_errors_and_health(vendors):
    out = run("airflow_import_errors", "", AF)
    assert "2 DAG file(s) failed to import (showing 1)" in out
    assert "/dags/broken.py" in out and "ModuleNotFoundError: No module named 'pandas'" in out
    assert "Traceback" not in out, "just the last line of the traceback"

    out = run("airflow_health", "", AF)
    assert "Unhealthy: scheduler" in out and "metadatabase: healthy" in out
    assert "scheduler: unhealthy (last heartbeat 2026-10-26 06:00:00)" in out
    assert "Authentication failed" in run("airflow_health", "", {**AF, "password": "x"})


def test_offline_utilities():
    assert "38 business days" in run("date_calculator", "business days between 2026-11-02 and 2026-12-24", {})
    assert "= 2027-01-04" in run("date_calculator", "add 10 business days to 2026-12-18", {"holidays": "2026-12-25"})
    assert "= 2026-02-28" in run("date_calculator", "2026-01-31 + 1 month", {}), "month end clamps"
    md = run("html_to_markdown", "<h2>T</h2><p>Hi <b>there</b> <a href='https://x.io'>x</a></p>"
                                 "<ol><li>a</li><li>b</li></ol><script>bad()</script>", {})
    assert "## T" in md and "**there**" in md and "[x](https://x.io)" in md and "1. a" in md
    assert "bad()" not in md, "scripts dropped"
