"""
telemetry.py — Prometheus metrics and OpenTelemetry traces for runs, LLM calls, tool calls and jobs.

Metrics (GET /metrics on the API; WORKER_METRICS_PORT on ``manage.py worker``)
------------------------------------------------------------------------------
  pipesets_runs_total{kind, app, status}            finished runs (kind: llm | master_agent)
  pipesets_run_duration_seconds{kind, app}          histogram → p95 with histogram_quantile
  pipesets_llm_calls_total{provider, model, status} one per model call (each step of a tool loop)
  pipesets_llm_call_duration_seconds{provider, model}
  pipesets_llm_tokens_total{provider, model, type}  type: prompt | completion
  pipesets_llm_cost_usd_total{provider, model}
  pipesets_tool_calls_total{tool, status}, pipesets_tool_call_duration_seconds{tool}
  pipesets_jobs_total{kind, outcome}                outcome: done | retry | dead | cancelled | lost
  pipesets_job_duration_seconds{kind}
  pipesets_job_queue{kind, status}                  queued / running / dead jobs, read from the DB
  pipesets_job_queue_oldest_seconds{kind}           how long the oldest due job has waited

Counters are per process: sum them across pods in queries. The queue gauges come from the shared
DB, so every pod reports the same numbers: use max(), not sum(). Error rate:
``sum(rate(pipesets_runs_total{status="failed"}[5m])) / sum(rate(pipesets_runs_total[5m]))``.

Traces (OTLP over HTTP, when OTEL_EXPORTER_OTLP_ENDPOINT or …_TRACES_ENDPOINT is set)
--------------------------------------------------------------------------------------
Each finished run becomes one trace: a ``pipesets.run`` span with a child per LLM call
(``chat <model>``) and tool call (``execute_tool <name>``), or per agent step for Master Agent
runs, placed at their recorded offsets. The trace id is derived from the run id (a UUID run id
is used as is), so a run found in Pipesets can be looked up in Tempo / Jaeger / Datadog by id.
Jobs get a live ``job <kind>`` span. Standard OTEL_* variables configure the exporter
(OTEL_EXPORTER_OTLP_HEADERS for auth, OTEL_SERVICE_NAME, default ``pipesets-ai``).

Prompt and output text stay out of spans unless OTEL_CAPTURE_CONTENT=1.
Attributes follow the GenAI semantic conventions where one exists (gen_ai.*).
"""

import contextlib
import contextvars
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily

logger = logging.getLogger("pipesets-ai-backend")

REGISTRY = CollectorRegistry()
_SECONDS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)

RUNS = Counter("pipesets_runs_total", "Finished runs", ["kind", "app", "status"], registry=REGISTRY)
RUN_SECONDS = Histogram("pipesets_run_duration_seconds", "Run duration", ["kind", "app"], buckets=_SECONDS,
                        registry=REGISTRY)
LLM_CALLS = Counter("pipesets_llm_calls_total", "Model calls", ["provider", "model", "status"], registry=REGISTRY)
LLM_SECONDS = Histogram("pipesets_llm_call_duration_seconds", "Model call duration", ["provider", "model"],
                        buckets=_SECONDS, registry=REGISTRY)
TOKENS = Counter("pipesets_llm_tokens_total", "Tokens", ["provider", "model", "type"], registry=REGISTRY)
COST = Counter("pipesets_llm_cost_usd_total", "Model spend in USD", ["provider", "model"], registry=REGISTRY)
PHASE_SECONDS = Histogram("pipesets_phase_duration_seconds",
                          "Time a run spends outside model and tool calls (middleware, retrieval, embedding)",
                          ["phase"], buckets=_SECONDS, registry=REGISTRY)
TOOL_CALLS = Counter("pipesets_tool_calls_total", "Tool calls", ["tool", "status"], registry=REGISTRY)
TOOL_SECONDS = Histogram("pipesets_tool_call_duration_seconds", "Tool call duration", ["tool"], buckets=_SECONDS,
                         registry=REGISTRY)
JOBS = Counter("pipesets_jobs_total", "Finished job attempts", ["kind", "outcome"], registry=REGISTRY)
JOB_SECONDS = Histogram("pipesets_job_duration_seconds", "Job attempt duration", ["kind"], buckets=_SECONDS,
                        registry=REGISTRY)

# trace node_type / agent status → the runs_total status label
_STATUS = {"success": "completed", "error": "failed"}


