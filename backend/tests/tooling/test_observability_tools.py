"""Grafana, Loki, Tempo, Alertmanager, Datadog, Splunk and Elasticsearch Ops against a fake HTTP server shaped
like each product's documented API (method, path, query, auth, body); plus the OpenSearch and Elastic Agent
Builder MCP launch config. No network or accounts needed."""
import asyncio
import base64
import importlib
import json

import httpx
import pytest

import tools

calls = []


def handler(request: httpx.Request) -> httpx.Response:  # noqa: C901 — one fake server for every product
    calls.append(request)
    host, path, q, h = request.url.host, request.url.path, request.url.params, request.headers

    if host == "grafana.example":
        if h.get("authorization") != "Bearer glsa":
            return httpx.Response(401, json={"message": "Unauthorized"})
        if path == "/api/prometheus/grafana/api/v1/rules":
            return httpx.Response(200, json={"status": "success", "data": {"groups": [{"name": "api", "file": "Prod", "rules": [
                {"name": "High 5xx rate", "state": "firing", "health": "ok", "alerts": [
                    {"labels": {"alertname": "High 5xx rate", "service": "checkout"}, "annotations": {"summary": "5xx > 5%"},
                     "activeAt": "2026-11-04T08:00:00Z"}]},
                {"name": "Disk full", "state": "inactive", "health": "ok"},
                {"name": "Latency", "state": "pending", "health": "ok"},
                {"name": "Broken rule", "state": "inactive", "health": "error", "lastError": "datasource not found"}]}]}})
        if path == "/api/search":
            assert q["type"] == "dash-db" and q["query"] == "checkout"
            return httpx.Response(200, json=[{"title": "Checkout", "folderTitle": "Prod", "url": "/d/abc/checkout", "tags": ["sre"]}])
        if path == "/api/annotations":
            assert int(q["to"]) - int(q["from"]) == 2 * 3600 * 1000
            return httpx.Response(200, json=[{"time": 1762243200000, "text": "Deploy checkout v42", "tags": ["deploy"]},
                                             {"time": 1762240000000, "text": "Config change", "tags": []}])
        if path == "/api/datasources":
            return httpx.Response(200, json=[{"name": "Prometheus", "type": "prometheus", "isDefault": True}])

    if host == "logs.example":
        assert h.get("authorization") == "Basic " + base64.b64encode(b"123456:glc").decode() and h.get("x-scope-orgid") == "t1"
        assert path == "/loki/api/v1/query_range" and q["direction"] == "backward"
        if "count_over_time" in q["query"]:
            return httpx.Response(200, json={"data": {"resultType": "matrix", "result": [
                {"metric": {"level": "error"}, "values": [[1, "3"], [2, "7"]]}]}})
        if q["query"] == "{bad":
            return httpx.Response(400, text="parse error at line 1, col 5")
        return httpx.Response(200, json={"data": {"resultType": "streams", "result": [
            {"stream": {"app": "checkout", "level": "error"}, "values": [
                ["1762243200000000000", "payment timeout"], ["1762243260000000000", "db connection refused"]]}]}})

    if host == "tempo.example":
        if path == "/api/search":
            assert q["q"] == "{status=error}" and int(q["end"]) - int(q["start"]) == 900
            return httpx.Response(200, json={"traces": [
                {"traceID": "a1", "rootServiceName": "web", "rootTraceName": "GET /", "durationMs": 120, "startTimeUnixNano": "1762243200000000000"},
                {"traceID": "b2", "rootServiceName": "checkout", "rootTraceName": "POST /pay", "durationMs": 3400, "startTimeUnixNano": "1762243200000000000"}]})
        if path == "/api/v2/traces/0123456789abcdef0123456789abcdef":
            return httpx.Response(404, text="")
        if path == "/api/traces/0123456789abcdef0123456789abcdef":
            return httpx.Response(200, json={"batches": [
                {"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                 "scopeSpans": [{"spans": [
                     {"name": "POST /pay", "startTimeUnixNano": "0", "endTimeUnixNano": "3400000000", "status": {}},
                     {"name": "charge card", "startTimeUnixNano": "0", "endTimeUnixNano": "3000000000",
                      "status": {"code": 2, "message": "gateway timeout"}}]}]}]})

    if host == "am.example":
        if path == "/api/v2/alerts":
            assert q["active"] == "true" and q["silenced"] == "false"
            assert q.get("filter") in (None, 'alertname="DiskFull"', 'severity="critical"')
            return httpx.Response(200, json=[
                {"labels": {"alertname": "DiskFull", "severity": "warning", "instance": "db-1"}, "annotations": {"summary": "90% full"},
                 "startsAt": "2026-11-04T07:00:00Z", "status": {"state": "active"}},
                {"labels": {"alertname": "APIDown", "severity": "critical", "job": "api"}, "annotations": {},
                 "startsAt": "2026-11-04T08:00:00Z", "status": {"state": "active"}}])
        if path == "/api/v2/silences":
            return httpx.Response(200, json=[
                {"status": {"state": "active"}, "endsAt": "2026-11-05T00:00:00Z", "createdBy": "ana", "comment": "maintenance",
                 "matchers": [{"name": "instance", "value": "db-.*", "isRegex": True, "isEqual": True}]},
                {"status": {"state": "expired"}, "matchers": []}])

    if host == "api.datadoghq.eu":
        if h.get("dd-api-key") != "ddk" or h.get("dd-application-key") != "dda":
            return httpx.Response(403, json={"errors": ["Forbidden"]})
        if path == "/api/v1/monitor":
            assert q["group_states"] == "alert,warn,no data" and q.get("monitor_tags") == "team:payments"
            return httpx.Response(200, json=[
                {"id": 1, "name": "Checkout errors", "overall_state": "Alert", "type": "log alert", "tags": ["team:payments"]},
                {"id": 2, "name": "CPU", "overall_state": "OK", "type": "metric alert"},
                {"id": 3, "name": "Queue depth", "overall_state": "Warn", "type": "metric alert"}])
        if path == "/api/v2/logs/events/search":
            body = json.loads(request.content)
            assert body["filter"] == {"query": "service:web status:error", "from": "now-900s", "to": "now"} and body["sort"] == "-timestamp"
            return httpx.Response(200, json={"data": [{"attributes": {"timestamp": "2026-11-04T08:01:02Z", "status": "error",
                                                                     "service": "web", "host": "w1", "message": "NullPointerException"}}]})
        if path == "/api/v1/events":
            return httpx.Response(200, json={"events": [{"date_happened": 1762243200, "alert_type": "info", "title": "Deployed web v7"}]})

    if host == "splunk.example":
        if h.get("authorization") != "Bearer spt":
            return httpx.Response(401, text="unauthorized")
        form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
        assert form["output_mode"] == "json" and form["earliest_time"] == "-15m"
        if path == "/services/search/v2/jobs/export":
            return httpx.Response(404, text="")   # an older Splunk: only v1
        assert path == "/services/search/jobs/export"
        if "nothing" in form["search"]:
            return httpx.Response(200, text=json.dumps({"messages": [{"type": "INFO", "text": "No matching fields"}]}))
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in [
            {"preview": True, "result": {"host": "ignored"}},
            {"preview": False, "result": {"host": "web-1", "count": "42"}},
            {"preview": False, "result": {"host": "web-2", "count": "7"}}]))

    if host == "es.example":
        assert h.get("authorization") == "ApiKey esk"
        if path == "/_cluster/health":
            return httpx.Response(200, json={"cluster_name": "prod", "status": "yellow", "number_of_nodes": 3, "number_of_data_nodes": 2,
                                             "active_shards": 40, "relocating_shards": 0, "initializing_shards": 0, "unassigned_shards": 2,
                                             "number_of_pending_tasks": 0, "active_shards_percent_as_number": 95.2})
        if path == "/_cluster/allocation/explain":
            return httpx.Response(200, json={"index": "logs-1", "shard": 0, "primary": False, "unassigned_info": {"reason": "NODE_LEFT"},
                                             "allocate_explanation": "cannot allocate because allocation is not permitted to any of the nodes"})
        if path == "/_cat/indices/logs-*":
            assert q["s"] == "store.size:desc" and q["format"] == "json"
            return httpx.Response(200, json=[{"index": "logs-1", "health": "yellow", "status": "open", "docs.count": "1000",
                                              "store.size": str(5 * 1024**3), "pri": "1", "rep": "1"}])
        if path == "/_query":
            query = json.loads(request.content)["query"]
            if "BAD" in query:
                return httpx.Response(400, json={"error": {"reason": "Unknown column [BAD]"}}, headers={"content-type": "application/json"})
            return httpx.Response(200, json={"columns": [{"name": "c", "type": "long"}, {"name": "service.name", "type": "keyword"}],
                                             "values": [[12, "checkout"], [3, None]]})
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


