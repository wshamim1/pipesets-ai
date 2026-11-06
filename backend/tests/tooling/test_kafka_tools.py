"""Kafka / Confluent tools: topics, consumer lag, produce, Schema Registry and Connect against a fake REST
API (Kafka REST v3, Schema Registry, Connect), plus the Confluent MCP server's launch config."""

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
    host, path, method = request.url.host, request.url.path, request.method

    if host == "kafka.acme.io":
        if request.headers.get("authorization") != basic("key", "secret"):
            return httpx.Response(401, json={"message": "Unauthorized"})
        c = "/kafka/v3/clusters/lkc-1"
        if path == "/kafka/v3/clusters":
            return httpx.Response(200, json={"data": [{"cluster_id": "lkc-1"}]})
        if path == f"{c}/topics" and method == "GET":
            return httpx.Response(200, json={"data": [
                {"topic_name": "orders", "partitions_count": 6, "replication_factor": 3, "is_internal": False},
                {"topic_name": "__consumer_offsets", "partitions_count": 50, "replication_factor": 3, "is_internal": True},
                {"topic_name": "payments", "partitions_count": 3, "replication_factor": 3, "is_internal": False}]})
        if path == f"{c}/topics/orders":
            return httpx.Response(200, json={"topic_name": "orders", "partitions_count": 6, "replication_factor": 3})
        if path == f"{c}/topics/orders/configs":
            return httpx.Response(200, json={"data": [{"name": "retention.ms", "value": "604800000"},
                                                      {"name": "unrelated", "value": "x"},
                                                      {"name": "cleanup.policy", "value": "delete"}]})
        if path == f"{c}/topics/nope":
            return httpx.Response(404, json={"error_code": 40403, "message": "This server does not host this topic-partition."})
        if path == f"{c}/topics/orders/records":
            return httpx.Response(200, json={"error_code": 200, "partition_id": 2, "offset": 41})
        if path == f"{c}/topics/locked/records":
            return httpx.Response(200, json={"error_code": 40301, "message": "Not authorized to write"})
        if path == f"{c}/consumer-groups":
            return httpx.Response(200, json={"data": [{"consumer_group_id": "billing", "state": "STABLE"},
                                                      {"consumer_group_id": "audit", "state": "EMPTY"}]})
        if path == f"{c}/consumer-groups/billing":
            return httpx.Response(200, json={"consumer_group_id": "billing", "state": "STABLE"})
        if path == f"{c}/consumer-groups/billing/lags":
            return httpx.Response(200, json={"data": [
                {"topic_name": "orders", "partition_id": 0, "current_offset": 90, "log_end_offset": 100, "lag": 10},
                {"topic_name": "orders", "partition_id": 1, "current_offset": 50, "log_end_offset": 950, "lag": 900},
                {"topic_name": "payments", "partition_id": 0, "current_offset": 7, "log_end_offset": 7, "lag": 0}]})
        if path == f"{c}/consumer-groups/audit":
            return httpx.Response(200, json={"consumer_group_id": "audit", "state": "EMPTY"})
        if path == f"{c}/consumer-groups/audit/lags":
            return httpx.Response(200, json={"data": []})

    if host == "multi.acme.io":
        return httpx.Response(200, json={"data": [{"cluster_id": "a"}, {"cluster_id": "b"}]})

    if host == "registry.acme.io":
        if path == "/subjects":
            return httpx.Response(200, json=["payments-value", "orders-value"])
        if path == "/subjects/orders-value/versions/latest":
            return httpx.Response(200, json={"subject": "orders-value", "version": 3, "id": 100001,
                                             "schema": '{"type":"record","name":"Order","fields":[]}'})
        if path == "/subjects/orders-value/versions/2":
            return httpx.Response(200, json={"subject": "orders-value", "version": 2, "id": 7, "schemaType": "PROTOBUF", "schema": "syntax"})
        if path.startswith("/subjects/nope"):
            return httpx.Response(404, json={"error_code": 40401, "message": "Subject 'nope' not found."})
        if path == "/compatibility/subjects/orders-value/versions/latest" and method == "POST":
            sent = json.loads(request.content)
            assert request.url.params.get("verbose") == "true"
            if "removed" in sent["schema"]:
                return httpx.Response(200, json={"is_compatible": False, "messages": [
                    "Incompatibility{type:READER_FIELD_MISSING_DEFAULT_VALUE, location:/fields/1, reader:{...}}",
                    "Incompatibility{type:TYPE_MISMATCH, location:/fields/2/type}"]})
            return httpx.Response(200, json={"is_compatible": True})
        if path == "/compatibility/subjects/nope/versions/latest":
            return httpx.Response(404, json={"error_code": 40401, "message": "Subject 'nope' not found."})
        if path == "/config/orders-value":
            return httpx.Response(200, json={"compatibilityLevel": "BACKWARD"})

    if host == "connect.acme.io":
        if path == "/connectors":
            return httpx.Response(200, json={
                "s3-sink": {"status": {"connector": {"state": "RUNNING"}, "tasks": [{"id": 0, "state": "RUNNING"}]}},
                "pg-source": {"status": {"connector": {"state": "RUNNING"}, "tasks": [
                    {"id": 0, "state": "FAILED", "trace": "org.apache.kafka.connect.errors.ConnectException: x\n"
                                                        "Caused by: java.net.ConnectException: Connection refused"}]}}})
        if path == "/connectors/pg-source/status":
            return httpx.Response(200, json={"name": "pg-source", "connector": {"state": "RUNNING"}, "tasks": [
                {"id": 0, "state": "FAILED", "trace": "boom\nCaused by: java.net.ConnectException: Connection refused"}]})
        if path == "/connectors/gone/status":
            return httpx.Response(404, json={"error_code": 404, "message": "No status found for connector gone"})

    if host == "jobs.acme.io":
        a, b = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        if path == "/jobs/overview":
            return httpx.Response(200, json={"jobs": [
                {"jid": b, "name": "enrich-orders", "state": "RUNNING", "start-time": 1767225600000, "duration": 7200000},
                {"jid": a, "name": "fraud-scoring", "state": "RESTARTING", "start-time": 1767225600000, "duration": 90000}]})
        if path == f"/jobs/{a}":
            return httpx.Response(200, json={"jid": a, "name": "fraud-scoring", "state": "RESTARTING",
                                             "start-time": 1767225600000, "duration": 90000,
                                             "vertices": [{"id": "v1", "name": "Source: orders", "status": "RUNNING", "parallelism": 4}]})
        if path == f"/jobs/{b}":
            return httpx.Response(200, json={"jid": b, "name": "enrich-orders", "state": "RUNNING",
                                             "start-time": 1767225600000, "duration": 7200000,
                                             "vertices": [{"id": "v1", "name": "Source: orders", "status": "RUNNING", "parallelism": 2},
                                                          {"id": "v2", "name": "Sink: enriched", "status": "FINISHED", "parallelism": 2}]})
        if path == f"/jobs/{a}/vertices/v1/backpressure" or path == f"/jobs/{b}/vertices/v1/backpressure":
            return httpx.Response(200, json={"status": "ok", "backpressure-level": "high"})
        if path == f"/jobs/{a}/checkpoints":
            return httpx.Response(200, json={"counts": {"completed": 40, "failed": 3, "in_progress": 0}, "latest": {
                "completed": {"id": 40, "trigger_timestamp": 1767225600000, "end_to_end_duration": 2500, "state_size": 3 * 1024 * 1024},
                "failed": {"id": 41, "failure_timestamp": 1767225660000,
                           "failure_message": "Checkpoint expired before completing.\nmore"}}})
        if path == f"/jobs/{a}/exceptions":
            return httpx.Response(200, json={"root-exception": "java.lang.OutOfMemoryError: Java heap space\n\tat x", "exceptionHistory": {"entries": []}})
        if path == f"/jobs/{b}/checkpoints":
            return httpx.Response(404, json={"errors": ["not available"]})
        if path == f"/jobs/{b}/exceptions":
            return httpx.Response(200, json={"root-exception": None, "exceptionHistory": {"entries": []}})
        if path == "/jobs/" + "c" * 32:
            return httpx.Response(404, json={"errors": ["org.apache.flink.runtime.rest.NotFoundException: Job not found\n\tat x"]})

    if host == "flink.acme.io":
        if request.headers.get("authorization") != basic("fk", "fs"):
            return httpx.Response(401, json={"errors": [{"detail": "Unauthorized"}]})
        s = "/sql/v1/organizations/org-1/environments/env-1/statements"
        if path == s:
            return httpx.Response(200, json={"data": [
                {"name": "enrich-orders", "spec": {"statement": "INSERT INTO enriched SELECT * FROM orders"},
                 "status": {"phase": "RUNNING"}},
                {"name": "bad-join", "spec": {"statement": "INSERT INTO j SELECT *\nFROM a JOIN b"},
                 "status": {"phase": "FAILED", "detail": "Table 'b' not found"}}]})
        if path == f"{s}/bad-join":
            return httpx.Response(200, json={"name": "bad-join", "spec": {"compute_pool_id": "lfcp-1", "statement": "SELECT 1"},
                                             "status": {"phase": "FAILED", "detail": "Table 'b' not found"}})
        if path == f"{s}/bad-join/exceptions":
            return httpx.Response(200, json={"data": [{"timestamp": "2026-01-01T00:00:00Z", "stacktrace": "boom"}]})
        if path == f"{s}/enrich-orders":
            return httpx.Response(200, json={"name": "enrich-orders", "spec": {"compute_pool_id": "lfcp-1", "statement": "SELECT 2"},
                                             "status": {"phase": "RUNNING"}})
        if path == f"{s}/gone":
            return httpx.Response(404, json={"errors": [{"detail": "The statement was not found."}]})

    return httpx.Response(599, json={"error": f"unexpected request {method} {request.url}"})


