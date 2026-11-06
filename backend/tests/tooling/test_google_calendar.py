"""Google Calendar tool — list / create / delete events against a fake Google Calendar API server."""
import asyncio
import json

import httpx
import pytest

import tools

calls = []


def handler(request: httpx.Request) -> httpx.Response:
    calls.append(request)
    host, path = request.url.host, request.url.path
    if host == "oauth2.googleapis.com":
        return httpx.Response(200, json={"access_token": "fresh-token", "expires_in": 3600, "token_type": "Bearer"})
    if host == "www.googleapis.com":
        auth = request.headers.get("authorization") or ""
        if path == "/calendar/v3/calendars/primary/events" and request.method == "GET":
            if auth != "Bearer fresh-token":
                return httpx.Response(401, json={"error": {"code": 401, "message": "expired token"}})
            return httpx.Response(200, json={"items": [{
                "id": "evt1", "summary": "Deploy", "status": "confirmed",
                "start": {"dateTime": "2026-11-01T09:00:00Z", "timeZone": "UTC"},
                "end": {"dateTime": "2026-11-01T10:00:00Z", "timeZone": "UTC"},
                "htmlLink": "https://cal/evt1", "description": "Ship it.",
            }]})
        if path == "/calendar/v3/calendars/primary/events" and request.method == "POST":
            return httpx.Response(201, json={"id": "evt-new", "summary": "Deploy", "status": "confirmed",
                                            "htmlLink": "https://cal/evt-new"})
        if path.startswith("/calendar/v3/calendars/primary/events/") and request.method == "DELETE":
            return httpx.Response(204)
        if path.startswith("/calendar/v3/calendars/primary/events/"):
            return httpx.Response(404, json={"error": {"code": 404, "message": "nope"}})
    return httpx.Response(599, json={"error": f"unexpected request {request.method} {request.url}"})


@pytest.fixture
def vendors(monkeypatch):
    real = httpx.AsyncClient

    class FakeClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


def run(tool, inp, cfg):
    calls.clear()
    return asyncio.run(tools.execute(tool, inp, cfg))


CAL = {"access_token": "fresh-token", "calendar_id": "primary"}


def test_list(vendors):
    out = run("google_calendar", "list", {**CAL, "time_min": "2026-11-01T00:00:00Z", "time_max": "2026-11-30T00:00:00Z"})
    assert calls[0].method == "GET"
    assert calls[0].url.path == "/calendar/v3/calendars/primary/events"
    assert "evt1" in out and "Deploy" in out and "https://cal/evt1" in out


def test_create(vendors):
    out = run("google_calendar", "create", {**CAL, "summary": "Deploy", "start": "2026-11-01T09:00:00Z", "end": "2026-11-01T10:00:00Z"})
    assert calls[0].method == "POST"
    sent = json.loads(calls[0].content)
    assert sent["summary"] == "Deploy"
    assert sent["start"] == {"dateTime": "2026-11-01T09:00:00Z", "timeZone": "UTC"}
    assert sent["end"] == {"dateTime": "2026-11-01T10:00:00Z", "timeZone": "UTC"}
    assert "Created event evt-new" in out


def test_create_needs_summary_and_start(vendors):
    assert "summary" in run("google_calendar", "create", {**CAL, "start": "2026-11-01T09:00:00Z"})


def test_delete(vendors):
    out = run("google_calendar", "delete", {**CAL, "event_id": "evt1"})
    assert calls[0].method == "DELETE"
    assert "Deleted event evt1" in out


def test_delete_needs_event_id(vendors):
    assert "event_id" in run("google_calendar", "delete", {**CAL})


def test_missing_access_token():
    out = asyncio.run(tools.execute("google_calendar", "list", {}))
    assert "access_token" in out and "required in config" in out


def test_token_refresh(vendors):
    out = asyncio.run(tools.execute("google_calendar", "list", {
        "access_token": "expired-token", "refresh_token": "r", "client_id": "cid", "client_secret": "cs"}))
    assert calls[0].headers["authorization"] == "Bearer expired-token"
    assert calls[2].headers["authorization"] == "Bearer fresh-token", "retried with the refreshed token"
    assert "evt1" in out
