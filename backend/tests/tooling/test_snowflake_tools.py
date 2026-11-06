"""Snowflake REST built-in tools against a fake account (httpx.MockTransport): token headers, the SQL
API (including a 202 that is polled), the REST resource endpoints each tool calls, name validation
before anything reaches SQL text, and the read-only guards."""

import asyncio
import json

import httpx
import pytest

import tools

CFG = {"account": "MyOrg-Acct1", "token": "pat-1", "warehouse": "WH", "database": "DB"}
HOST = "myorg-acct1.snowflakecomputing.com"
calls = []
responses = {}
statements = []   # replies to POST /api/v2/statements, in order


def result_set(columns, rows):
    return {"resultSetMetaData": {"rowType": [{"name": c} for c in columns]}, "data": rows, "statementHandle": "h1"}


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content) if request.content else None
    calls.append((request.method, request.url.path, dict(request.url.params), body))
    assert request.url.host == HOST, "the account becomes <account>.snowflakecomputing.com"
    assert request.headers["authorization"] == "Bearer pat-1"
    assert request.headers["x-snowflake-authorization-token-type"] == "PROGRAMMATIC_ACCESS_TOKEN"
    if request.method == "POST" and request.url.path == "/api/v2/statements":
        status, reply = statements.pop(0)
        return httpx.Response(status, json=reply)
    reply = responses.get((request.method, request.url.path))
    if reply is None:
        return httpx.Response(404, json={"code": "390404", "message": f"no {request.url.path}"})
    status, payload = reply if isinstance(reply, tuple) else (200, reply)
    if isinstance(payload, str):
        return httpx.Response(status, text=payload, headers={"content-type": "text/event-stream"})
    return httpx.Response(status, json=payload)


@pytest.fixture(autouse=True)
def fake_account(monkeypatch):
    real = httpx.AsyncClient

    class FakeClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    async def no_wait(_):
        return None

    import tools.data._snowflake as sf
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(sf.asyncio, "sleep", no_wait)
    calls.clear()
    responses.clear()
    statements.clear()


def run(tool, args, cfg=CFG):
    return asyncio.run(tools.execute(tool, "", dict(cfg), args))


def report(out):
    return json.loads(out.split("\n", 1)[1])


def test_tools_are_registered_with_typed_inputs():
    expected = {
        "snowflake_sql_api": ["sql"], "snowflake_warehouses": [], "snowflake_warehouse_control": ["warehouse_name"],
        "snowflake_catalog": [], "snowflake_query_history": [], "snowflake_task": ["task_name"],
        "snowflake_pipe_status": ["pipe_name"], "snowflake_copy_history": ["table_name"],
        "snowflake_stage_files": ["stage"], "snowflake_cortex_complete": ["prompt"],
        "snowflake_cortex_search": ["query"], "snowflake_cortex_analyst": ["question"],
    }
    for tool_id, required in expected.items():
        spec = tools.get_spec(tool_id)
        assert spec is not None and spec.parameters["required"] == required, tool_id
        assert spec.required[:2] == ("account", "token") and spec.selects["token_type"]


def test_sql_api_polls_a_running_statement_and_stays_read_only():
    statements.append((202, {"statementHandle": "h9", "message": "running"}))
    responses[("GET", "/api/v2/statements/h9")] = result_set(["N", "NAME"], [["1", "ada"], ["2", "grace"]])
    out = run("snowflake_sql_api", {"sql": "SELECT n, name FROM people", "max_results": 1})
    assert "| N | NAME |" in out and "ada" in out and "grace" not in out and "first 1 rows" in out
    assert calls[0][3] == {"statement": "SELECT n, name FROM people", "timeout": 60, "warehouse": "WH",
                           "database": "DB"}
    assert "read-only" in run("snowflake_sql_api", {"sql": "DROP TABLE people"}) and len(calls) == 2


def test_token_type_and_account_url():
    import tools.data._snowflake as sf
    assert sf._headers({**CFG, "token_type": "oauth"})["X-Snowflake-Authorization-Token-Type"] == "OAUTH"
    assert sf._headers({**CFG, "token_type": "keypair_jwt"})["X-Snowflake-Authorization-Token-Type"] == "KEYPAIR_JWT"
    assert sf.account_url({"account": "ab12345.us-east-1.snowflakecomputing.com"}) == \
        "https://ab12345.us-east-1.snowflakecomputing.com"
    assert sf.account_url({"account": "https://custom.example.com/"}) == "https://custom.example.com"