@pytest.fixture
def kafka(monkeypatch):
    """Every httpx.AsyncClient talks to the fake services above."""
    real = httpx.AsyncClient

    class FakeClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


def run(tool, inp, cfg):
    calls.clear()
    return asyncio.run(tools.execute(tool, inp, cfg))


K = {"base_url": "https://kafka.acme.io/", "api_key": "key", "api_secret": "secret"}


def test_kafka_topics(kafka):
    out = run("kafka_topics", "", K)
    assert "2 topic(s), 1 internal hidden" in out
    assert out.index("orders") < out.index("payments") and "__consumer_offsets" not in out
    assert "orders — 6 partition(s), replication 3" in out

    out = run("kafka_topics", "orders", K)
    assert "Partitions  : 6" in out and "retention.ms" in out and "604800000" in out
    assert "cleanup.policy" in out and "unrelated" not in out, "only the settings that matter"

    assert "This server does not host this topic-partition" in run("kafka_topics", "nope", K)
    assert "Authentication failed" in run("kafka_topics", "", {**K, "api_secret": "bad"})
    assert "base_url" in run("kafka_topics", "", {"base_url": ""})


def test_kafka_needs_a_cluster_id_when_there_are_several(kafka):
    out = run("kafka_topics", "", {"base_url": "https://multi.acme.io"})
    assert "2 clusters" in out and "cluster_id" in out
    run("kafka_topics", "", {**K, "cluster_id": "lkc-1"})
    assert [r.url.path for r in calls] == ["/kafka/v3/clusters/lkc-1/topics"], "a cluster_id skips the lookup"
    run("kafka_topics", "", {**K, "rest_path": "/v3"})
    assert calls[0].url.path == "/v3/clusters", "a standalone REST Proxy uses /v3"


