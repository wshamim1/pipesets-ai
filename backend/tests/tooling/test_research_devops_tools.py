"""Semantic Scholar, Crossref, SEC EDGAR, GitLab, Sentry, Prometheus, ClickUp and Pushover against a fake
HTTP server shaped like each vendor's documented API (method, path, query, auth, body), plus the
offline cron helper and XML ↔ JSON converter. No network or vendor accounts needed.
"""
import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

import tools

calls = []


def handler(request: httpx.Request) -> httpx.Response:
    calls.append(request)
    host, path, q, h = request.url.host, request.url.path, request.url.params, request.headers

    if host == "api.semanticscholar.org" and path == "/graph/v1/paper/search":
        assert q["query"] == "rent control" and q["limit"] == "2" and q.get("year") == "2020-2024"
        return httpx.Response(200, json={"data": [{
            "title": "Rent Control and Housing Supply", "year": 2021, "venue": "AER", "citationCount": 88,
            "authors": [{"name": "A. Diamond"}], "url": "https://www.semanticscholar.org/paper/abc",
            "externalIds": {"DOI": "10.1257/aer.1"}, "openAccessPdf": {"url": "https://x/paper.pdf"},
            "abstract": "We study rent control."}]})

    if host == "api.crossref.org":
        if path == "/works/10.1257/aer.1":
            return httpx.Response(200, json={"message": {
                "DOI": "10.1257/aer.1", "title": ["Rent Control"], "type": "journal-article",
                "author": [{"given": "Rebecca", "family": "Diamond"}], "container-title": ["AER"],
                "issued": {"date-parts": [[2019, 9]]}, "is-referenced-by-count": 300, "publisher": "AEA",
                "abstract": "<jats:p>Effects of rent control.</jats:p>"}})
        if path == "/works/10.9999/missing":
            return httpx.Response(404, text="Resource not found.")
        if path == "/works":
            assert q["query.bibliographic"] == "rent control diamond" and q["mailto"] == "me@x.org"
            assert "mailto:me@x.org" in h["user-agent"]
            return httpx.Response(200, json={"message": {"items": [{"DOI": "10.1/a", "title": ["A"], "type": "journal-article"}]}})

    if host in ("www.sec.gov", "data.sec.gov"):
        if h.get("user-agent") != "Acme ops@acme.com":
            return httpx.Response(403, text="Undeclared automated tool")
        if path == "/files/company_tickers.json":
            return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})
        if path == "/submissions/CIK0000320193.json":
            return httpx.Response(200, json={"name": "Apple Inc.", "tickers": ["AAPL"], "filings": {"recent": {
                "form": ["8-K", "10-Q", "10-K"], "filingDate": ["2026-10-30", "2026-08-01", "2025-11-01"],
                "accessionNumber": ["0000320193-26-000100", "0000320193-26-000080", "0000320193-25-000079"],
                "primaryDocument": ["a8k.htm", "a10q.htm", "a10k.htm"],
                "primaryDocDescription": ["8-K", "10-Q", "Annual report"]}}})

    if host == "gitlab.example.com":
        if h.get("private-token") != "glpat":
            return httpx.Response(401, json={"message": "401 Unauthorized"})
        if request.url.raw_path.startswith(b"/api/v4/projects/grp%2Fsub%2Fapp/merge_requests"):
            assert q["state"] == "opened"
            return httpx.Response(200, json=[{"iid": 7, "title": "Fix login", "source_branch": "fix",
                                              "target_branch": "main", "author": {"username": "ana"}}])
        if request.url.raw_path == b"/api/v4/projects/grp%2Fsub%2Fapp":
            return httpx.Response(200, json={"path_with_namespace": "grp/sub/app", "star_count": 3, "forks_count": 1,
                                             "default_branch": "main", "web_url": "https://gitlab.example.com/grp/sub/app"})
        return httpx.Response(404, json={"message": "404 Project Not Found"})

    if host == "sentry.io":
        if h.get("authorization") != "Bearer sntrys":
            return httpx.Response(401, json={"detail": "Invalid token"})
        if path == "/api/0/organizations/acme/issues/":
            assert q["query"] == "is:unresolved TypeError" and q["statsPeriod"] == "14d"
            return httpx.Response(200, json=[{"id": "42", "shortId": "WEB-1A", "title": "TypeError: x is undefined",
                                              "level": "error", "count": "120", "userCount": 9,
                                              "lastSeen": "2026-11-03T10:00:00Z", "permalink": "https://acme.sentry.io/issues/42/"}])
        if path == "/api/0/projects/acme/web/issues/":
            assert q["query"] == "is:resolved"
            return httpx.Response(200, json=[])
        if path == "/api/0/organizations/acme/issues/42/":
            return httpx.Response(200, json={"shortId": "WEB-1A", "title": "TypeError: x is undefined", "status": "unresolved",
                                             "level": "error", "count": "120", "userCount": 9, "project": {"slug": "web"},
                                             "culprit": "app/checkout.js", "permalink": "https://acme.sentry.io/issues/42/"})
        if path == "/api/0/organizations/acme/issues/42/events/latest/":
            return httpx.Response(200, json={"entries": [{"type": "exception", "data": {"values": [{
                "type": "TypeError", "value": "x is undefined",
                "stacktrace": {"frames": [{"function": "pay", "filename": "checkout.js", "lineNo": 12}]}}]}}]})

    if host == "prom.local":
        assert h.get("authorization") == "Bearer promtok"
        if path == "/api/v1/query":
            if q["query"] == "bad(":
                return httpx.Response(400, json={"status": "error", "errorType": "bad_data", "error": "parse error"})
            return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": [
                {"metric": {"__name__": "up", "job": "api"}, "value": [1730000000, "1"]}]}})
        if path == "/api/v1/query_range":
            assert float(q["end"]) - float(q["start"]) == 3600 and q["step"] == "30"
            return httpx.Response(200, json={"status": "success", "data": {"resultType": "matrix", "result": [
                {"metric": {"job": "api"}, "values": [[1, "0.5"], [2, "2.25"], [3, "1"]]}]}})

    if host == "api.clickup.com":
        if h.get("authorization") != "pk_1":
            return httpx.Response(401, json={"err": "Token invalid", "ECODE": "OAUTH_025"})
        if path == "/api/v2/list/900/task" and request.method == "GET":
            return httpx.Response(200, json={"tasks": [
                {"id": "86abc123", "name": "Fix invoice PDF", "status": {"status": "in progress"},
                 "assignees": [{"username": "ana"}], "url": "https://app.clickup.com/t/86abc123"},
                {"id": "86abc999", "name": "Plan offsite", "status": {"status": "to do"}, "url": "https://app.clickup.com/t/86abc999"}]})
        if path == "/api/v2/list/900/task" and request.method == "POST":
            body = json.loads(request.content)
            assert body == {"name": "Ship it", "description": "Before Friday"}
            return httpx.Response(200, json={"id": "86new001", "name": "Ship it", "url": "https://app.clickup.com/t/86new001"})
        if path == "/api/v2/task/86abc123":
            return httpx.Response(200, json={"id": "86abc123", "name": "Fix invoice PDF", "status": {"status": "in progress"},
                                             "list": {"name": "Billing"}, "text_content": "Totals are wrong.",
                                             "url": "https://app.clickup.com/t/86abc123"})
        if path == "/api/v2/task/86abc123/comment":
            return httpx.Response(200, json={"comments": [{"user": {"username": "raj"}, "comment_text": "On it"}]})

    if host == "api.pushover.net" and path == "/1/messages.json":
        form = parse_qs(request.content.decode())
        if form["token"] != ["app1"]:
            return httpx.Response(400, json={"status": 0, "errors": ["application token is invalid"]})
        assert form["user"] == ["u1"] and form["message"] == ["Deploy done"] and form["priority"] == ["1"]
        return httpx.Response(200, json={"status": 1, "request": "r1"})

    return httpx.Response(599, json={"error": f"unexpected request {request.method} {request.url}"})