def test_warehouses_list_and_control():
    responses[("GET", "/api/v2/warehouses")] = [{"name": "WH", "state": "SUSPENDED", "warehouse_size": "XSMALL"}]
    data = report(run("snowflake_warehouses", {"name": "W"}))
    assert data["warehouses"][0]["state"] == "SUSPENDED" and calls[-1][2] == {"like": "%W%"}
    responses[("POST", "/api/v2/warehouses/WH:resume")] = {"status": "Statement executed successfully."}
    assert report(run("snowflake_warehouse_control", {"warehouse_name": "WH"}))["action"] == "resume"
    assert "isn't a warehouse name" in run("snowflake_warehouse_control", {"warehouse_name": "WH; DROP"})


def test_catalog_depths():
    responses[("GET", "/api/v2/databases")] = [{"name": "DB", "owner": "SYSADMIN"}]
    responses[("GET", "/api/v2/databases/DB/schemas")] = [{"name": "PUBLIC"}]
    responses[("GET", "/api/v2/databases/DB/schemas/PUBLIC/tables")] = [{"name": "ORDERS", "kind": "PERMANENT"}]
    responses[("GET", "/api/v2/databases/DB/schemas/PUBLIC/tables/ORDERS")] = {
        "name": "ORDERS", "rows": 10, "columns": [{"name": "ID", "datatype": "NUMBER(38,0)", "nullable": False}]}
    assert report(run("snowflake_catalog", {}))["databases"][0]["name"] == "DB"
    assert report(run("snowflake_catalog", {"name": "DB"}))["schemas"] == [{"name": "PUBLIC"}]
    assert report(run("snowflake_catalog", {"name": "DB.PUBLIC"}))["tables"][0]["kind"] == "PERMANENT"
    assert report(run("snowflake_catalog", {"name": "DB.PUBLIC.ORDERS"}))["columns"][0]["type"] == "NUMBER(38,0)"
    assert "Expected" in run("snowflake_catalog", {"name": "a.b.c.d"})


def test_query_history_filters_by_status():
    statements.append((200, result_set(["QUERY_ID", "EXECUTION_STATUS"], [["q1", "FAILED_WITH_ERROR"]])))
    data = report(run("snowflake_query_history", {"status": "failed", "limit": 5}))
    assert data["queries"] == [{"QUERY_ID": "q1", "EXECUTION_STATUS": "FAILED_WITH_ERROR"}]
    sql = calls[-1][3]["statement"]
    assert "WHERE execution_status = 'FAILED_WITH_ERROR'" in sql and sql.endswith("LIMIT 5")


def test_task_status_includes_history_and_execute():
    path = "/api/v2/databases/DB/schemas/ETL/tasks/LOAD"
    responses[("GET", path)] = {"name": "LOAD", "state": "started", "schedule": "USING CRON 0 * * * * UTC"}
    statements.append((200, result_set(["NAME", "STATE"], [["LOAD", "SUCCEEDED"]])))
    data = report(run("snowflake_task", {"task_name": "DB.ETL.LOAD"}))
    assert data["state"] == "started" and data["recent_runs"] == [{"NAME": "LOAD", "STATE": "SUCCEEDED"}]
    assert "DB.INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME => 'LOAD'" in calls[-1][3]["statement"]
    responses[("POST", f"{path}:execute")] = {}
    assert report(run("snowflake_task", {"task_name": "DB.ETL.LOAD", "action": "execute"}))["requested"]
    assert "Expected db.schema.task" in run("snowflake_task", {"task_name": "LOAD'); DROP TABLE x; --"})


def test_pipe_status_parses_the_json():
    statements.append((200, result_set(["STATUS"], [['{"executionState":"RUNNING","pendingFileCount":0}']])))
    data = report(run("snowflake_pipe_status", {"pipe_name": "DB.RAW.EVENTS_PIPE"}))
    assert data["status"]["executionState"] == "RUNNING"
    assert calls[-1][3]["statement"] == "SELECT SYSTEM$PIPE_STATUS('DB.RAW.EVENTS_PIPE') AS status"