def test_kafka_consumer_lag(kafka):
    out = run("kafka_consumer_lag", "", K)
    assert "2 consumer group(s)" in out and "audit [EMPTY]" in out and "billing [STABLE]" in out

    out = run("kafka_consumer_lag", "billing", K)
    assert "total lag 910 across 3 partition(s)" in out
    assert out.index("orders: 910") < out.index("payments: 0"), "worst topic first"
    assert "orders[1] lag 900 (offset 50 of 950)" in out and "payments[0]" not in out, "only lagging partitions"
    assert "no committed offsets" in run("kafka_consumer_lag", "audit", K)


def test_kafka_produce_is_gated(kafka):
    cfg = {**K, "topic": "orders"}
    assert "disabled" in run("kafka_produce", "hi", cfg)
    assert calls == [], "nothing is sent while producing is off"
    assert "topic" in run("kafka_produce", "hi", {**K, "allow_produce": True})
    assert "Provide the message" in run("kafka_produce", "", {**cfg, "allow_produce": True})

    out = run("kafka_produce", '{"id": 7}', {**cfg, "allow_produce": True, "message_key": "k1"})
    sent = json.loads(calls[-1].content)
    assert sent == {"value": {"type": "JSON", "data": {"id": 7}}, "key": {"type": "JSON", "data": "k1"}}
    assert "partition 2, offset 41" in out
    run("kafka_produce", "plain text", {**cfg, "allow_produce": True})
    assert json.loads(calls[-1].content)["value"]["data"] == "plain text"
    assert "Not authorized" in run("kafka_produce", "x", {**K, "topic": "locked", "allow_produce": True})