def test_grafana():
    cfg = {"base_url": "https://grafana.example/", "token": "glsa"}
    out = run("grafana", "", cfg)
    assert out.splitlines()[0] == "[Grafana] 3 active alert rule(s) of 4"
    assert "FIRING · High 5xx rate · Prod/api" in out and "service=checkout — 5xx > 5%" in out
    assert "PENDING · Latency" in out and "error: datasource not found" in out and "Disk full" not in out
    assert "Checkout · Prod · https://grafana.example/d/abc/checkout" in run("grafana", "checkout", {**cfg, "action": "dashboards"})
    out = run("grafana", "deploy", {**cfg, "action": "annotations", "lookback": "2h"})
    assert "Deploy checkout v42" in out and "Config change" not in out
    assert "Prometheus · prometheus · default" in run("grafana", "", {**cfg, "action": "datasources"})
    assert "HTTP 401" in run("grafana", "", {**cfg, "token": "x"})


def test_loki():
    cfg = {"base_url": "https://logs.example", "username": "123456", "token": "glc", "org_id": "t1"}
    out = run("loki_query", '{app="checkout"} |= "error"', cfg)
    lines = out.splitlines()
    assert "2 line(s), newest first" in lines[0] and "db connection refused" in lines[1] and "payment timeout" in lines[2]
    assert "app=checkout" in lines[1]
    assert "level=error: 7" in run("loki_query", 'sum by (level) (count_over_time({app="x"}[5m]))', cfg)
    assert "rejected the query: parse error" in run("loki_query", "{bad", cfg)
    assert "Provide a LogQL query" in run("loki_query", "", cfg)


