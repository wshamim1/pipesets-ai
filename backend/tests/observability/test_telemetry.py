"""
Metrics and traces (services/telemetry.py): /metrics after real (mock-model) runs, queue depth,
job outcomes, OpenTelemetry spans for LLM runs, Master Agent runs and jobs, and the stream's
per-step trace events.
"""

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client.parser import text_string_to_metric_families

from helpers import hdr, run_jobs
from services import api_keys, jobs, llm_runner, telemetry
from services.request_context import RequestContext


def _metrics(client, **headers):
    r = client.get("/metrics", headers=headers)
    assert r.status_code == 200, r.text
    out = {}
    for fam in text_string_to_metric_families(r.text):
        for s in fam.samples:
            out[(s.name, tuple(sorted(s.labels.items())))] = s.value
    return out


def _value(metrics, name, **labels):
    return metrics.get((name, tuple(sorted(labels.items()))), 0.0)


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    telemetry.use_exporter(exporter)
    yield exporter
    telemetry.use_exporter(None)


class _Usage:
    def as_dict(self):
        return {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}


class _Chunk:
    def __init__(self, text):
        self.text, self.tool_calls, self.thinking_blocks, self.finish_reason = text, [], [], None


class _FakeStream:
    """A local model's answer, so runs take the real (non-simulated) path without a server."""
    usage, cost_usd, backend = _Usage(), 0.0, "fake"

    def __init__(self, messages):
        self._text = f"echo: {messages[-1]['content']}"

    async def __aiter__(self):
        await asyncio.sleep(0.01)
        yield _Chunk(self._text)


@pytest.fixture(scope="module", autouse=True)
def _fake_model(env):
    async def start(cfg, messages, tools=None, tool_choice=None):
        return _FakeStream(messages), cfg, 1, False
    env.setattr(llm_runner, "_start_stream_with_policy", start)


FLOW = {"nodes": [{"id": "m", "type": "llm", "data": {"label": "m", "provider": "ollama", "model": "llama3"}}],
        "edges": []}


@pytest.fixture(scope="module")
def app_id(client):
    aid = client.post("/api/apps", headers=hdr(), json={"name": "Telemetry", "description": "",
                                                        "flow_data": FLOW}).json()["id"]
    assert client.post(f"/api/apps/{aid}/publish", headers=hdr()).status_code == 200
    return aid


@pytest.fixture(scope="module")
def key():
    plaintext, _ = api_keys.create_key(RequestContext(tenant_id="tenant_demo", project_id="proj_research",
                                                      user_id="user_admin"), "telemetry", rate_limit_rpm=0)
    return plaintext


def _run(client, key, app_id, prompt="hello", stream=False):
    return client.post(f"/v1/apps/{app_id}/run", json={"prompt": prompt, "stream": stream},
                       headers={"Authorization": f"Bearer {key}"})


MOCK_FLOW = {"nodes": [{"id": "m", "type": "llm", "data": {"label": "m", "provider": "mock", "model": "mock-gpt-4"}},
                      {"id": "t", "type": "tool", "data": {"label": "Clock", "toolId": "datetime_tool", "config": {}}}],
             "edges": [{"id": "e", "source": "t", "target": "m"}]}


# ── Metrics ───────────────────────────────────────────────────────────────────

def test_a_run_moves_the_run_llm_and_token_metrics(client, key, app_id):
    before = _metrics(client)
    assert _run(client, key, app_id).json()["status"] == "completed"
    after = _metrics(client)
    runs = dict(kind="llm", app=app_id, status="completed")
    assert _value(after, "pipesets_runs_total", **runs) == _value(before, "pipesets_runs_total", **runs) + 1
    assert _value(after, "pipesets_run_duration_seconds_count", kind="llm", app=app_id) >= 1
    calls = dict(provider="ollama", model="llama3", status="success")
    assert _value(after, "pipesets_llm_calls_total", **calls) > _value(before, "pipesets_llm_calls_total", **calls)
    assert _value(after, "pipesets_llm_tokens_total", provider="ollama", model="llama3", type="completion") >= 7


