"""FRED, OSV vulnerabilities, Pipedrive, HCP Terraform, Vercel deployments, Dropbox and WhatsApp (2026-11-05)
against a fake HTTP server shaped like each documented API. No network or accounts needed."""
import asyncio
import json

import httpx
import pytest

import tools

calls = []


def handler(request: httpx.Request) -> httpx.Response:  # noqa: C901
    calls.append(request)
    host, path, q, h = request.url.host, request.url.path, request.url.params, request.headers
    if host == "api.stlouisfed.org":
        if q["api_key"] != "fred":
            return httpx.Response(400, json={"error_code": 400, "error_message": "Bad Request.  The value for variable api_key is not registered."})
        assert q["file_type"] == "json"
        if path == "/fred/series/search":
            assert q["search_text"] == "consumer sentiment" and q["order_by"] == "popularity"
            return httpx.Response(200, json={"seriess": [{"id": "UMCSENT", "title": "University of Michigan: Consumer Sentiment",
                                                           "frequency_short": "M", "units_short": "Index 1966:Q1=100",
                                                           "observation_start": "1952-11-01", "observation_end": "2026-09-01"}]})
        if path == "/fred/series":
            if q["series_id"] == "NOPE":
                return httpx.Response(400, json={"error_code": 400, "error_message": "Bad Request.  The series does not exist."})
            return httpx.Response(200, json={"seriess": [{"id": "UNRATE", "title": "Unemployment Rate", "units": "Percent",
                                                           "frequency": "Monthly", "seasonal_adjustment_short": "SA",
                                                           "last_updated": "2026-10-03 07:48:02-05"}]})
        if path == "/fred/series/observations":
            assert q["series_id"] == "UNRATE"
            obs = [{"date": "2026-09-01", "value": "4.3"}, {"date": "2026-08-01", "value": "."}, {"date": "2026-07-01", "value": "4.2"}]
            if q.get("observation_start"):
                assert q["sort_order"] == "asc"
                obs = list(reversed(obs))
            else:
                assert q["sort_order"] == "desc" and q["limit"] == "12"
            return httpx.Response(200, json={"observations": obs})
    if host == "api.osv.dev":
        if path == "/v1/query":
            body = json.loads(request.content)
            if body["package"]["name"] == "safe":
                return httpx.Response(200, json={})
            assert body == {"package": {"name": "@babel/traverse", "ecosystem": "npm"}, "version": "7.22.0"}
            return httpx.Response(200, json={"vulns": [{
                "id": "GHSA-67hx-6x53-jw92", "aliases": ["CVE-2023-45133"], "summary": "Arbitrary code execution in @babel/traverse",
                "database_specific": {"severity": "CRITICAL"},
                "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H"}],
                "affected": [{"package": {"name": "@babel/traverse", "ecosystem": "npm"},
                              "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "7.23.2"}]},
                                         {"type": "SEMVER", "events": [{"introduced": "8.0.0-alpha.0"}, {"fixed": "8.0.0-alpha.4"}]}]},
                             {"package": {"name": "babel-traverse", "ecosystem": "npm"},
                              "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "99"}]}]}]}]})
        if path == "/v1/vulns/CVE-2021-44228":
            return httpx.Response(200, json={"id": "CVE-2021-44228", "summary": "Log4Shell", "details": "JNDI lookup RCE",
                                             "published": "2021-12-10T00:00:00Z", "modified": "2026-01-01T00:00:00Z",
                                             "affected": [{"package": {"name": "org.apache.logging.log4j:log4j-core", "ecosystem": "Maven"},
                                                           "ranges": [{"events": [{"introduced": "2.0"}, {"fixed": "2.15.0"}]}]}]})
        return httpx.Response(404, json={"code": 5, "message": "Bug not found."})
    if host == "acme.pipedrive.com":
        if h.get("x-api-token") != "pd":
            return httpx.Response(401, json={"success": False, "error": "unauthorized"})
        if path == "/api/v2/deals":
            assert q["status"] == "open" and q["sort_by"] == "update_time"
            return httpx.Response(200, json={"success": True, "data": [
                {"id": 7, "title": "Globex renewal", "value": 12000, "currency": "USD", "stage_id": 3,
                 "expected_close_date": "2026-12-01", "update_time": "2026-11-04T10:00:00Z"}]})
        if path == "/api/v2/deals/7":
            return httpx.Response(200, json={"success": True, "data": {"id": 7, "title": "Globex renewal", "status": "open", "value": 12000,
                                                                       "currency": "USD", "stage_id": 3, "probability": 60, "person_id": 5, "org_id": 9}})
        if path == "/api/v2/persons/5":
            return httpx.Response(200, json={"data": {"name": "Hank Scorpio", "emails": [{"value": "hank@globex.com", "primary": True}]}})
        if path == "/api/v2/organizations/9":
            return httpx.Response(200, json={"data": {"name": "Globex"}})
        if path == "/api/v2/itemSearch":
            assert q["term"] == "globex" and q["item_types"] == "deal,person,organization"
            return httpx.Response(200, json={"data": {"items": [
                {"item": {"type": "deal", "id": 7, "title": "Globex renewal", "status": "open", "value": 12000, "currency": "USD",
                          "organization": {"name": "Globex"}}},
                {"item": {"type": "person", "id": 5, "name": "Hank Scorpio", "emails": ["hank@globex.com"], "organization": {"name": "Globex"}}}]}})
        return httpx.Response(404, json={"success": False, "error": "not found"})
    if host == "app.terraform.io":
        if h.get("authorization") != "Bearer tf":
            return httpx.Response(401, json={"errors": [{"status": "401", "title": "unauthorized"}]})
        if path == "/api/v2/organizations/acme/workspaces":
            assert q["include"] == "current_run"
            return httpx.Response(200, json={"data": [
                {"id": "ws-1", "attributes": {"name": "app-prod", "resource-count": 40, "terraform-version": "1.9.5"},
                 "relationships": {"current-run": {"data": {"id": "run-ok", "type": "runs"}}}},
                {"id": "ws-2", "attributes": {"name": "network", "resource-count": 12, "terraform-version": "1.9.5", "locked": True},
                 "relationships": {"current-run": {"data": {"id": "run-bad", "type": "runs"}}}}],
                "included": [{"id": "run-ok", "type": "runs", "attributes": {"status": "applied"}},
                             {"id": "run-bad", "type": "runs", "attributes": {"status": "errored"}}]})
        if path == "/api/v2/organizations/acme/workspaces/network":
            return httpx.Response(200, json={"data": {"id": "ws-2"}})
        if path == "/api/v2/workspaces/ws-2/runs":
            return httpx.Response(200, json={"data": [{"id": "run-bad", "attributes": {
                "status": "errored", "message": "Queued manually", "created-at": "2026-11-05T09:00:00Z"}}]})
        if path == "/api/v2/runs/run-bad":
            assert q["include"] == "plan,apply"
            return httpx.Response(200, json={"data": {"id": "run-bad", "attributes": {"status": "errored", "message": "Queued manually", "source": "tfe-ui"}},
                                             "included": [{"type": "plans", "attributes": {"status": "errored", "resource-additions": 2,
                                                                                           "log-read-url": "https://archivist.terraform.io/v1/object/abc"}}]})
        return httpx.Response(404, json={"errors": [{"status": "404", "title": "not found"}]})
    if host == "archivist.terraform.io":
        assert "authorization" not in h, "the token must not go to the pre-signed log URL"
        return httpx.Response(200, text="Terraform v1.9.5\nError: Invalid provider configuration\n")
    if host == "api.vercel.com":
        if h.get("authorization") != "Bearer vc":
            return httpx.Response(403, json={"error": {"code": "forbidden", "message": "Not authorized"}})
        if path == "/v6/deployments":
            assert q["state"] == "ERROR" and q["projectId"] == "web" and q["teamId"] == "team_1"
            return httpx.Response(200, json={"deployments": [
                {"uid": "dpl_abc", "name": "web", "url": "web-abc.vercel.app", "state": "ERROR", "target": "production",
                 "created": 1762300800000, "meta": {"githubCommitMessage": "fix: build\n\nbody"}}]})
        if path == "/v13/deployments/web-abc.vercel.app":
            return httpx.Response(200, json={"id": "dpl_abc", "name": "web", "url": "web-abc.vercel.app", "readyState": "ERROR",
                                             "createdAt": 1762300800000, "errorCode": "BUILD_FAILED", "errorMessage": "Command \"npm run build\" exited with 1",
                                             "meta": {"githubCommitSha": "abcdef123", "githubCommitMessage": "fix: build", "githubCommitRef": "main"}})
        if path == "/v3/deployments/dpl_abc/events":
            assert q["direction"] == "backward"
            return httpx.Response(200, json=[{"type": "stderr", "text": "Type error: x is not defined"},
                                             {"type": "stdout", "payload": {"text": "Running build"}}])
    if host == "api.dropboxapi.com":
        if path == "/oauth2/token":
            assert request.headers["authorization"].startswith("Basic ") and b"refresh_token=rt" in request.content
            return httpx.Response(200, json={"access_token": "dbx", "expires_in": 14400})
        assert h.get("authorization") == "Bearer dbx"
        body = json.loads(request.content)
        if path == "/2/files/list_folder":
            if body["path"] == "/notes.txt" or body["path"] == "/logo.png":
                return httpx.Response(409, json={"error_summary": "path/not_folder/..", "error": {".tag": "path"}})
            if body["path"] == "/missing":
                return httpx.Response(409, json={"error_summary": "path/not_found/.."})
            assert body["path"] == ""
            return httpx.Response(200, json={"has_more": False, "entries": [
                {".tag": "file", "name": "b.txt", "path_display": "/b.txt", "size": 1200, "server_modified": "2026-11-01T00:00:00Z"},
                {".tag": "folder", "name": "Reports", "path_display": "/Reports"}]})
        if path == "/2/files/search_v2":
            assert body["query"] == "budget"
            return httpx.Response(200, json={"matches": [{"metadata": {".tag": "metadata", "metadata": {
                ".tag": "file", "path_display": "/Reports/budget.xlsx", "size": 5000, "server_modified": "2026-10-01T00:00:00Z"}}}]})
    if host == "content.dropboxapi.com":
        arg = json.loads(request.headers["dropbox-api-arg"])
        if arg["path"] == "/logo.png":
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n\xff\xfe", headers={"dropbox-api-result": json.dumps({"size": 10})})
        return httpx.Response(200, content="héllo notes".encode(), headers={
            "dropbox-api-result": json.dumps({"path_display": "/notes.txt", "server_modified": "2026-11-02T00:00:00Z"})})
    if host == "graph.facebook.com":
        assert path == "/v23.0/1234567/messages" and h["authorization"] == "Bearer wa"
        body = json.loads(request.content)
        assert body["messaging_product"] == "whatsapp" and body["to"] == "919812345678"
        if body["type"] == "text" and body["text"]["body"] == "late":
            return httpx.Response(400, json={"error": {"message": "Re-engagement message", "code": 131047}})
        if body["type"] == "template":
            assert body["template"] == {"name": "order_update", "language": {"code": "en_US"},
                                        "components": [{"type": "body", "parameters": [{"type": "text", "text": "#42 shipped"}]}]}
        return httpx.Response(200, json={"messages": [{"id": "wamid.X1"}]})
    return httpx.Response(599, text=f"unexpected {request.method} {request.url}")


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


def test_fred_reads_a_series_or_searches():
    out = run("fred_economic_data", "unemployment", {"api_key": "fred"})
    assert "UNRATE: Unemployment Rate (Percent, Monthly, SA)" in out and "- 2026-09-01: 4.3" in out
    assert "2026-08-01" not in out, "missing values ('.') are skipped"
    out = run("fred_economic_data", "UNRATE", {"api_key": "fred", "start": "2026-07-01"})
    assert out.index("2026-09-01") < out.index("2026-07-01"), "newest first either way"
    assert "UMCSENT · University of Michigan" in run("fred_economic_data", "consumer sentiment", {"api_key": "fred"})
    assert "series does not exist" in run("fred_economic_data", "NOPE", {"api_key": "fred"})
    assert "check api_key" in run("fred_economic_data", "UNRATE", {"api_key": "bad"})
    assert "start is a date" in run("fred_economic_data", "UNRATE", {"api_key": "fred", "start": "2020"})


def test_osv_package_version_and_advisory():
    out = run("osv_vulnerabilities", "npm:@babel/traverse@7.22.0", {})
    assert "1 known vulnerability affecting npm @babel/traverse 7.22.0" in out
    assert "GHSA-67hx-6x53-jw92 (CVE-2023-45133) · CRITICAL · CVSS:3.1" in out
    assert "Fixed in: 7.23.2, 8.0.0-alpha.4 ·" in out and "99" not in out, "only the queried package's fixes"
    assert "No known vulnerabilities for PyPI safe 1.0" in run("osv_vulnerabilities", "pip:safe@1.0", {})
    out = run("osv_vulnerabilities", "CVE-2021-44228", {})
    assert "Log4Shell" in out and "Maven:org.apache.logging.log4j:log4j-core" in out and "2.15.0" in out
    assert "Unknown ecosystem" in run("osv_vulnerabilities", "cobol:x@1", {})
    assert "No advisory GHSA-nope" in run("osv_vulnerabilities", "GHSA-nope", {})


def test_pipedrive():
    cfg = {"company_domain": "https://acme.pipedrive.com", "api_token": "pd"}
    assert "#7 Globex renewal · 12,000 USD · stage 3 · close 2026-12-01" in run("pipedrive", "", cfg)
    out = run("pipedrive", "#7", cfg)
    assert "Probability: 60" in out and "Contact: Hank Scorpio · hank@globex.com" in out and "Organization: Globex" in out
    out = run("pipedrive", "globex", cfg)
    assert "deal #7 Globex renewal · open · 12,000 USD · Globex" in out and "person #5 Hank Scorpio · hank@globex.com · Globex" in out
    assert "HTTP 401" in run("pipedrive", "", {**cfg, "api_token": "bad"})
    assert "company_domain" in run("pipedrive", "", {"company_domain": "../x", "api_token": "pd"})


def test_terraform_cloud():
    cfg = {"token": "tf", "organization": "acme"}
    out = run("terraform_cloud", "", cfg)
    assert out.index("network") < out.index("app-prod"), "errored workspaces first"
    assert "network · latest run: errored (run-bad) · 12 resources · TF 1.9.5 · locked" in out
    assert "run-bad · errored" in run("terraform_cloud", "network", cfg)
    out = run("terraform_cloud", "run-bad", cfg)
    assert "Plan: errored · +2 ~0 -0" in out and "Error: Invalid provider configuration" in out
    assert "Input is a workspace name" in run("terraform_cloud", "a b/c", cfg)
    assert "HTTP 401" in run("terraform_cloud", "", {**cfg, "token": "bad"})


def test_vercel_deployments():
    cfg = {"token": "vc", "team_id": "team_1"}
    out = run("vercel_deployments", "web", cfg)
    assert "1 recent error deployment(s) of web" in out and "dpl_abc · web · ERROR · production · 2025-11-05" in out
    assert "fix: build" in out and "body" not in out
    out = run("vercel_deployments", "https://web-abc.vercel.app", cfg)
    assert "Error: BUILD_FAILED" in out and "Commit: abcdef1 fix: build (main)" in out
    assert out.index("Running build") < out.index("Type error"), "log in time order"
    assert "state is one of" in run("vercel_deployments", "", {**cfg, "state": "weird"})
    assert "HTTP 403" in run("vercel_deployments", "web", {**cfg, "token": "bad"})


def test_dropbox_refreshes_then_lists_reads_and_searches():
    cfg = {"refresh_token": "rt", "app_key": "k", "app_secret": "s"}
    out = run("dropbox", "/", cfg)
    assert out.index("📁 /Reports/") < out.index("/b.txt · 1,200 bytes"), "folders first"
    assert calls[0].url.path == "/oauth2/token"
    out = run("dropbox", "/notes.txt", cfg)
    assert "héllo notes" in out and "/notes.txt · modified 2026-11-02" in out
    assert "binary file" in run("dropbox", "/logo.png", cfg)
    assert "/Reports/budget.xlsx · 5,000 bytes" in run("dropbox", "budget", cfg)
    assert "Not found" in run("dropbox", "/missing", cfg)
    assert "app_key and app_secret" in run("dropbox", "/", {"refresh_token": "rt"})
    assert "/b.txt" in run("dropbox", "/", {"access_token": "dbx"})


def test_whatsapp_text_template_and_window():
    cfg = {"access_token": "wa", "phone_number_id": "1234567", "to": "+91 98123 45678"}
    assert "Sent message to +919812345678 (wamid.X1)" in run("whatsapp_cloud", "hello", cfg)
    assert "only a template" in run("whatsapp_cloud", "late", cfg)
    assert "Sent template order_update" in run("whatsapp_cloud", "#42 shipped", {**cfg, "template_name": "order_update"})
    assert "4096" in run("whatsapp_cloud", "x" * 4097, cfg)
    assert "phone number" in run("whatsapp_cloud", "hi", {**cfg, "to": "abc"})


def test_whatsapp_recipient_is_not_a_model_argument():
    tools._load()
    entry = next(t for s in tools.catalog() for t in s["tools"] if t["id"] == "whatsapp_cloud")
    assert set(entry["parameters"]["properties"]) == {"message"}


@pytest.mark.parametrize("tool_id,category", [
    ("fred_economic_data", "Research & Knowledge"), ("osv_vulnerabilities", "Code & Compute"),
    ("pipedrive", "Business Apps"), ("terraform_cloud", "APIs & Integrations"),
    ("vercel_deployments", "APIs & Integrations"), ("dropbox", "Productivity"), ("whatsapp_cloud", "Communication"),
])
def test_catalog(tool_id, category):
    tools._load()
    entry = next(t for s in tools.catalog() if s["id"] == "agentic_tools" for t in s["tools"] if t["id"] == tool_id)
    assert entry["category"] == category and entry["parameters"]["type"] == "object"