def test_tempo():
    cfg = {"base_url": "https://tempo.example"}
    out = run("tempo_traces", "{status=error}", {**cfg, "lookback": "15m"})
    assert out.splitlines()[1].startswith("- b2 · checkout POST /pay · 3400 ms"), "slowest first"
    out = run("tempo_traces", "0123456789abcdef0123456789abcdef", cfg)
    assert "2 span(s) across checkout · 1 with errors" in out and "3400.0 ms · checkout · POST /pay" in out
    assert "charge card — gateway timeout" in out and calls[0].url.path.startswith("/api/v2/"), "tries the v2 API first"


def test_alertmanager():
    cfg = {"base_url": "http://am.example"}
    out = run("alertmanager", "", cfg)
    assert out.splitlines()[1].startswith("- critical · APIDown"), "most severe first"
    assert "warning · DiskFull · instance=db-1" in out and "— 90% full" in out
    run("alertmanager", "DiskFull", cfg)
    assert calls[0].url.params["filter"] == 'alertname="DiskFull"', "a bare name becomes an alertname matcher"
    run("alertmanager", 'severity="critical"', cfg)
    assert calls[0].url.params["filter"] == 'severity="critical"'
    out = run("alertmanager", "", {**cfg, "action": "silences"})
    assert "1 silence(s)" in out and "by ana · instance=~db-.* — maintenance" in out


def test_datadog():
    cfg = {"site": "eu1", "api_key": "ddk", "application_key": "dda"}
    out = run("datadog", "team:payments", cfg)
    assert "2 monitor(s) not OK" in out and out.index("Checkout errors") < out.index("Queue depth") and "CPU" not in out
    out = run("datadog", "service:web status:error", {**cfg, "action": "logs", "lookback": "15m"})
    assert "error web w1 | NullPointerException" in out
    assert "Deployed web v7" in run("datadog", "deploy", {**cfg, "action": "events"})
    assert "HTTP 403" in run("datadog", "", {**cfg, "application_key": "bad"})
    assert "required" in run("datadog", "", {})