def test_a_simulated_run_is_traced_but_never_counted_as_a_model_call(client, key, spans):
    aid = client.post("/api/apps", headers=hdr(), json={"name": "Simulated", "description": "",
                                                        "flow_data": MOCK_FLOW}).json()["id"]
    assert client.post(f"/api/apps/{aid}/publish", headers=hdr()).status_code == 200
    before = _metrics(client)
    assert _run(client, key, aid).json()["status"] == "completed"
    after = _metrics(client)

    rows = client.get("/api/traces", headers=hdr(), params={"app_id": aid}).json()
    assert len(rows) == 1 and rows[0]["provider"] == "mock" and rows[0]["status"] == "success"
    assert json.loads(rows[0]["metadata_json"])["simulated"] is True
    assert [s["name"] for s in json.loads(rows[0]["spans_json"])] == ["Clock"], "the tool really ran"

    runs = dict(kind="llm", app=aid, status="completed")
    assert _value(after, "pipesets_runs_total", **runs) == _value(before, "pipesets_runs_total", **runs) + 1
    calls = dict(provider="mock", model="mock-gpt-4", status="success")
    assert _value(after, "pipesets_llm_calls_total", **calls) == _value(before, "pipesets_llm_calls_total", **calls)
    tool = dict(tool="Clock", status="success")
    assert _value(after, "pipesets_tool_calls_total", **tool) == _value(before, "pipesets_tool_calls_total", **tool) + 1

    root = next(s for s in spans.get_finished_spans() if s.name == "pipesets.run")
    assert root.attributes["pipesets.simulated"] is True


class _FakeStore:
    def count(self, collection):
        return 1

    def search(self, collection, query_emb, top_k):
        return [{"chunk_id": "c1", "source": "handbook.pdf", "content": "Leave is 25 days.", "_sim": 0.9}]


def test_middleware_retrieval_and_embedding_get_their_own_spans(client, key, spans, monkeypatch):
    import routers.retrieval
    from services import vector_store

    async def embed(texts, *a, **kw):
        await asyncio.sleep(0.02)
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(routers.retrieval, "embed_texts", embed)
    monkeypatch.setattr(vector_store, "store_for", lambda collection: _FakeStore())
    flow = {"nodes": [{"id": "m", "type": "llm", "data": {"label": "m", "provider": "ollama", "model": "llama3"}},
                      {"id": "g", "type": "middleware", "data": {"label": "Guard", "middleware_type": "content_moderation",
                                                                 "config": {}, "enabled": True}},
                      {"id": "r", "type": "retriever", "data": {"label": "KB", "collection_name": "handbook",
                                                                "embedding_provider": "local", "top_k": 3}}],
            "edges": [{"id": "e1", "source": "g", "target": "m"}, {"id": "e2", "source": "r", "target": "m"}]}
    aid = client.post("/api/apps", headers=hdr(), json={"name": "Phases", "description": "",
                                                        "flow_data": flow}).json()["id"]
    assert client.post(f"/api/apps/{aid}/publish", headers=hdr()).status_code == 200
    before = _metrics(client)
    assert _run(client, key, aid, prompt="How much leave do I get?").json()["status"] == "completed"
    after = _metrics(client)

    row = client.get("/api/traces", headers=hdr(), params={"app_id": aid}).json()[0]
    recorded = json.loads(row["spans_json"])
    assert [(s["span_type"], s["name"]) for s in recorded if s["span_type"] != "llm"] == [
        ("middleware", "prompt checks"), ("retrieval", "handbook"), ("embedding", "sentence-transformers/all-MiniLM-L6-v2"),
        ("middleware", "response checks")]
    by_type = {s["span_type"]: s for s in recorded}
    assert by_type["retrieval"]["chunks"] == 1
    assert by_type["embedding"]["latency_ms"] >= 15 and by_type["retrieval"]["latency_ms"] >= by_type["embedding"]["latency_ms"]
    assert by_type["embedding"]["start_ms"] >= by_type["retrieval"]["start_ms"], "embedding sits inside retrieval"

    names = {s.name for s in spans.get_finished_spans()}
    assert {"middleware prompt checks", "retrieval handbook", "embeddings sentence-transformers/all-MiniLM-L6-v2",
            "middleware response checks"} <= names
    for phase in ("middleware", "retrieval", "embedding"):
        assert _value(after, "pipesets_phase_duration_seconds_count", phase=phase) > \
            _value(before, "pipesets_phase_duration_seconds_count", phase=phase)


def test_the_grafana_dashboard_only_queries_metrics_we_export(client):
    dashboard = Path(__file__).resolve().parents[3] / "deploy" / "grafana" / "pipesets-dashboard.json"
    panels = [p for p in json.loads(dashboard.read_text())["panels"] if p["type"] != "row"]
    used = {m for p in panels for t in p["targets"] for m in re.findall(r"pipesets_[a-z_]+", t["expr"])}
    help_lines = client.get("/metrics").text.splitlines()
    exported = {line.split()[2] for line in help_lines if line.startswith("# HELP ")}
    missing = {m for m in used if m not in exported and re.sub(r"_(bucket|sum|count)$", "", m) not in exported}
    assert used and not missing, f"dashboard queries metrics the backend doesn't export: {missing}"