class _QueueCollector:
    """Queue depth from the jobs table, read at scrape time."""

    def collect(self):
        depth = GaugeMetricFamily("pipesets_job_queue", "Jobs by status", labels=["kind", "status"])
        oldest = GaugeMetricFamily("pipesets_job_queue_oldest_seconds", "Wait of the oldest due queued job",
                                   labels=["kind"])
        try:
            from db import get_db_connection
            from services.jobs import _ts
            conn = get_db_connection()
            try:
                for r in conn.execute("SELECT kind, status, COUNT(*) AS n FROM jobs WHERE status IN "
                                      "('queued', 'running', 'dead') GROUP BY kind, status").fetchall():
                    depth.add_metric([r["kind"], r["status"]], int(r["n"]))
                now = datetime.now(timezone.utc)
                for r in conn.execute("SELECT kind, MIN(run_after) AS due FROM jobs WHERE status = 'queued' "
                                      "AND run_after <= ? GROUP BY kind", (_ts(),)).fetchall():
                    due = datetime.strptime(r["due"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                    oldest.add_metric([r["kind"]], max(0.0, (now - due).total_seconds()))
            finally:
                conn.close()
        except Exception:
            logger.exception("Reading queue depth for /metrics failed")
        yield depth
        yield oldest


REGISTRY.register(_QueueCollector())


# ── Tracing setup ─────────────────────────────────────────────────────────────

_provider = None
_tracer = None
_next_trace_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("next_trace_id", default=None)


def tracing_enabled() -> bool:
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"))


def capture_content() -> bool:
    return os.getenv("OTEL_CAPTURE_CONTENT", "").strip().lower() in ("1", "true", "yes")


def _make_provider(exporter=None, simple: bool = False):
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

    class RunIdGenerator(RandomIdGenerator):
        """A trace started for a run gets the trace id derived from the run id."""
        def generate_trace_id(self) -> int:
            return _next_trace_id.get() or super().generate_trace_id()

    provider = TracerProvider(resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "pipesets-ai")}),
                              id_generator=RunIdGenerator())
    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter()   # endpoint, headers, timeout from OTEL_EXPORTER_OTLP_*
    provider.add_span_processor(SimpleSpanProcessor(exporter) if simple else BatchSpanProcessor(exporter))
    return provider


def tracer():
    """The tracer, or None when tracing is off."""
    global _provider, _tracer
    if _tracer is None and tracing_enabled():
        _provider = _make_provider()
        _tracer = _provider.get_tracer("pipesets-ai")
        logger.info("OpenTelemetry tracing on")
    return _tracer


def use_exporter(exporter) -> None:
    """Send spans to ``exporter`` synchronously (tests); None turns tracing back to the env config."""
    global _provider, _tracer
    if _provider is not None:
        _provider.shutdown()
    _provider = _make_provider(exporter, simple=True) if exporter is not None else None
    _tracer = _provider.get_tracer("pipesets-ai") if _provider else None


def shutdown() -> None:
    """Flush spans still buffered (at process exit)."""
    if _provider is not None:
        _provider.shutdown()


def trace_id_for(run_id: str) -> int:
    try:
        tid = uuid.UUID(str(run_id)).int
    except ValueError:
        tid = int(hashlib.sha256(str(run_id).encode()).hexdigest()[:32], 16)
    return tid or 1


def _ns(seconds: float) -> int:
    return int(seconds * 1e9)


def _root(name: str, run_id: str, start: float, attributes: Dict[str, Any]):
    """Start a run's root span in a trace of its own (id from the run id). A run inside a job
    links to the job's span instead of nesting under it."""
    from opentelemetry import trace as ot
    from opentelemetry.context import Context

    current = ot.get_current_span().get_span_context()
    links = [ot.Link(current)] if current.is_valid else None
    token = _next_trace_id.set(trace_id_for(run_id))
    try:
        return tracer().start_span(name, context=Context(), start_time=_ns(start), attributes=attributes, links=links)
    finally:
        _next_trace_id.reset(token)


def _set_error(span, message: Optional[str]) -> None:
    from opentelemetry.trace import Status, StatusCode
    span.set_status(Status(StatusCode.ERROR, (message or "error")[:500]))


def _clean(attrs: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in attrs.items() if v is not None and v != ""}


# ── LLM runs (one traces row: write_trace) ────────────────────────────────────

def record_run(t: Dict[str, Any]) -> None:
    """Metrics and a trace for one finished LLM run, from its write_trace() payload. Never raises."""
    try:
        _run_metrics(t)
    except Exception:
        logger.exception("Recording run metrics failed")
    try:
        if tracer() is not None:
            _export_run(t)
    except Exception:
        logger.exception("Exporting run trace failed")


def _simulated(t: Dict[str, Any]) -> bool:
    """A mock / no-key run: answered without calling a model."""
    try:
        return bool(json.loads(t.get("metadata_json") or "{}").get("simulated"))
    except (json.JSONDecodeError, TypeError, AttributeError):
        return False


