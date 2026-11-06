"""dbt Cloud, Fivetran, Airbyte, Prefect, Kubernetes, GitHub Actions and Service Status against a fake HTTP
server shaped like each vendor's documented API (method, path, query, auth, body). No network or vendor
accounts needed."""
import asyncio
import base64
import json

import httpx
import pytest

import tools

calls = []


def handler(request: httpx.Request) -> httpx.Response:  # noqa: C901 — one fake server for every vendor
    calls.append(request)
    host, path, q, h = request.url.host, request.url.path, request.url.params, request.headers

    if host == "cloud.getdbt.com":
        if h.get("authorization") != "Token dbtok":
            return httpx.Response(401, json={"status": {"is_success": False}})
        acc = "/api/v2/accounts/42"
        if path == f"{acc}/runs/" and request.method == "GET":
            assert q["order_by"] == "-id" and q.get("job_definition_id") == "7"
            return httpx.Response(200, json={"data": [
                {"id": 900, "status": 20, "status_humanized": "Error", "job_definition_id": 7, "job": {"name": "nightly"},
                 "finished_at": "2026-11-04T02:10:00Z", "duration_humanized": "4 minutes"}]})
        if path == f"{acc}/runs/900/":
            assert "run_steps" in q["include_related"]
            return httpx.Response(200, json={"data": {
                "id": 900, "status": 20, "status_humanized": "Error", "job": {"name": "nightly"},
                "started_at": "2026-11-04T02:06:00Z", "duration_humanized": "4 minutes", "git_branch": "main",
                "href": "https://cloud.getdbt.com/#/runs/900",
                "run_steps": [{"name": "dbt deps", "status": 10, "status_humanized": "Success", "logs": "ok"},
                              {"name": "dbt build", "status": 20, "status_humanized": "Error",
                               "logs": "Database Error in model orders\n  column \"customer_id\" does not exist"}]}})
        if path == f"{acc}/runs/404/":
            return httpx.Response(404, json={})
        if path == f"{acc}/jobs/":
            return httpx.Response(200, json={"data": [{"id": 7, "name": "nightly", "state": 1,
                                                       "triggers": {"schedule": True}, "schedule": {"cron": "0 2 * * *"}}]})
        if path == f"{acc}/jobs/7/run/" and request.method == "POST":
            assert json.loads(request.content)["cause"]
            return httpx.Response(200, json={"data": {"id": 901, "status": 1, "status_humanized": "Queued", "href": "h"}})

    if host == "api.fivetran.com":
        if h.get("authorization") != "Basic " + base64.b64encode(b"fk:fs").decode():
            return httpx.Response(401, json={"code": "AuthFailed"})
        assert h.get("accept") == "application/json;version=2"
        if path == "/v1/connections":
            assert q.get("group_id") == "grp"
            return httpx.Response(200, json={"data": {"items": [
                {"id": "ok_1", "schema": "salesforce", "service": "salesforce", "paused": False,
                 "status": {"setup_state": "connected", "sync_state": "scheduled"},
                 "succeeded_at": "2026-11-04T01:00:00Z", "failed_at": None},
                {"id": "bad_1", "schema": "stripe", "service": "stripe", "paused": False,
                 "status": {"setup_state": "connected", "sync_state": "scheduled"},
                 "succeeded_at": "2026-11-01T01:00:00Z", "failed_at": "2026-11-04T01:00:00Z"}]}})
        if path == "/v1/connections/bad_1":
            return httpx.Response(200, json={"data": {
                "id": "bad_1", "schema": "stripe", "service": "stripe", "paused": False, "sync_frequency": 60,
                "succeeded_at": "2026-11-01T01:00:00Z", "failed_at": "2026-11-04T01:00:00Z",
                "status": {"setup_state": "broken", "sync_state": "scheduled", "update_state": "delayed",
                           "tasks": [{"code": "reconnect", "message": "Reauthorize the Stripe account"}], "warnings": []}}})
        if path == "/v1/connections/nope":
            return httpx.Response(404, json={"code": "NotFound"})

    if host == "api.airbyte.com":
        if h.get("authorization") != "Bearer abtok":
            return httpx.Response(401, json={})
        if path == "/v1/connections":
            return httpx.Response(200, json={"data": [{"connectionId": "c-1", "name": "PG → BQ", "status": "active",
                                                       "schedule": {"scheduleType": "cron"}}]})
        if path == "/v1/jobs":
            assert q["connectionId"] == "c-1" and q["orderBy"] == "createdAt|DESC" and q["status"] == "failed"
            return httpx.Response(200, json={"data": [{"jobId": 55, "jobType": "sync", "status": "failed",
                                                       "startTime": "2026-11-04T03:00:00Z", "duration": "PT4M",
                                                       "rowsSynced": 0, "bytesSynced": 0}]})

    if host == "prefect.example":
        assert h.get("authorization") == "Bearer pfkey"
        if path == "/api/flow_runs/filter":
            body = json.loads(request.content)
            assert body["sort"] == "START_TIME_DESC" and body["flow_runs"]["state"]["type"]["any_"] == ["FAILED", "CRASHED"]
            return httpx.Response(200, json=[{"id": "fr-1", "name": "brave-otter", "state_name": "Failed",
                                              "start_time": "2026-11-04T04:00:00Z"}])
        if path == "/api/flow_runs/fr-1":
            return httpx.Response(200, json={"id": "fr-1", "name": "brave-otter", "state_name": "Crashed",
                                             "start_time": "2026-11-04T04:00:00Z", "end_time": "2026-11-04T04:01:00Z",
                                             "total_run_time": 61.2, "state": {"message": "Worker died: OOMKilled"}})
        if path == "/api/logs/filter":
            body = json.loads(request.content)
            assert body["logs"]["flow_run_id"]["any_"] == ["fr-1"] and body["sort"] == "TIMESTAMP_DESC"
            return httpx.Response(200, json=[{"timestamp": "2026-11-04T04:01:00Z", "message": "Process exited 137"},
                                             {"timestamp": "2026-11-04T04:00:30Z", "message": "Loading 9M rows"}])

    if host == "k8s.example":
        if h.get("authorization") != "Bearer k8stok":
            return httpx.Response(401, json={})
        if path == "/api/v1/namespaces/prod/pods":
            return httpx.Response(200, json={"items": [
                {"metadata": {"name": "web-1"}, "status": {"phase": "Running", "containerStatuses": [
                    {"ready": True, "restartCount": 0, "state": {"running": {}}}]}},
                {"metadata": {"name": "api-7"}, "status": {"phase": "Running", "containerStatuses": [
                    {"ready": False, "restartCount": 12, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}}]})
        if path == "/api/v1/namespaces/prod/pods/api-7/log":
            assert q["tailLines"] == "200" and q.get("previous") == "true" and q.get("container") == "app"
            return httpx.Response(200, text="panic: missing DATABASE_URL\n")
        if path == "/api/v1/namespaces/prod/events":
            return httpx.Response(200, json={"items": [
                {"metadata": {"name": "e1"}, "type": "Normal", "reason": "Pulled", "message": "pulled",
                 "lastTimestamp": "2026-11-04T05:00:00Z", "involvedObject": {"kind": "Pod", "name": "web-1"}},
                {"metadata": {"name": "e2"}, "type": "Warning", "reason": "BackOff", "message": "Back-off restarting",
                 "count": 12, "lastTimestamp": "2026-11-04T04:00:00Z", "involvedObject": {"kind": "Pod", "name": "api-7"}}]})
        if path == "/apis/apps/v1/namespaces/prod/deployments":
            return httpx.Response(200, json={"items": [{"metadata": {"name": "api"}, "spec": {"replicas": 3},
                                                        "status": {"readyReplicas": 1, "updatedReplicas": 3}}]})
        if path == "/api/v1/namespaces/locked/pods":
            return httpx.Response(403, json={})

    if host == "api.github.com":
        assert h.get("x-github-api-version") == "2022-11-28"
        if path == "/repos/acme/web/actions/runs":
            assert q["status"] == "failure" and q.get("branch") == "main"
            return httpx.Response(200, json={"workflow_runs": [{"id": 77, "name": "CI", "conclusion": "failure",
                                                                "head_branch": "main", "created_at": "2026-11-04T06:00:00Z",
                                                                "head_commit": {"message": "Bump deps\n\nbody"}}]})
        if path == "/repos/acme/web/actions/runs/77":
            return httpx.Response(200, json={"id": 77, "name": "CI", "conclusion": "failure", "head_branch": "main",
                                             "head_sha": "abcdef123", "event": "push", "html_url": "https://github.com/acme/web/actions/runs/77"})
        if path == "/repos/acme/web/actions/runs/77/jobs":
            return httpx.Response(200, json={"jobs": [
                {"id": 1, "name": "lint", "conclusion": "success", "steps": []},
                {"id": 2, "name": "test", "conclusion": "failure",
                 "steps": [{"number": 4, "name": "pytest", "conclusion": "failure"}]}]})
        if path == "/repos/acme/web/actions/jobs/2/logs":
            if h.get("authorization") != "Bearer ghtok":
                return httpx.Response(403, json={})
            return httpx.Response(302, headers={"location": "https://logs.example/job2.txt"})
        if path == "/repos/acme/missing/actions/runs":
            return httpx.Response(404, json={})
    if host == "logs.example":
        return httpx.Response(200, text="collected 120 items\nFAILED tests/test_api.py::test_login - AssertionError")

    if host == "www.githubstatus.com" and path == "/api/v2/summary.json":
        return httpx.Response(200, json={
            "page": {"name": "GitHub"}, "status": {"description": "Partial System Outage"},
            "components": [{"name": "Actions", "status": "major_outage"}, {"name": "Git", "status": "operational"}],
            "incidents": [{"name": "Delayed Actions runs", "status": "investigating", "impact": "major",
                           "started_at": "2026-11-04T07:00:00Z", "shortlink": "https://stspg.io/x",
                           "incident_updates": [{"body": "We are\n investigating."}]}],
            "scheduled_maintenances": []})
    if host == "status.example.com":
        return httpx.Response(404, text="<html>nope</html>", headers={"content-type": "text/html"})
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


def test_dbt_cloud():
    cfg = {"account_id": "42", "api_token": "dbtok"}
    out = run("dbt_cloud", "7", cfg)
    assert "run 900 · nightly · Error" in out and "4 minutes" in out
    out = run("dbt_cloud", "900", {**cfg, "action": "run"})
    assert "dbt build: Error" in out and 'column "customer_id" does not exist' in out
    assert "dbt deps: Success" in out and "Log (end)" in out.split("dbt build")[1], "logs only for the failed step"
    assert "0 2 * * *" in run("dbt_cloud", "", {**cfg, "action": "jobs"})
    assert "run 901 is Queued" in run("dbt_cloud", "7", {**cfg, "action": "trigger"}) and calls[0].method == "POST"
    assert "Not found" in run("dbt_cloud", "404", {**cfg, "action": "run"})
    assert "run id" in run("dbt_cloud", "", {**cfg, "action": "run"})
    assert "HTTP 401" in run("dbt_cloud", "7", {**cfg, "api_token": "bad"})
    assert "required" in run("dbt_cloud", "7", {})


def test_dbt_cloud_typed_call():
    out = run("dbt_cloud", "", {"account_id": "42", "api_token": "dbtok"}, {"id": "900", "action": "run"})
    assert "Run 900" in out


def test_fivetran():
    cfg = {"api_key": "fk", "api_secret": "fs", "group_id": "grp"}
    out = run("fivetran", "", cfg)
    lines = out.splitlines()
    assert "2 connection(s)" in lines[0] and "bad_1 · stripe (stripe) · FAILING" in lines[1], "failing first"
    out = run("fivetran", "bad_1", cfg)
    assert "stripe (stripe) · BROKEN" in out and "Task: reconnect — Reauthorize the Stripe account" in out
    assert "Last failure: 2026-11-04 01:00" in out
    assert "not found" in run("fivetran", "nope", cfg)
    assert "HTTP 401" in run("fivetran", "", {**cfg, "api_secret": "x"})


def test_airbyte():
    cfg = {"access_token": "abtok"}
    assert "c-1 · PG → BQ · active · cron" in run("airbyte", "", cfg)
    out = run("airbyte", "c-1", {**cfg, "status": "failed"})
    assert "job 55 · sync · failed" in out and "0 rows" in out
    assert "status is one of" in run("airbyte", "c-1", {**cfg, "status": "weird"})
    assert "access_token" in run("airbyte", "", {"access_token": "bad"})


def test_prefect():
    cfg = {"api_url": "http://prefect.example/api/", "api_key": "pfkey"}
    assert "fr-1 · brave-otter · Failed" in run("prefect", "", cfg)
    out = run("prefect", "fr-1", cfg)
    assert "brave-otter (fr-1) · Crashed" in out and "Worker died: OOMKilled" in out and "Runtime: 61s" in out
    assert out.index("Loading 9M rows") < out.index("Process exited 137"), "log lines oldest first"
    assert "api_url is required" in run("prefect", "", {})


def test_kubernetes():
    cfg = {"api_url": "https://k8s.example", "token": "k8stok", "namespace": "prod"}
    out = run("kubernetes", "", cfg)
    lines = out.splitlines()
    assert "api-7 · Running · 0/1 ready · 12 restarts · CrashLoopBackOff" in lines[1], "unready pods first"
    out = run("kubernetes", "api-7", {**cfg, "action": "logs", "container": "app", "previous": True})
    assert "panic: missing DATABASE_URL" in out and "previous instance" in out
    out = run("kubernetes", "", {**cfg, "action": "events"})
    assert out.splitlines()[1].startswith("- Warning") and "(×12)" in out
    assert "api-7" in run("kubernetes", "api", {**cfg, "action": "events"})
    assert "api · 1/3 ready" in run("kubernetes", "", {**cfg, "action": "deployments"})
    assert "HTTP 403" in run("kubernetes", "", {**cfg, "namespace": "locked"})
    assert "pod name" in run("kubernetes", "", {**cfg, "action": "logs"})
    assert "HTTP 401" in run("kubernetes", "", {**cfg, "token": "bad"})


def test_github_actions():
    out = run("github_actions", "acme/web", {"branch": "main"})
    assert "#77 · CI · failure · main · Bump deps" in out
    out = run("github_actions", "acme/web#77", {"token": "ghtok"})
    assert "job test: failure" in out and "✗ step 4 pytest" in out and "test_login - AssertionError" in out
    assert "job lint: success" in out and calls[-1].url.host == "logs.example", "follows the log redirect"
    out = run("github_actions", "https://github.com/acme/web#77", {})
    assert "needs a token" in out
    assert "Not found" in run("github_actions", "acme/missing", {})
    assert "owner/repo" in run("github_actions", "just-a-name", {})


def test_service_status():
    out = run("service_status", "github, status.example.com, nope", {})
    assert "- GitHub: Partial System Outage" in out and "⚠ Actions: major outage" in out and "Git:" not in out
    assert "🔴 Delayed Actions runs (investigating, major)" in out and "We are investigating." in out
    assert "isn't a Statuspage status page" in out and "nope: unknown provider" in out
    assert "Name the services" in run("service_status", "", {})


def test_catalog_lists_them_as_installable_packages():
    tools._load()
    entries = {t["id"]: t for s in tools.catalog() for t in s["tools"]}
    for tid in ("dbt_cloud", "fivetran", "airbyte", "prefect", "kubernetes", "github_actions", "service_status"):
        assert entries[tid]["category"] == "APIs & Integrations" and entries[tid].get("parameters"), tid
