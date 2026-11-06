"""The Microsoft 365 tools (Outlook mail, Outlook calendar, OneDrive, Teams, Excel workbooks)
against a fake Microsoft Graph shaped like the documented API — request method, path, query, auth
and body, and how responses are parsed, including the refresh flow. No network or tenant needed.
"""
import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

import tools

calls = []


def ok(body, code=200):
    return httpx.Response(code, json=body)


def graph(request, path, q, body):
    if request.headers.get("authorization") != "Bearer ms-good":
        return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken",
                                                   "message": "Access token validation failure."}})
    mail = {"id": "AAMk1", "subject": "Invoice March", "bodyPreview": "March invoice attached",
            "receivedDateTime": "2026-10-29T10:00:00Z",
            "from": {"emailAddress": {"name": "Billing", "address": "billing@contoso.com"}},
            "toRecipients": [{"emailAddress": {"name": "Ada", "address": "ada@x.dev"}}]}
    if path == "/v1.0/me/messages" and request.method == "GET":
        if "$search" in q:
            assert q["$search"] == '"invoice"'
            assert "$orderby" not in q, "search can't combine with $orderby"
            return ok({"value": [mail], "@odata.count": 1})
        assert q["$orderby"] == "receivedDateTime desc" and q["$top"] == "10"
        return ok({"value": [{**mail, "id": "AAMk2", "subject": "Weekly digest", "bodyPreview": "Everything green"}]})
    if path == "/v1.0/me/messages/AAMk1" and request.method == "GET":
        return ok({**mail, "body": {"contentType": "html", "content": "<p>Monthly total <b>$1,299</b>.</p>"}})
    if path == "/v1.0/me/sendMail" and request.method == "POST":
        assert body["message"]["body"]["contentType"] == "Text"
        assert [r["emailAddress"]["address"] for r in body["message"]["toRecipients"]] == ["boss@x.dev"]
        assert body["saveToSentItems"] is True
        return httpx.Response(202, json={})
    if path == "/v1.0/me/calendarview" and request.method == "GET":
        return ok({"value": [
            {"id": "ev1", "subject": "Standup", "start": {"dateTime": "2026-11-02T09:00:00.0000000", "timeZone": "UTC"},
             "end": {"dateTime": "2026-11-02T09:15:00.0000000", "timeZone": "UTC"},
             "organizer": {"emailAddress": {"address": "ada@x.dev"}}, "webLink": "https://outlook.office.com/ev1"},
            {"id": "ev2", "subject": "Deploy review", "start": {"dateTime": "2026-11-03T15:00:00.0000000", "timeZone": "UTC"},
             "end": {"dateTime": "2026-11-03T16:00:00.0000000", "timeZone": "UTC"}, "organizer": {}}]})
    if path == "/v1.0/me/events" and request.method == "POST":
        assert body["subject"] == "Customer call"
        assert body["start"] == {"dateTime": "2026-11-04T10:00:00.0000000", "timeZone": "UTC"}
        assert body["attendees"][0]["emailAddress"]["address"] == "lead@corp.com"
        return ok({"id": "ev9", "subject": "Customer call", "start": body["start"], "end": body["end"],
                   "webLink": "https://outlook.office.com/ev9"}, 201)
    if path == "/v1.0/me/events/ev2" and request.method == "DELETE":
        return httpx.Response(204)
    if path == "/v1.0/me/joinedTeams":
        return ok({"value": [{"id": "team1", "displayName": "Engineering"}]})
    if path == "/v1.0/teams/team1/channels":
        return ok({"value": [{"id": "chan1", "displayName": "General"}, {"id": "chan2", "displayName": "Incidents"}]})
    if path == "/v1.0/teams/team1/channels/chan1/messages" and request.method == "GET":
        assert q["$top"] == "10"
        return ok({"value": [  # newest first
            {"id": "m2", "createdDateTime": "2026-10-29T10:00:00Z", "from": {"user": {"displayName": "Raj"}},
             "body": {"contentType": "html", "content": "<div>Deploy <b>done</b> ✅</div>"}},
            {"id": "m1", "createdDateTime": "2026-10-29T09:00:00Z", "from": {"user": {"displayName": "Ana"}},
             "body": {"contentType": "text", "content": "Starting deploy"}}]})
    if path == "/v1.0/teams/team1/channels/chan1/messages/m2/replies":
        assert q["$top"] == "15"
        return ok({"value": [{"id": "r1", "createdDateTime": "2026-10-29T10:05:00Z",
                              "from": {"user": {"displayName": "Ana"}}, "body": {"contentType": "text", "content": "🎉"}}]})
    if request.method == "GET" and path.startswith("/v1.0/me/drive/root/search"):
        assert "search(q='report')" in request.url.raw_path.decode(), "free text in the search path"
        return ok({"value": [
            {"id": "f1", "name": "Q3 report.xlsx", "size": 20480, "file": {"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
             "lastModifiedDateTime": "2026-10-28T08:00:00Z"},
            {"id": "fd1", "name": "Reports", "size": 0, "folder": {"childCount": 3}}]})
    if request.method == "GET" and path == "/v1.0/me/drive/recent":
        return ok({"value": [{"id": "f1", "name": "Q3 report.xlsx", "size": 20480,
                              "file": {"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                              "lastModifiedDateTime": "2026-10-28T08:00:00Z"}]})
    if request.method == "GET" and path == "/v1.0/me/drive/root:/Documents/report.txt":
        return ok({"id": "t1", "name": "report.txt"})
    if request.method == "GET" and path == "/v1.0/me/drive/items/f1":
        return ok({"id": "f1", "name": "Q3 report.xlsx", "size": 20480,
                   "file": {"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}})
    if request.method == "GET" and path == "/v1.0/me/drive/items/t1":
        return ok({"id": "t1", "name": "report.txt", "size": 22, "file": {"mimeType": "text/plain"},
                   "webUrl": "https://contoso-my.sharepoint.com/report.txt"})
    if request.method == "GET" and path == "/v1.0/me/drive/items/fd1":
        return ok({"id": "fd1", "name": "Reports", "size": 0, "folder": {"childCount": 2}})
    if request.method == "GET" and path == "/v1.0/me/drive/items/fd1/children":
        return ok({"value": [{"id": "f1", "name": "Q3 report.xlsx", "size": 20480, "file": {"mimeType": "xlsx"}},
                             {"id": "fd2", "name": "Archive", "size": 0, "folder": {"childCount": 0}}]})
    if request.method == "GET" and path == "/v1.0/me/drive/items/t1/content":
        return httpx.Response(200, content=b"October summary:\nEverything is green.\n")
    if request.method == "GET" and path == "/v1.0/me/drive/items/xl1/workbook/worksheets":
        return ok({"value": [{"id": "{a}", "name": "Costs", "position": 0}, {"id": "{b}", "name": "Traffic", "position": 1}]})
    if request.method == "GET" and path == "/v1.0/me/drive/xlpath/workbook/worksheets":  # not used; keeps fake symmetric
        return ok({"value": []})
    if request.method == "GET" and path == "/v1.0/me/drive/items/xl1/workbook/worksheets/Costs/usedRange":
        assert request.url.query.decode() == "valuesOnly=true"
        return ok({"rowCount": 2, "columnCount": 2,
                   "text": [["Item", "Cost"], ["Seats", "12"], ["Domain", "9.99"]], "values": [[None, None], [12], [9.99]]})
    if request.method == "GET" and path == "/v1.0/me/drive/root:/Documents/report.xlsx":
        return ok({"id": "xl1", "name": "report.xlsx"})
    return None


def token(request, path, q, body):
    assert "refresh_token=rt-good;" in str(body) or "refresh_token" in body
    return ok({"token_type": "Bearer", "access_token": "ms-good"})


VENDORS = {"graph.microsoft.com": graph, "login.microsoftonline.com": token}


def handler(request: httpx.Request) -> httpx.Response:
    calls.append(request)
    q = {k: v[0] for k, v in parse_qs(request.url.query.decode(), keep_blank_values=True).items()}
    ctype = request.headers.get("content-type", "")
    body = json.loads(request.content) if request.content and ctype.startswith("application/json") else (
        parse_qs(request.content.decode()) if request.content and ctype.startswith("application/x-www-form-urlencoded") else {})
    res = VENDORS[request.url.host](request, request.url.raw_path.decode().split("?")[0], q, body)
    return res if res is not None else httpx.Response(404, json={"error": {"message": f"unexpected {request.method} {request.url}"}})


@pytest.fixture(autouse=True)
def graph_fix(monkeypatch):
    real = httpx.AsyncClient

    class FakeClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


def run(tool, inp, cfg, args=None):
    calls.clear()
    return asyncio.run(tools.execute(tool, inp, cfg, args))


def test_outlook_mail():
    cfg = {"access_token": "ms-good"}
    out = run("outlook_mail", "list", {**cfg, "action": "list"})
    assert "Weekly digest" in out and "invoice" not in out, "no search = newest first"
    search = run("outlook_mail", "read", {**cfg, "action": "read", "message_id": "AAMk1"})
    assert "[Outlook Mail]" in search and "Billing <billing@contoso.com>" in search and "$1,299" in search
    listed = run("outlook_mail", "list", {**cfg, "action": "list", "query": "invoice"})
    assert "Invoice March" in listed and "1 message(s)" in listed and "AAMk1" in listed
    send = run("outlook_mail", "send", {**cfg, "action": "send", "to": "boss@x.dev",
                                        "subject": "Hi", "message_text": "Confirming"})
    assert send == "[Outlook Mail] Sent 'Hi' to boss@x.dev."
    assert run("outlook_mail", "send", {**cfg, "action": "send", "to": "not-an-email, a@b.co",
                                        "subject": "s", "message_text": "m"}).startswith("[Outlook Mail] These don't")
    assert run("outlook_mail", "read", cfg) == "[Outlook Mail] read needs a message_id — pass the id of a message from list."
    assert run("outlook_mail", "list", {**cfg, "access_token": "expired"}) == \
        "[Outlook Mail] Authentication failed — check the access_token (or refresh_token)."


def test_outlook_calendar():
    cfg = {"access_token": "ms-good"}
    out = run("outlook_calendar", "list", cfg)
    assert "Standup" in out and "2026-11-02T09:00" in out
    assert "Deploy review" in out
    created = run("outlook_calendar", "create", {**cfg, "action": "create", "subject": "Customer call",
                                                 "start": "2026-11-04T10:00:00Z", "attendees": "lead@corp.com"})
    assert created.startswith("[Outlook Calendar] Created event ev9") and "Customer call" in created
    assert run("outlook_calendar", "delete", {**cfg, "action": "delete", "event_id": "ev2"}) == \
        "[Outlook Calendar] Deleted event ev2."
    assert "subject and a start time" in run("outlook_calendar", "create", {**cfg, "action": "create"})
    assert run("outlook_calendar", "delete", cfg).startswith("[Outlook Calendar] delete needs an event_id")


def test_onedrive():
    cfg = {"access_token": "ms-good"}
    out = run("onedrive", "list", cfg)
    assert "Q3 report.xlsx · 20.0 KB" in out and "1 recent drive item(s)" in out
    found = run("onedrive", "", {**cfg, "action": "search", "query": "report"})
    assert "Reports · folder · 3 child(ren)" in found and "Q3 report.xlsx" in found
    run("onedrive", "read", {**cfg, "action": "read", "file_id": "t1"})
    assert calls[0].url.path == "/v1.0/me/drive/items/t1", "metadata first"
    assert calls[1].url.path == "/v1.0/me/drive/items/t1/content"
    read = run("onedrive", "read", {**cfg, "action": "read", "path": "Documents/report.txt"})
    assert "October summary" in read and "Everything is green" in read
    children = run("onedrive", "read", {**cfg, "action": "read", "file_id": "fd1"})
    assert "Q3 report.xlsx" in children, "a folder read lists its children"
    assert run("onedrive", "", {**cfg, "action": "search"}).startswith("[OneDrive] search needs a query")


def test_teams_messages():
    cfg = {"access_token": "ms-good"}
    out = run("teams_messages", "channels", cfg)
    assert "Engineering (team1)" in out and "chan2 · Incidents" in out
    msgs = run("teams_messages", "messages", {**cfg, "action": "messages", "team_id": "team1", "channel_id": "chan1"})
    assert msgs.index("Ana · 2026-10-29 09:00:00") < msgs.index("Raj · 2026-10-29 10:00:00"), "oldest first"
    assert "Deploy done ✅" in msgs, "HTML bodies arrive as readable text"
    replies = run("teams_messages", "", {**cfg, "action": "messages", "team_id": "team1",
                                         "channel_id": "chan1", "message_id": "m2"})
    assert "Ana" in replies and "🎉" in replies
    assert "team_id and channel_id" in run("teams_messages", "messages", cfg)


def test_excel_workbook():
    cfg = {"access_token": "ms-good", "file_id": "xl1"}
    assert run("excel_workbook", "", cfg).startswith("[Excel] 2 sheet(s), in order: 'Costs', 'Traffic'")
    table = run("excel_workbook", "Costs", cfg)
    assert "3 row(s), 2 column(s)" in table and "| Item | Cost |" in table and "| Seats | 12 |" in table
    assert run("excel_workbook", "Costs", {**cfg, "file_id": "", "path": "Documents/report.xlsx"})


def test_refresh_flow():
    cfg = {"access_token": "expired", "refresh_token": "rt-good", "client_id": "cid", "client_secret": "cs"}
    out = run("onedrive", "list", cfg)
    assert "Q3 report.xlsx" in out, "401 → refresh via login.microsoftonline.com → retried once"
    assert any("login.microsoftonline.com" in str(c.url) for c in calls)