def test_kafka_schema_registry(kafka):
    R = {"base_url": "https://registry.acme.io"}
    out = run("kafka_schema_registry", "", R)
    assert "2 subject(s)" in out and out.index("orders-value") < out.index("payments-value")
    out = run("kafka_schema_registry", "orders-value", R)
    assert "orders-value v3 (id 100001, AVRO)" in out and '"name":"Order"' in out
    assert "PROTOBUF" in run("kafka_schema_registry", "orders-value", {**R, "version": "2"})
    assert "Subject 'nope' not found" in run("kafka_schema_registry", "nope", R)
    assert "number or 'latest'" in run("kafka_schema_registry", "orders-value", {**R, "version": "../x"})
    assert "base_url" in run("kafka_schema_registry", "", {"base_url": ""})


def test_kafka_connectors(kafka):
    C = {"base_url": "https://connect.acme.io"}
    out = run("kafka_connectors", "", C)
    assert "2 connector(s), 1 failing" in out
    assert out.index("pg-source") < out.index("s3-sink"), "failing connectors first"
    assert "1 failed task(s) — task 0: Caused by: java.net.ConnectException: Connection refused" in out

    out = run("kafka_connectors", "pg-source", C)
    assert "pg-source [RUNNING] — 1 task(s)" in out and "task 0: FAILED" in out
    assert "Error (task 0): Caused by: java.net.ConnectException: Connection refused" in out
    assert "No status found" in run("kafka_connectors", "gone", C)


F = {"base_url": "https://flink.acme.io/", "organization_id": "org-1", "environment_id": "env-1",
     "api_key": "fk", "api_secret": "fs"}


def test_flink_statements(kafka):
    out = run("flink_statements", "", F)
    assert "2 statement(s), 1 unhealthy" in out
    assert out.index("bad-join") < out.index("enrich-orders"), "unhealthy statements first"
    assert "bad-join [FAILED]" in out and "Table 'b' not found" in out
    assert "enrich-orders [RUNNING]" in out and "bad-join" not in run("flink_statements", "", {**F, "phase": "running"})
    assert "No statements in phase STOPPED" in run("flink_statements", "", {**F, "phase": "STOPPED"})

    out = run("flink_statements", "bad-join", F)
    assert "[FAILED]" in out and "lfcp-1" in out and "Exception (2026-01-01T00:00:00Z): boom" in out
    assert "Exception" not in run("flink_statements", "enrich-orders", F), "exceptions only for unhealthy statements"
    assert "statement was not found" in run("flink_statements", "gone", F)
    assert "Authentication failed" in run("flink_statements", "", {**F, "api_secret": "bad"})
    assert "environment_id" in run("flink_statements", "", {**F, "environment_id": ""})


