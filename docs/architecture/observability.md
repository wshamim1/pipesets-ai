# Observability

There are three layers, from built-in to external:

1. **Traces in the app database.** Every run writes a trace with per-step detail: model calls,
   tool calls and agent steps, plus tokens, latency and cost (`routers/traces.py`). **Monitor**
   in the UI reads these for runs, traces, logs, sessions, costs and budgets.
2. **Prometheus metrics and OpenTelemetry traces**, in
   [services/telemetry.py](../../backend/services/telemetry.py).
3. **Langfuse mirroring**, optional and with a redaction mode, in `services/langfuse_export.py`.

## Metrics

Metrics are served at `GET /metrics` on the API. A standalone worker serves them on
`WORKER_METRICS_PORT`.

| Metric | Labels |
|---|---|
| `pipesets_runs_total`, `pipesets_run_duration_seconds` | `kind` (llm, master_agent), `app`, `status` |
| `pipesets_llm_calls_total`, `pipesets_llm_call_duration_seconds` | `provider`, `model`, `status` |
| `pipesets_llm_tokens_total` | `provider`, `model`, `type` (prompt, completion) |
| `pipesets_llm_cost_usd_total` | `provider`, `model` |
| `pipesets_tool_calls_total`, `pipesets_tool_call_duration_seconds` | `tool`, `status` |
| `pipesets_jobs_total`, `pipesets_job_duration_seconds` | `kind`, `outcome` |
| `pipesets_job_queue`, `pipesets_job_queue_oldest_seconds` | `kind`, `status` |

Counters are counted per process, so `sum` them across pods. The queue gauges are read from the
shared database, so every pod reports the same value; use `max`, not `sum`.

A ready-made Grafana dashboard is in
[deploy/grafana/pipesets-dashboard.json](../../deploy/grafana/pipesets-dashboard.json).

## OpenTelemetry

When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, each finished run is exported as one trace. It has a
`pipesets.run` span, with a child span for each LLM call (`chat <model>`) and each tool call
(`execute_tool <name>`), or for each agent step in a Master Agent run. The trace id comes from the
run id, so you can find a run from Pipesets in Tempo, Jaeger or Datadog. Jobs get a live
`job <kind>` span.

## Logs

The backend logs to stdout, or to `backend.log` when started with `start.sh`. Every log line goes
through `services/log_redaction.py`, which masks API keys, bearer tokens and sealed values.