@pytest.fixture(autouse=True)
def vendors(monkeypatch):
    """Every httpx.AsyncClient talks to the fake vendor APIs above."""
    real = httpx.AsyncClient

    class FakeClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


def run(tool, inp, cfg, args=None):
    calls.clear()
    return asyncio.run(tools.execute(tool, inp, cfg, args))


def test_semantic_scholar():
    out = run("semantic_scholar_search", "", {}, {"query": "rent control", "max_results": 2, "year": "2020-2024"})
    assert "Rent Control and Housing Supply" in out and "88 citations" in out
    assert "https://x/paper.pdf" in out and "DOI: 10.1257/aer.1" in out
    assert "x-api-key" not in calls[0].headers
    run("semantic_scholar_search", "rent control", {"api_key": "s2", "max_results": 2, "year": "2020-2024"})
    assert calls[0].headers["x-api-key"] == "s2"


def test_crossref_doi_and_search():
    out = run("crossref_search", "https://doi.org/10.1257/aer.1", {})
    assert "Rent Control" in out and "Rebecca Diamond" in out and "2019-09" in out and "Effects of rent control." in out
    assert "No work with DOI 10.9999/missing" in run("crossref_search", "10.9999/missing", {})
    out = run("crossref_search", "rent control diamond", {"mailto": "me@x.org"})
    assert out.startswith("[Crossref] 1 work(s)")


def test_sec_edgar():
    cfg = {"user_agent": "Acme ops@acme.com"}
    out = run("sec_edgar_filings", "aapl", cfg)
    assert "Apple Inc. (CIK 320193, AAPL)" in out
    assert "https://www.sec.gov/Archives/edgar/data/320193/000032019326000100/a8k.htm" in out
    out = run("sec_edgar_filings", "", cfg, {"company": "320193", "form_type": "10-k"})
    assert "Annual report" in out and "8-K" not in out.split("\n", 1)[1]
    assert "refused" in run("sec_edgar_filings", "AAPL", {"user_agent": "bot"})
    assert "user_agent is required" in run("sec_edgar_filings", "AAPL", {})