def test_flink_jobs(kafka):
    J = {"base_url": "https://jobs.acme.io/"}
    a, b = "a" * 32, "b" * 32
    out = run("flink_jobs", "", J)
    assert "2 job(s), 1 unhealthy" in out
    assert out.index("fraud-scoring") < out.index("enrich-orders"), "unhealthy jobs first"
    assert f"enrich-orders [RUNNING] — {b}, 2h 0m" in out

    out = run("flink_jobs", "fraud-scoring", J)  # by name
    assert "[RESTARTING]" in out and f"Id       : {a}" in out and "Source: orders [RUNNING] — parallelism 4, backpressure high" in out
    assert "Checkpoints : 40 completed, 3 failed, 0 in progress" in out
    assert "Last completed: #40 at 2026-01-01 00:00:00Z, 2s, 3.0 MB" in out
    assert "Last failed: #41" in out and "Checkpoint expired before completing." in out and "more" not in out.split("Last failed")[1].split("Latest")[0].split("—")[1]
    assert "Latest exception: java.lang.OutOfMemoryError: Java heap space" in out and "\tat" not in out

    out = run("flink_jobs", b, J)  # by id; no checkpoints (404) and no exception are just left out
    assert "Checkpoints" not in out and "Latest exception" not in out and "Sink: enriched [FINISHED]" in out
    assert "backpressure" in out.split("Sink")[0] and "backpressure" not in out.split("Sink")[1]

    assert "No job named 'nope'" in run("flink_jobs", "nope", J)
    assert "Job not found" in run("flink_jobs", "c" * 32, J)
    assert "base_url" in run("flink_jobs", "", {"base_url": ""})


def test_kafka_schema_compat(kafka):
    R = {"base_url": "https://registry.acme.io", "subject": "orders-value"}
    out = run("kafka_schema_compat", '{"type":"record","name":"Order","fields":[]}', R)
    assert out == "[Schema Registry] Compatible with orders-value (latest) under BACKWARD"
    post = next(c for c in calls if c.method == "POST")
    assert json.loads(post.content) == {"schema": '{"type":"record","name":"Order","fields":[]}'}, "Avro needs no schemaType"

    out = run("kafka_schema_compat", '{"removed": true}', {**R, "schema_type": "json"})
    assert "NOT compatible with orders-value (latest)" in out and "READER_FIELD_MISSING_DEFAULT_VALUE" in out
    assert "TYPE_MISMATCH" in out
    assert json.loads([c for c in calls if c.method == "POST"][-1].content)["schemaType"] == "JSON"

    assert "Subject 'nope' not found" in run("kafka_schema_compat", "{}", {**R, "subject": "nope"})
    assert "subject is required" in run("kafka_schema_compat", "{}", {"base_url": R["base_url"]})
    assert "Provide the candidate schema" in run("kafka_schema_compat", "", R)
    assert "number or 'latest'" in run("kafka_schema_compat", "{}", {**R, "version": "../x"})
    assert "schema_type" in run("kafka_schema_compat", "{}", {**R, "schema_type": "XML"})
    assert "base_url" in run("kafka_schema_compat", "{}", {"base_url": ""})
    assert not [c for c in calls if c.method in ("PUT", "DELETE")], "the check never registers anything"


# ── The Confluent MCP server ──────────────────────────────────────────────────

def _launch(config, input=""):
    from tools.mcp.databases import mcp_confluent as m
    env = {}
    args, name, call = m.prepare(config, input, list(m.ARGS), env, {"default_tool": m.DEFAULT_TOOL})
    return args, name, call, env


def test_confluent_mcp_config(monkeypatch):
    for name in ("CONFLUENT_CLOUD_API_KEY", "BOOTSTRAP_SERVERS", "KAFKA_API_KEY", "SCHEMA_REGISTRY_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    args, tool, call, env = _launch({
        "confluent_cloud_api_key": "ck", "confluent_cloud_api_secret": "cs",
        "kafka_bootstrap_servers": "pkc-1.confluent.cloud:9092", "kafka_api_key": "k", "kafka_api_secret": "s",
        "schema_registry_endpoint": "https://psrc-1.confluent.cloud", "FLINK_ORG_ID": "org-1"})
    assert args[:2] == ["-y", "@confluentinc/mcp-confluent@1.6.1"] and args[2] == "--block-tools"
    blocked = args[3].split(",")
    assert {"produce-message", "delete-topics", "create-connector", "create-flink-statement"} <= set(blocked)
    assert "list-topics" not in blocked and "consume-messages" not in blocked, "reading stays available"
    assert env == {"CONFLUENT_CLOUD_API_KEY": "ck", "CONFLUENT_CLOUD_API_SECRET": "cs",
                   "BOOTSTRAP_SERVERS": "pkc-1.confluent.cloud:9092", "KAFKA_API_KEY": "k", "KAFKA_API_SECRET": "s",
                   "SCHEMA_REGISTRY_ENDPOINT": "https://psrc-1.confluent.cloud", "FLINK_ORG_ID": "org-1",
                   "DO_NOT_TRACK": "true"}
    assert (tool, call) == ("list-topics", {})

    args, tool, call, env = _launch({"read_only": "false", "tool_name": "produce-message",
                                     "arguments": {"topicName": "orders"}})
    assert args == ["-y", "@confluentinc/mcp-confluent@1.6.1"] and env == {"DO_NOT_TRACK": "true"}
    assert (tool, call) == ("produce-message", {"topicName": "orders"})