def test_tool_calls_and_failures_are_counted():
    before = telemetry.TOOL_CALLS.labels("web_search", "success")._value.get()
    telemetry.record_run({"run_id": str(uuid.uuid4()), "app_id": "app_t", "node_type": "llm", "status": "error",
                          "error": "boom", "provider": "openai", "model": "gpt-x", "latency_ms": 1500,
                          "spans_json": json.dumps([
                              {"span_type": "llm", "step": 1, "start_ms": 0, "provider": "openai", "model": "gpt-x",
                               "latency_ms": 900, "status": "success"},
                              {"span_type": "tool", "step": 1, "start_ms": 900, "name": "web_search",
                               "latency_ms": 400, "status": "success"}])})
    assert telemetry.TOOL_CALLS.labels("web_search", "success")._value.get() == before + 1
    assert telemetry.RUNS.labels("llm", "app_t", "failed")._value.get() >= 1


def test_queue_depth_comes_from_the_database(client):
    job_id = jobs.enqueue("schedule.run", {"schedule_id": "gone", "run_row_id": "x"}, tenant_id="tenant_demo",
                          project_id="proj_research")
    m = _metrics(client)
    assert _value(m, "pipesets_job_queue", kind="schedule.run", status="queued") >= 1
    assert _value(m, "pipesets_job_queue_oldest_seconds", kind="schedule.run") >= 0
    run_jobs()   # its schedule is gone, so it's done at once
    m = _metrics(client)
    assert _value(m, "pipesets_job_queue", kind="schedule.run", status="queued") == 0
    assert _value(m, "pipesets_jobs_total", kind="schedule.run", outcome="done") >= 1
    assert jobs.get(job_id)["status"] == "done"