def test_splunk():
    cfg = {"base_url": "https://splunk.example:8089", "token": "spt", "earliest": "-15m"}
    out = run("splunk_search", "index=web status>=500 | stats count by host", cfg)
    assert "2 result(s) for: search index=web" in out and "host | count" in out and "web-1 | 42" in out and "ignored" not in out
    assert [c.url.path for c in calls] == ["/services/search/v2/jobs/export", "/services/search/jobs/export"], "falls back to v1"
    out = run("splunk_search", "| makeresults nothing", cfg)
    assert "No results" in out and "No matching fields" in out
    assert "HTTP 401" in run("splunk_search", "index=x", {**cfg, "token": "bad"})
    assert "Set token" in run("splunk_search", "index=x", {"base_url": "https://splunk.example:8089"})


def test_elasticsearch_ops():
    cfg = {"base_url": "https://es.example", "api_key": "esk"}
    out = run("elasticsearch_ops", "", cfg)
    assert "Cluster prod: YELLOW" in out and "2 unassigned" in out and "logs-1 shard 0 (replica) — NODE_LEFT" in out
    out = run("elasticsearch_ops", "logs-*", {**cfg, "action": "indices"})
    assert "1 not green" in out and "logs-1 · yellow · open · 1000 docs · 5.0GB · 1p/1r" in out
    out = run("elasticsearch_ops", "FROM logs-* | STATS c = COUNT(*) BY service.name", {**cfg, "action": "esql"})
    assert "c | service.name" in out and "12 | checkout" in out and "3 | " in out
    assert "ES|QL error: Unknown column [BAD]" in run("elasticsearch_ops", "FROM x | KEEP BAD", {**cfg, "action": "esql"})


def test_catalog_registers_the_tools():
    tools._load()
    entries = {t["id"]: t for s in tools.catalog() for t in s["tools"]}
    for tid in ("grafana", "loki_query", "tempo_traces", "alertmanager", "datadog", "splunk_search", "elasticsearch_ops"):
        assert tid in entries and entries[tid].get("parameters"), tid


def _prepare(module, config, input=""):
    mod = importlib.import_module(module)
    if hasattr(mod, "ARGS"):
        env = {}
        args, name, call = mod.prepare(config, input, list(mod.ARGS), env, {"default_tool": mod.DEFAULT_TOOL})
        return args, name, call, env
    return mod.prepare(config, input, {"default_tool": mod.DEFAULT_TOOL})


def test_opensearch_mcp():
    args, name, call, env = _prepare("tools.mcp.databases.mcp_opensearch", {
        "opensearch_url": "https://os:9200", "opensearch_username": "admin", "opensearch_password": "pw"}, "logs-*")
    assert args == ["opensearch-mcp-server-py@0.12.0"] and name == "ListIndexTool" and call == {"index": "logs-*"}
    assert env == {"OPENSEARCH_URL": "https://os:9200", "OPENSEARCH_USERNAME": "admin", "OPENSEARCH_PASSWORD": "pw",
                   "OPENSEARCH_SETTINGS_ALLOW_WRITE": "false"}
    _, _, _, env = _prepare("tools.mcp.databases.mcp_opensearch", {"opensearch_url": "http://localhost:9200",
                                                                   "allow_write": "on", "ssl_verify": "off"})
    assert env["OPENSEARCH_NO_AUTH"] == "true" and env["OPENSEARCH_SETTINGS_ALLOW_WRITE"] == "true" and env["OPENSEARCH_SSL_VERIFY"] == "false"


def test_elastic_agent_builder_mcp():
    url, headers, name, call = _prepare("tools.mcp.databases.mcp_elastic_agent_builder",
                                        {"kibana_url": "https://kb.example/", "elastic_api_key": "k1"})
    assert url == "https://kb.example/api/agent_builder/mcp" and headers == {"Authorization": "ApiKey k1"}
    assert name == "platform.core.list_indices" and call == {}
    url, _, _, _ = _prepare("tools.mcp.databases.mcp_elastic_agent_builder",
                            {"kibana_url": "https://kb.example", "space": "ops", "elastic_api_key": "k1"})
    assert url == "https://kb.example/s/ops/api/agent_builder/mcp"
    assert "elastic_api_key" in asyncio.run(tools.execute("mcp_elastic_agent_builder", "", {"kibana_url": "https://kb"}, None))
