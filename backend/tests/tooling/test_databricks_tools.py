"""Databricks built-in tools against a fake workspace (httpx.MockTransport): the request each one
sends, how the response is summarised, and that a model-supplied argument (job_id, cluster_id…)
reaches the tool rather than only node config."""

import asyncio
import json

import httpx
import pytest

import tools

CFG = {"host": "adb-1.azuredatabricks.net", "token": "dapi-1"}
calls = []
responses = {}


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content) if request.content else None
    calls.append((request.method, request.url.path, dict(request.url.params), body))
    assert request.headers["authorization"] == "Bearer dapi-1"
    assert request.url.host == "adb-1.azuredatabricks.net", "a bare host gets https://"
    reply = responses.get((request.method, request.url.path))
    if reply is None:
        return httpx.Response(404, json={"error_code": "NOT_FOUND", "message": f"no {request.url.path}"})
    if isinstance(reply, list):   # successive polls
        reply = reply.pop(0) if len(reply) > 1 else reply[0]
    if isinstance(reply, str):
        return httpx.Response(200, text=reply)
    return httpx.Response(200, json=reply)


@pytest.fixture(autouse=True)
def fake_workspace(monkeypatch):
    real = httpx.AsyncClient

    class FakeClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    calls.clear()
    responses.clear()


def run(tool, args, cfg=CFG):
    return asyncio.run(tools.execute(tool, "", dict(cfg), args))


def test_new_tools_are_registered_with_typed_inputs():
    expected = {
        "databricks_list_jobs": [], "databricks_run_job": ["job_id"], "databricks_cancel_run": ["run_id"],
        "databricks_list_clusters": [], "databricks_cluster_control": ["cluster_id"],
        "databricks_list_warehouses": [], "databricks_unity_catalog": [], "databricks_volume_files": ["path"],
        "databricks_model_serving": ["input"], "databricks_vector_search": ["query"],
        "databricks_genie": ["question"], "databricks_pipeline": ["pipeline_id"],
    }
    for tool_id, required in expected.items():
        spec = tools.get_spec(tool_id)
        assert spec is not None and spec.parameters["required"] == required, tool_id
        assert "host" in spec.required and "token" in spec.required


def test_model_argument_reaches_the_existing_tools():
    responses[("GET", "/api/2.1/jobs/get")] = {"job_id": 7, "settings": {"name": "nightly"}}
    responses[("GET", "/api/2.1/jobs/runs/list")] = {"runs": [{"run_id": 9, "state": {"life_cycle_state": "RUNNING"}}]}
    out = run("databricks_job_status", {"job_id": "7"}, {**CFG, "host": "https://adb-1.azuredatabricks.net"})
    assert '"job_name": "nightly"' in out and calls[0][2] == {"job_id": "7"}
    assert "job_id" not in tools.get_spec("databricks_job_status").required, "the model supplies it per call"


def test_list_jobs_and_run_and_cancel():
    responses[("GET", "/api/2.1/jobs/list")] = {"jobs": [{"job_id": 1, "settings": {"name": "etl"}}], "has_more": False}
    out = run("databricks_list_jobs", {"name": "etl", "limit": 10})
    assert '"name": "etl"' in out and calls[-1][2] == {"limit": "10", "name": "etl"}

    responses[("POST", "/api/2.1/jobs/run-now")] = {"run_id": 55, "number_in_job": 55}
    out = run("databricks_run_job", {"job_id": "1", "job_parameters": {"date": "2026-11-03"}})
    assert '"run_id": 55' in out
    assert calls[-1][3] == {"job_id": 1, "job_parameters": {"date": "2026-11-03"}}

    responses[("POST", "/api/2.1/jobs/runs/cancel")] = {}
    assert '"cancel_requested": true' in run("databricks_cancel_run", {"run_id": "55"})
    assert calls[-1][3] == {"run_id": 55}


def test_clusters_list_filter_and_control():
    responses[("GET", "/api/2.0/clusters/list")] = {"clusters": [
        {"cluster_id": "a", "cluster_name": "dev", "state": "RUNNING"},
        {"cluster_id": "b", "cluster_name": "old", "state": "TERMINATED"}]}
    out = run("databricks_list_clusters", {"state": "RUNNING"})
    assert '"count": 1' in out and '"dev"' in out and '"old"' not in out

    responses[("POST", "/api/2.0/clusters/delete")] = {}
    out = run("databricks_cluster_control", {"cluster_id": "a", "action": "terminate"})
    assert '"action": "terminate"' in out and calls[-1][1:] == ("/api/2.0/clusters/delete", {}, {"cluster_id": "a"})


def test_warehouses_show_http_path():
    responses[("GET", "/api/2.0/sql/warehouses")] = {"warehouses": [
        {"id": "w1", "name": "Starter", "state": "RUNNING", "odbc_params": {"path": "/sql/1.0/warehouses/w1"}}]}
    assert "/sql/1.0/warehouses/w1" in run("databricks_list_warehouses", {})