def _spans(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return json.loads(t.get("spans_json") or "[]") or []
    except (json.JSONDecodeError, TypeError):
        return []


def _run_metrics(t: Dict[str, Any]) -> None:
    kind, app = t.get("node_type") or "llm", t.get("app_id") or "none"
    status = _STATUS.get(t.get("status") or "", t.get("status") or "completed")
    RUNS.labels(kind, app, status).inc()
    RUN_SECONDS.labels(kind, app).observe((t.get("latency_ms") or 0) / 1000)
    provider = t.get("effective_provider") or t.get("provider") or "unknown"
    model = t.get("effective_model") or t.get("model") or "unknown"
    spans = _spans(t)
    for s in spans:
        if s.get("span_type") == "tool":
            TOOL_CALLS.labels(s.get("name") or "tool", s.get("status") or "success").inc()
            TOOL_SECONDS.labels(s.get("name") or "tool").observe((s.get("latency_ms") or 0) / 1000)
        elif s.get("span_type") in _PHASES:
            PHASE_SECONDS.labels(s["span_type"]).observe((s.get("latency_ms") or 0) / 1000)
    if _simulated(t):
        return   # no model was called: no LLM call, token or cost metrics
    llm_spans = [s for s in spans if s.get("span_type") == "llm"]
    for s in llm_spans:
        LLM_CALLS.labels(s.get("provider") or provider, s.get("model") or model, s.get("status") or "success").inc()
        LLM_SECONDS.labels(s.get("provider") or provider, s.get("model") or model).observe((s.get("latency_ms") or 0) / 1000)
    if not llm_spans:   # no per-step record (non-streaming /api/run, errors before the first step)
        LLM_CALLS.labels(provider, model, "error" if status == "failed" else "success").inc()
        LLM_SECONDS.labels(provider, model).observe((t.get("latency_ms") or 0) / 1000)
    TOKENS.labels(provider, model, "prompt").inc(t.get("prompt_tokens") or 0)
    TOKENS.labels(provider, model, "completion").inc(t.get("completion_tokens") or 0)
    COST.labels(provider, model).inc(t.get("cost_usd") or 0.0)


_PHASES = ("middleware", "retrieval", "embedding")


def _phase_span(s: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Name and attributes for a middleware / retrieval / embedding span (GenAI conventions where they exist)."""
    kind = s["span_type"]
    if kind == "embedding":
        return f"embeddings {s.get('model') or s.get('name')}", {
            "gen_ai.operation.name": "embeddings", "gen_ai.system": s.get("provider"),
            "gen_ai.request.model": s.get("model")}
    if kind == "retrieval":
        return f"retrieval {s.get('collection') or s.get('name')}", {
            "pipesets.collection": s.get("collection"), "pipesets.chunks": s.get("chunks")}
    return f"middleware {s.get('name')}", {"pipesets.middleware": s.get("name")}


def _export_run(t: Dict[str, Any]) -> None:
    end = time.time()
    start = end - (t.get("latency_ms") or 0) / 1000
    content = capture_content()
    root = _root("pipesets.run", t["run_id"], start, _clean({
        "pipesets.run_id": t["run_id"], "pipesets.app_id": t.get("app_id"), "pipesets.node_id": t.get("node_id"),
        "pipesets.kind": t.get("node_type") or "llm", "pipesets.status": t.get("status"),
        "gen_ai.system": t.get("effective_provider") or t.get("provider"),
        "gen_ai.request.model": t.get("model"), "gen_ai.response.model": t.get("effective_model"),
        "gen_ai.usage.input_tokens": t.get("prompt_tokens"), "gen_ai.usage.output_tokens": t.get("completion_tokens"),
        "pipesets.cost_usd": t.get("cost_usd"), "pipesets.attempt_count": t.get("attempt_count"),
        "pipesets.used_fallback": bool(t.get("used_fallback")),
        "pipesets.simulated": True if _simulated(t) else None,
        "pipesets.prompt": t.get("prompt_preview") if content else None,
        "pipesets.output": t.get("output_preview") if content else None,
    }))
    from opentelemetry import trace as ot
    ctx = ot.set_span_in_context(root)
    cursor = start
    for s in _spans(t):
        s_start = start + s["start_ms"] / 1000 if s.get("start_ms") is not None else cursor
        s_end = s_start + (s.get("latency_ms") or 0) / 1000
        cursor = s_end
        if s.get("span_type") in _PHASES:
            name, attrs = _phase_span(s)
        elif s.get("span_type") == "tool":
            name, attrs = f"execute_tool {s.get('name')}", {
                "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": s.get("name"),
                "pipesets.tool_id": s.get("tool_id"), "pipesets.step": s.get("step"),
                "pipesets.tool.input": s.get("input_preview") if content else None,
                "pipesets.tool.output": s.get("output_preview") if content else None}
        else:
            name, attrs = f"chat {s.get('model') or t.get('model')}", {
                "gen_ai.operation.name": "chat", "gen_ai.system": s.get("provider"),
                "gen_ai.request.model": s.get("model"), "gen_ai.response.finish_reasons": [s["finish_reason"]]
                if s.get("finish_reason") else None, "pipesets.step": s.get("step"),
                "pipesets.tool_calls": s.get("tool_calls_count"), "pipesets.cost_usd": s.get("cost_usd")}
        child = tracer().start_span(name, context=ctx, start_time=_ns(s_start), attributes=_clean(attrs))
        if s.get("status") == "error":
            _set_error(child, s.get("error"))
        child.end(end_time=_ns(min(s_end, end)))
    if t.get("status") == "error":
        _set_error(root, t.get("error"))
    root.end(end_time=_ns(end))


# ── Master Agent runs ─────────────────────────────────────────────────────────

def record_agent_run(result: Any, started: float, app_id: Optional[str]) -> None:
    """Metrics and a trace for a finished (or paused) Master Agent run. ``started`` is time.time()
    at its start. Steps are placed at their recorded ``started_at``, so parallel steps overlap;
    steps without one (restored from an older checkpoint) follow the previous step. Never raises."""
    try:
        app = app_id or "none"
        RUNS.labels("master_agent", app, result.status).inc()
        RUN_SECONDS.labels("master_agent", app).observe(max(0.0, time.time() - started))
        for s in result.steps:
            provider, model = s.effective_provider or "unknown", s.effective_model or "unknown"
            LLM_CALLS.labels(provider, model, "success").inc()
            LLM_SECONDS.labels(provider, model).observe(s.duration_ms / 1000)
            COST.labels(provider, model).inc(s.cost_usd or 0.0)
    except Exception:
        logger.exception("Recording agent run metrics failed")
    try:
        if tracer() is not None:
            _export_agent_run(result, started, app_id)
    except Exception:
        logger.exception("Exporting agent run trace failed")


def _started(step: Any) -> Optional[float]:
    return getattr(step, "started_at", None)


def _export_agent_run(result: Any, started: float, app_id: Optional[str]) -> None:
    from opentelemetry import trace as ot
    end = max(time.time(), started)
    content = capture_content()
    root = _root("pipesets.run", result.run_id, started, _clean({
        "pipesets.run_id": result.run_id, "pipesets.app_id": app_id, "pipesets.kind": "master_agent",
        "pipesets.status": result.status, "pipesets.strategy": result.strategy,
        "pipesets.steps": result.total_steps, "pipesets.resumed_steps": result.resumed_steps,
        # "recorded": every span sits at its real start; "sequential": some were laid end to end
        "pipesets.timing": "recorded" if all(_started(s) is not None for s in result.steps) else "sequential",
        "pipesets.prompt": result.goal if content else None,
        "pipesets.output": result.final_answer if content else None,
    }))
    ctx = ot.set_span_in_context(root)
    cursor = started
    for s in result.steps:
        s_start = min(max(_started(s) or cursor, started), end)
        s_end = min(s_start + s.duration_ms / 1000, end)
        child = tracer().start_span(f"agent {s.agent}", context=ctx, start_time=_ns(s_start), attributes=_clean({
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": s.agent, "pipesets.role": s.role,
            "pipesets.step": s.step, "gen_ai.system": s.effective_provider, "gen_ai.request.model": s.effective_model,
            "pipesets.total_tokens": s.total_tokens, "pipesets.cost_usd": s.cost_usd,
            "pipesets.attempt_count": s.attempt_count, "pipesets.used_fallback": s.used_fallback,
            "pipesets.input": s.input[:4000] if content else None,
            "pipesets.output": s.output[:4000] if content else None,
        }))
        child.end(end_time=_ns(s_end))
        cursor = max(cursor, s_end)
    if result.status in ("failed", "rejected"):
        _set_error(root, result.error)
    root.end(end_time=_ns(end))


# ── Jobs ──────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def job_span(job: Any) -> Iterator[None]:
    """A live span around one job attempt (a no-op with tracing off)."""
    t = tracer()
    if t is None:
        yield
        return
    with t.start_as_current_span(f"job {job.kind}", attributes={
            "pipesets.job_id": job.id, "pipesets.job_kind": job.kind, "pipesets.attempt": job.attempts,
            "pipesets.max_attempts": job.max_attempts}):
        yield


def record_job(kind: str, outcome: str, seconds: float) -> None:
    JOBS.labels(kind, outcome).inc()
    JOB_SECONDS.labels(kind).observe(max(0.0, seconds))


def metrics_text() -> bytes:
    from prometheus_client import generate_latest
    return generate_latest(REGISTRY)