def test_metrics_token(client, env):
    env.setenv("METRICS_TOKEN", "s3cret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    env.delenv("METRICS_TOKEN")


# ── Traces ────────────────────────────────────────────────────────────────────

def test_an_llm_run_is_one_trace_keyed_by_its_run_id(client, key, app_id, spans):
    _run(client, key, app_id, prompt="secret prompt text")
    done = spans.get_finished_spans()
    root = next(s for s in done if s.name == "pipesets.run")
    run_id = root.attributes["pipesets.run_id"]
    assert root.context.trace_id == uuid.UUID(run_id).int, "look a run up in the tracing backend by its id"
    assert root.attributes["pipesets.app_id"] == app_id and root.attributes["gen_ai.system"] == "ollama"
    chat = next(s for s in done if s.name == "chat llama3")
    assert chat.parent.span_id == root.context.span_id and chat.context.trace_id == root.context.trace_id
    assert root.start_time <= chat.start_time <= chat.end_time <= root.end_time
    assert "pipesets.prompt" not in root.attributes, "content stays out of spans by default"


def test_content_capture_is_opt_in(client, key, app_id, spans, env):
    env.setenv("OTEL_CAPTURE_CONTENT", "1")
    _run(client, key, app_id, prompt="please include me")
    root = next(s for s in spans.get_finished_spans() if s.name == "pipesets.run")
    assert "please include me" in root.attributes["pipesets.prompt"]
    env.delenv("OTEL_CAPTURE_CONTENT")


def test_recorded_steps_become_child_spans_at_their_offsets(spans):
    run_id = str(uuid.uuid4())
    telemetry.record_run({"run_id": run_id, "node_type": "llm", "status": "error", "error": "tool blew up",
                          "provider": "openai", "model": "gpt-x", "latency_ms": 2000, "spans_json": json.dumps([
                              {"span_type": "llm", "step": 1, "start_ms": 100, "model": "gpt-x", "provider": "openai",
                               "latency_ms": 800, "finish_reason": "tool_calls", "status": "success"},
                              {"span_type": "tool", "step": 1, "start_ms": 950, "name": "web_search",
                               "latency_ms": 500, "status": "error", "error": "timeout"}])})
    by_name = {s.name: s for s in spans.get_finished_spans()}
    root, chat, tool = by_name["pipesets.run"], by_name["chat gpt-x"], by_name["execute_tool web_search"]
    ms = lambda a, b: round((a - b) / 1e6)   # noqa: E731
    assert ms(chat.start_time, root.start_time) == 100
    assert ms(tool.start_time, root.start_time) == 950
    assert ms(tool.end_time, tool.start_time) == 500
    assert tool.attributes["gen_ai.tool.name"] == "web_search"
    assert not tool.status.is_ok and not root.status.is_ok


def test_a_master_agent_run_is_a_trace_with_a_span_per_step(client, spans):
    from routers.agents import ChildAgentConfig, MasterAgentRunRequest, run_master
    ctx = RequestContext(tenant_id="tenant_demo", project_id="proj_research", user_id="user_admin")
    req = MasterAgentRunRequest(goal="Say hi", run_id="run-telemetry-agent", provider="mock", model="mock-gpt-4",
                                children=[ChildAgentConfig(agent_id="c", role="writer", label="W", provider="mock",
                                                           model="mock-gpt-4")])
    res = asyncio.run(run_master(req, ctx, app_id="app_agents"))
    assert res.status == "completed"
    done = spans.get_finished_spans()
    root = next(s for s in done if s.name == "pipesets.run")
    assert root.attributes["pipesets.kind"] == "master_agent"
    assert root.context.trace_id == telemetry.trace_id_for("run-telemetry-agent")
    steps = [s for s in done if s.name.startswith("agent ")]
    assert len(steps) == res.total_steps and all(s.parent.span_id == root.context.span_id for s in steps)
    assert telemetry.RUNS.labels("master_agent", "app_agents", "completed")._value.get() >= 1
    assert root.attributes["pipesets.timing"] == "recorded"


def test_parallel_agent_steps_overlap_at_their_recorded_starts(spans):
    started = time.time() - 10
    step = lambda n, agent, at, ms: SimpleNamespace(   # noqa: E731
        step=n, agent=agent, role="r", input="", output="", duration_ms=ms, started_at=at, effective_provider="mock",
        effective_model="m", total_tokens=0, cost_usd=0.0, attempt_count=1, used_fallback=False)
    result = SimpleNamespace(run_id=str(uuid.uuid4()), status="completed", strategy="parallel", total_steps=3,
                             resumed_steps=0, goal="g", final_answer="a", error=None, steps=[
                                 step(1, "A", started + 1, 3000), step(2, "B", started + 1, 2000),
                                 step(3, "Restored", None, 1000)])   # e.g. from an older checkpoint
    telemetry.record_agent_run(result, started, "app_parallel")

    done = spans.get_finished_spans()
    root = next(s for s in done if s.name == "pipesets.run")
    by_name = {s.name: s for s in done}
    a, b, restored = by_name["agent A"], by_name["agent B"], by_name["agent Restored"]
    ms = lambda x, y: round((x - y) / 1e6)   # noqa: E731
    assert ms(a.start_time, root.start_time) == ms(b.start_time, root.start_time) == 1000, "both started together"
    assert ms(a.end_time, a.start_time) == 3000 and ms(b.end_time, b.start_time) == 2000
    assert ms(restored.start_time, a.end_time) == 0, "no start time: follows the latest step to finish"
    assert root.attributes["pipesets.timing"] == "sequential"


@jobs.handler("test.traced")
async def _traced(payload, job):
    telemetry.record_run({"run_id": payload["run_id"], "node_type": "llm", "status": "success", "latency_ms": 5})


def test_a_job_gets_a_span_and_its_runs_link_to_it(spans):
    run_id = str(uuid.uuid4())
    jobs.enqueue("test.traced", {"run_id": run_id})
    asyncio.run(jobs.Worker(kinds=["test.traced"]).drain())
    done = spans.get_finished_spans()
    job = next(s for s in done if s.name == "job test.traced")
    run = next(s for s in done if s.name == "pipesets.run")
    assert run.context.trace_id == uuid.UUID(run_id).int, "a run keeps its own trace inside a job"
    assert [link.context.span_id for link in run.links] == [job.context.span_id]
    assert telemetry.JOBS.labels("test.traced", "done")._value.get() >= 1


def test_tracing_is_off_without_an_endpoint(env):
    env.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    env.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    telemetry.use_exporter(None)
    assert telemetry.tracer() is None
    env.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    assert telemetry.tracing_enabled()
    env.delenv("OTEL_EXPORTER_OTLP_ENDPOINT")


# ── Stream events ─────────────────────────────────────────────────────────────

def test_the_stream_reports_each_step_as_it_finishes(client, key, app_id):
    r = _run(client, key, app_id, stream=True)
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    trace = [e for e in events if e["type"] == "trace"]
    assert trace and trace[0]["span"] == "llm" and trace[0]["step"] == 1
    assert trace[0]["duration_ms"] >= 0 and trace[0]["start_ms"] >= 0
    assert [e["type"] for e in events].index("trace") < [e["type"] for e in events].index("meta")