def test_unity_catalog_depths():
    responses[("GET", "/api/2.1/unity-catalog/catalogs")] = {"catalogs": [{"name": "main"}]}
    responses[("GET", "/api/2.1/unity-catalog/schemas")] = {"schemas": [{"full_name": "main.sales"}]}
    responses[("GET", "/api/2.1/unity-catalog/tables")] = {"tables": [{"full_name": "main.sales.orders"}]}
    responses[("GET", "/api/2.1/unity-catalog/tables/main.sales.orders")] = {
        "full_name": "main.sales.orders", "columns": [{"name": "id", "type_text": "bigint"}]}
    assert '"main"' in run("databricks_unity_catalog", {})
    assert '"main.sales"' in run("databricks_unity_catalog", {"name": "main"})
    assert calls[-1][2]["catalog_name"] == "main"
    assert '"main.sales.orders"' in run("databricks_unity_catalog", {"name": "main.sales"})
    assert calls[-1][2]["schema_name"] == "sales"
    assert '"type": "bigint"' in run("databricks_unity_catalog", {"name": "main.sales.orders"})
    assert "at most" in run("databricks_unity_catalog", {"name": "a.b.c.d"})


def test_volume_lists_a_directory_or_reads_a_file():
    responses[("GET", "/api/2.0/fs/directories/Volumes/main/raw/v")] = {"contents": [
        {"name": "a.csv", "path": "/Volumes/main/raw/v/a.csv", "is_directory": False, "file_size": 9}]}
    assert '"a.csv"' in run("databricks_volume_files", {"path": "/Volumes/main/raw/v/"})
    responses[("GET", "/api/2.0/fs/files/Volumes/main/raw/v/a.csv")] = "id,name\n1,ada\n"
    out = run("databricks_volume_files", {"path": "/Volumes/main/raw/v/a.csv", "max_chars": 100})
    assert out.endswith("id,name\n1,ada\n")
    assert "must start with /Volumes/" in run("databricks_volume_files", {"path": "/tmp/x"})


def test_model_serving_chat_and_raw_json():
    cfg = {**CFG, "endpoint_name": "llama"}
    responses[("POST", "/serving-endpoints/llama/invocations")] = {"choices": [{"message": {"content": "hi there"}}]}
    assert run("databricks_model_serving", {"input": "hello"}, cfg).endswith("hi there")
    assert calls[-1][3]["messages"] == [{"role": "user", "content": "hello"}]
    responses[("POST", "/serving-endpoints/llama/invocations")] = {"predictions": [0.9]}
    assert "0.9" in run("databricks_model_serving", {"input": '{"inputs": [[1, 2]]}'}, cfg)
    assert calls[-1][3] == {"inputs": [[1, 2]]}


def test_vector_search_maps_columns():
    cfg = {**CFG, "index_name": "main.docs.idx", "columns": "id, text"}
    responses[("POST", "/api/2.0/vector-search/indexes/main.docs.idx/query")] = {
        "manifest": {"columns": [{"name": "id"}, {"name": "text"}, {"name": "score"}]},
        "result": {"data_array": [[1, "refund policy", 0.8]]}}
    out = run("databricks_vector_search", {"query": "refunds", "num_results": 3}, cfg)
    assert '"text": "refund policy"' in out
    assert calls[-1][3] == {"query_text": "refunds", "columns": ["id", "text"], "num_results": 3}


def test_genie_polls_then_returns_answer_and_rows(monkeypatch):
    import tools.data.databricks_genie as genie

    async def no_wait(_):
        return None

    monkeypatch.setattr(genie.asyncio, "sleep", no_wait)
    base = "/api/2.0/genie/spaces/s1"
    msg = f"{base}/conversations/c1/messages/m1"
    responses[("POST", f"{base}/start-conversation")] = {
        "conversation_id": "c1", "message_id": "m1", "message": {"status": "SUBMITTED"}}
    responses[("GET", msg)] = [
        {"status": "EXECUTING_QUERY"},
        {"status": "COMPLETED", "attachments": [
            {"attachment_id": "a1", "query": {"query": "SELECT 1 AS n", "description": "one"}},
            {"text": {"content": "There is one."}}]}]
    responses[("GET", f"{msg}/attachments/a1/query-result")] = {"statement_response": {
        "manifest": {"schema": {"columns": [{"name": "n"}]}}, "result": {"data_array": [["1"]]}}}
    out = run("databricks_genie", {"question": "how many?"}, {**CFG, "space_id": "s1"})
    data = json.loads(out.split("\n", 1)[1])
    assert data["answer"] == "There is one." and data["sql"] == "SELECT 1 AS n" and data["rows"] == [{"n": "1"}]


def test_pipeline_status_and_start():
    responses[("GET", "/api/2.0/pipelines/p1")] = {"name": "bronze", "state": "IDLE", "health": "HEALTHY"}
    responses[("GET", "/api/2.0/pipelines/p1/updates")] = {"updates": [{"update_id": "u1", "state": "COMPLETED"}]}
    out = run("databricks_pipeline", {"pipeline_id": "p1"})
    assert '"state": "IDLE"' in out and '"update_id": "u1"' in out
    responses[("POST", "/api/2.0/pipelines/p1/updates")] = {"update_id": "u2"}
    out = run("databricks_pipeline", {"pipeline_id": "p1", "action": "start", "full_refresh": True})
    assert '"update_id": "u2"' in out and calls[-1][3] == {"full_refresh": True}


def test_errors_are_reported_not_raised():
    out = run("databricks_cancel_run", {"run_id": "1"})
    assert out.startswith("[Databricks Cancel Run] HTTP 404") and "no /api/2.1/jobs/runs/cancel" in out
    out = asyncio.run(tools.execute("databricks_list_jobs", "", {"token": "x"}, {}))
    assert "Missing required config: host" in out