def test_copy_history_counts_failures():
    statements.append((200, result_set(["FILE_NAME", "STATUS"], [["a.csv", "Loaded"], ["b.csv", "Load failed"]])))
    data = report(run("snowflake_copy_history", {"table_name": "DB.RAW.EVENTS", "hours": 6}))
    assert data["files"] == 2 and data["not_loaded"] == 1
    assert "DATEADD(hours, -6" in calls[-1][3]["statement"]


def test_stage_files_validates_the_location():
    statements.append((200, result_set(["name", "size", "md5", "last_modified"], [["s/2026/a.csv", "9", "x", "Mon"]])))
    data = report(run("snowflake_stage_files", {"stage": "@DB.RAW.LANDING/2026/"}))
    assert data["files"][0]["name"] == "s/2026/a.csv" and calls[-1][3]["statement"] == "LIST @DB.RAW.LANDING/2026/"
    assert "Expected" in run("snowflake_stage_files", {"stage": "@DB.RAW.LANDING/x'; DROP"})


def test_cortex_complete_reads_json_or_sse():
    responses[("POST", "/api/v2/cortex/inference:complete")] = {"choices": [{"message": {"content": "hello"}}]}
    assert run("snowflake_cortex_complete", {"prompt": "hi"}, {**CFG, "model": "claude-sonnet-4-5"}).endswith("hello")
    assert calls[-1][3]["messages"] == [{"role": "user", "content": "hi"}] and calls[-1][3]["stream"] is False
    responses[("POST", "/api/v2/cortex/inference:complete")] = (
        'data: {"choices":[{"delta":{"content":"hel"}}]}\n\ndata: {"choices":[{"delta":{"content":"lo"}}]}\n\n')
    assert run("snowflake_cortex_complete", {"prompt": "hi"}, {**CFG, "model": "claude-sonnet-4-5"}).endswith("hello")


def test_cortex_search():
    cfg = {**CFG, "search_service": "DB.DOCS.FAQ", "columns": "question, answer"}
    responses[("POST", "/api/v2/databases/DB/schemas/DOCS/cortex-search-services/FAQ:query")] = {
        "results": [{"question": "refunds?", "answer": "30 days"}]}
    data = report(run("snowflake_cortex_search", {"query": "refund", "limit": 3}, cfg))
    assert data["results"][0]["answer"] == "30 days"
    assert calls[-1][3] == {"query": "refund", "limit": 3, "columns": ["question", "answer"]}


def test_cortex_analyst_runs_only_read_sql():
    cfg = {**CFG, "semantic_model": "DB.SALES.REVENUE_VIEW"}
    responses[("POST", "/api/v2/cortex/analyst/message")] = {"message": {"content": [
        {"type": "text", "text": "Revenue by month"}, {"type": "sql", "statement": "SELECT 1 AS revenue"}]}}
    statements.append((200, result_set(["REVENUE"], [["1"]])))
    data = report(run("snowflake_cortex_analyst", {"question": "revenue?"}, cfg))
    assert data["sql"] == "SELECT 1 AS revenue" and data["rows"] == [{"REVENUE": "1"}]
    assert calls[0][3]["semantic_view"] == "DB.SALES.REVENUE_VIEW"

    responses[("POST", "/api/v2/cortex/analyst/message")] = {"message": {"content": [
        {"type": "sql", "statement": "DELETE FROM orders"}]}}
    calls.clear()
    data = report(run("snowflake_cortex_analyst", {"question": "x"}, {**cfg, "semantic_model": "@DB.S.ST/m.yaml"}))
    assert "Not run" in data["result_error"] and len(calls) == 1
    assert calls[0][3]["semantic_model_file"] == "@DB.S.ST/m.yaml"


def test_errors_are_reported_not_raised():
    out = run("snowflake_warehouse_control", {"warehouse_name": "NOPE"})
    assert out.startswith("[Snowflake Warehouse Control] HTTP 404") and "no /api/v2/warehouses/NOPE:resume" in out
    statements.append((422, {"code": "002003", "message": "Object 'X' does not exist"}))
    assert "does not exist" in run("snowflake_sql_api", {"sql": "SELECT * FROM X"})
    assert "Missing required config: account" in asyncio.run(tools.execute("snowflake_warehouses", "", {"token": "t"}, {}))