def test_gitlab():
    cfg = {"base_url": "https://gitlab.example.com/", "token": "glpat"}
    out = run("gitlab_api", "https://gitlab.example.com/grp/sub/app/-/issues", cfg)
    assert "grp/sub/app" in out and "Stars       : 3" in out
    out = run("gitlab_api", "grp/sub/app.git", {**cfg, "action": "merge_requests"})
    assert "!7 Fix login (fix → main) — ana" in out
    assert "not found" in run("gitlab_api", "grp/other", cfg)
    assert "token is invalid" in run("gitlab_api", "grp/sub/app", {**cfg, "token": "nope"})


def test_sentry():
    cfg = {"auth_token": "sntrys", "organization": "acme"}
    out = run("sentry_issues", "TypeError", cfg)
    assert "42 WEB-1A: TypeError: x is undefined" in out and "120 events" in out
    assert "No issues match 'is:resolved'" in run("sentry_issues", "is:resolved", {**cfg, "project": "web"})
    out = run("sentry_issues", "42", cfg)
    assert "Culprit: app/checkout.js" in out and "at pay (checkout.js:12)" in out
    assert "auth_token is invalid" in run("sentry_issues", "x", {**cfg, "auth_token": "bad"})


def test_prometheus():
    cfg = {"base_url": "http://prom.local/", "bearer_token": "promtok"}
    assert '- up{job="api"}: 1' in run("prometheus_query", "up", cfg)
    out = run("prometheus_query", "", cfg, {"query": "rate(x[5m])", "lookback": "1h"})
    assert "last 1h" in out and "min 0.5 · max 2.25 · last 1" in out
    assert "bad_data: parse error" in run("prometheus_query", "bad(", cfg)
    assert "lookback is a duration" in run("prometheus_query", "up", {**cfg, "lookback": "soon"})
    assert not calls, "a bad lookback is caught before any request"


def test_clickup():
    cfg = {"api_token": "pk_1", "list_id": "900"}
    out = run("clickup", "invoice", cfg)
    assert "#86abc123 Fix invoice PDF · in progress · ana" in out and "Plan offsite" not in out
    out = run("clickup", "#86abc123", cfg)
    assert "List: Billing" in out and "Totals are wrong." in out and "- raj: On it" in out
    assert "Created #86new001" in run("clickup", "create: Ship it\nBefore Friday", cfg)
    assert "Set list_id" in run("clickup", "anything", {"api_token": "pk_1"})
    assert "api_token is invalid" in run("clickup", "x", {**cfg, "api_token": "bad"})


def test_pushover():
    cfg = {"app_token": "app1", "user_key": "u1", "priority": "high"}
    assert run("pushover_notify", "Deploy done", cfg) == "[Pushover] Notification sent."
    assert "application token is invalid" in run("pushover_notify", "Deploy done", {**cfg, "app_token": "x"})
    assert "Priority is one of" in run("pushover_notify", "hi", {**cfg, "priority": "panic"})


def test_cron_helper():
    out = run("cron_helper", "*/15 9-17 * * 1-5", {"timezone": "Europe/Berlin", "count": 3})
    assert "every 15 minutes" in out and "9 through 17" in out and "Mon through Fri" in out
    runs = [line for line in out.splitlines() if line.startswith("  ") and ":" in line and "CE" in line]
    assert len(runs) == 3
    assert "(= 0 0 * * *)" in run("cron_helper", "@daily", {})
    assert "5 fields" in run("cron_helper", "* * *", {})
    assert "Invalid cron expression" in run("cron_helper", "99 * * * *", {})
    assert "Unknown timezone" in run("cron_helper", "0 9 * * *", {"timezone": "Mars/Base"})


def test_xml_converter_round_trip():
    xml = '<order id="7"><item sku="a">Pen</item><item sku="b">Ink</item><note>rush</note></order>'
    data = json.loads(run("xml_converter", xml, {}))
    assert data == {"order": {"@id": "7", "item": [{"@sku": "a", "#text": "Pen"}, {"@sku": "b", "#text": "Ink"}], "note": "rush"}}
    back = run("xml_converter", json.dumps(data), {})
    assert back.startswith('<order id="7">') and back.count("<item") == 2 and "<note>rush</note>" in back
    assert run("xml_converter", "[1, 2]", {"root_tag": "nums"}).replace(" ", "").replace("\n", "") == \
        "<nums><item>1</item><item>2</item></nums>"


def test_xml_converter_refuses_entities_and_bad_tags():
    bomb = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><l>&b;</l>'
    assert "DOCTYPE and ENTITY declarations aren't supported" in run("xml_converter", bomb, {})
    assert "isn't a valid XML tag name" in run("xml_converter", '{"bad tag": 1}', {})
    assert "Invalid XML" in run("xml_converter", "<a><b></a>", {})