def test_kafka_and_confluent_servers_are_in_the_catalog():
    tools._load()
    entries = {e["id"]: e for s in tools.catalog() for e in s["tools"]}
    for tool_id in ("mcp_kafka", "mcp_confluent"):
        assert entries[tool_id]["type"] == "mcp" and entries[tool_id]["category"] == "Databases & Data"
    for tool_id in ("kafka_topics", "kafka_consumer_lag", "kafka_produce", "kafka_schema_registry", "kafka_connectors"):
        assert entries[tool_id]["category"] == "APIs & Integrations" and entries[tool_id]["required_config"]
    from tools.mcp.databases import mcp_kafka
    env = {}
    mcp_kafka.prepare({"kafka_bootstrap_servers": "b:9092"}, "", [], env, {"default_tool": "list-topics"})
    assert env["BOOTSTRAP_SERVERS"] == "b:9092", "the variable mcp-confluent reads"


def test_confluent_flink_mcp_config(monkeypatch):
    from tools.mcp.databases import mcp_confluent, mcp_confluent_flink as m
    for name in m.ENV.values():
        monkeypatch.delenv(name, raising=False)
    env = {}
    args, tool, call = m.prepare({"flink_rest_endpoint": "https://flink.us-east-1.aws.confluent.cloud",
                                  "flink_api_key": "k", "flink_org_id": "org-1", "TABLEFLOW_API_KEY": "tk"},
                                 "", list(m.ARGS), env, {"default_tool": m.DEFAULT_TOOL})
    assert args[:len(m.ARGS)] == m.ARGS and args[len(m.ARGS)] == "--allow-tools"
    allowed = set(args[len(m.ARGS) + 1].split(","))
    assert {"query-metrics", "list-flink-statements", "list-tableflow-topics"} <= allowed
    assert "list-topics" not in allowed and "produce-message" not in allowed, "only Flink, Tableflow and metrics"
    blocked = set(args[-1].split(","))
    assert args[-2] == "--block-tools" and {"create-flink-statement", "delete-tableflow-topic"} <= blocked
    assert blocked <= allowed and "query-metrics" not in blocked
    assert env == {"FLINK_REST_ENDPOINT": "https://flink.us-east-1.aws.confluent.cloud", "FLINK_API_KEY": "k",
                   "FLINK_ORG_ID": "org-1", "TABLEFLOW_API_KEY": "tk", "DO_NOT_TRACK": "true"}
    assert (tool, call) == ("list-flink-statements", {})

    args, tool, call = m.prepare({"read_only": "false", "tool_name": "query-metrics",
                                  "arguments": {"metric": "io.confluent.flink/num_records_in"}},
                                 "", list(m.ARGS), {}, {"default_tool": m.DEFAULT_TOOL})
    assert "--block-tools" not in args and tool == "query-metrics"


def test_flink_tools_are_in_the_catalog():
    tools._load()
    entries = {e["id"]: e for s in tools.catalog() for e in s["tools"]}
    assert entries["mcp_confluent_flink"]["type"] == "mcp" and entries["mcp_confluent_flink"]["category"] == "Databases & Data"
    for tool_id in ("flink_statements", "flink_jobs", "kafka_schema_compat"):
        assert entries[tool_id]["category"] == "APIs & Integrations" and entries[tool_id]["required_config"]
