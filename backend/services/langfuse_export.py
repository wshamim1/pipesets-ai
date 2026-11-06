"""
Langfuse trace export.

Every row written by routers.traces.write_trace() is mirrored to Langfuse via
its public ingestion API (batch endpoint) — no SDK dependency, just httpx.
Export is fire-and-forget on a daemon thread: a slow or unreachable Langfuse
never delays or fails a run.

Env:
  LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY   both required to enable export
  LANGFUSE_HOST                               default https://cloud.langfuse.com
  LANGFUSE_REDACT=1                           omit prompt/output/tool input+output text;
                                              only metadata (model, tokens, cost, latency) is sent

Mapping:
  run_id            -> Langfuse trace id (rows sharing a run_id group together)
  traces row        -> one `generation` (model, token usage, cost, latency)
  spans_json items  -> child `span`s (tool executions) / per-step generations
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("pipesets-ai-backend")

_TIMEOUT_S = 10.0


def _settings() -> Optional[Dict[str, str]]:
    pub = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    sec = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not pub or not sec:
        return None
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").strip().rstrip("/")
    return {"public_key": pub, "secret_key": sec, "host": host}


def is_enabled() -> bool:
    return _settings() is not None


def _redact() -> bool:
    return os.environ.get("LANGFUSE_REDACT", "").lower() in ("1", "true", "yes")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_batch(trace: Dict[str, Any], redact: bool) -> List[Dict[str, Any]]:
    """Translate one write_trace() payload into Langfuse ingestion events."""
    now = datetime.now(timezone.utc)
    latency_ms = int(trace.get("latency_ms") or 0)
    start = now - timedelta(milliseconds=latency_ms)

    run_id = trace["run_id"]
    gen_id = trace["id"]
    is_error = trace.get("status") == "error"
    model = trace.get("effective_model") or trace.get("model") or None

    prompt = None if redact else trace.get("prompt_preview")
    output = None if redact else trace.get("output_preview")

    try:
        meta = json.loads(trace.get("metadata_json") or "{}")
    except (TypeError, ValueError):
        meta = {}
    meta.update({
        "app_id": trace.get("app_id"),
        "node_id": trace.get("node_id"),
        "node_type": trace.get("node_type"),
        "provider": trace.get("effective_provider") or trace.get("provider"),
        "attempt_count": trace.get("attempt_count"),
        "used_fallback": bool(trace.get("used_fallback")),
    })

    def event(kind: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": str(uuid.uuid4()), "type": kind, "timestamp": _iso(now), "body": body}

    events: List[Dict[str, Any]] = [
        event("trace-create", {
            "id": run_id,
            "name": f"{trace.get('node_type', 'llm')} run",
            "input": prompt,
            "output": output,
            "metadata": meta,
            "tags": [t for t in (trace.get("app_id"), trace.get("node_type")) if t],
            "timestamp": _iso(start),
        }),
        event("generation-create", {
            "id": gen_id,
            "traceId": run_id,
            "name": f"{trace.get('node_type', 'llm')} generation",
            "model": model,
            "input": prompt,
            "output": output,
            "startTime": _iso(start),
            "endTime": _iso(now),
            "level": "ERROR" if is_error else "DEFAULT",
            "statusMessage": trace.get("error") if is_error else None,
            "usageDetails": {
                "input": int(trace.get("prompt_tokens") or 0),
                "output": int(trace.get("completion_tokens") or 0),
                "total": int(trace.get("total_tokens") or 0),
            },
            "costDetails": {"total": float(trace.get("cost_usd") or 0.0)},
            "metadata": meta,
        }),
    ]

    # Tool, middleware, retrieval and embedding spans (the generation above is the model call),
    # laid out sequentially inside the run window.
    try:
        spans = json.loads(trace.get("spans_json") or "[]")
    except (TypeError, ValueError):
        spans = []
    cursor = start
    for i, sp in enumerate(spans):
        if sp.get("span_type") == "llm":
            continue
        dur = int(sp.get("latency_ms") or 0)
        sp_start, sp_end = cursor, cursor + timedelta(milliseconds=dur)
        cursor = sp_end
        events.append(event("span-create", {
            "id": f"{gen_id}-span-{i}",
            "traceId": run_id,
            "parentObservationId": gen_id,
            "name": sp.get("name") or sp.get("tool_id") or sp.get("span_type") or "tool",
            "startTime": _iso(sp_start),
            "endTime": _iso(sp_end),
            "input": None if redact else sp.get("input_preview"),
            "output": None if redact else sp.get("output_preview"),
            "level": "ERROR" if sp.get("status") == "error" else "DEFAULT",
            "metadata": {"type": sp.get("span_type"), "step": sp.get("step"), "tool_id": sp.get("tool_id")},
        }))
    return events


def _send(trace: Dict[str, Any]) -> None:
    cfg = _settings()
    if not cfg:
        return
    try:
        batch = build_batch(trace, _redact())
        resp = httpx.post(
            f"{cfg['host']}/api/public/ingestion",
            json={"batch": batch},
            auth=(cfg["public_key"], cfg["secret_key"]),
            timeout=_TIMEOUT_S,
        )
        # 207 = multi-status; individual events may have failed.
        if resp.status_code >= 400:
            logger.warning(f"Langfuse export failed: HTTP {resp.status_code} {resp.text[:200]}")
        elif resp.status_code == 207:
            errors = (resp.json() or {}).get("errors") or []
            if errors:
                logger.warning(f"Langfuse export: {len(errors)} event(s) rejected: {errors[:2]}")
    except Exception as e:  # never let observability break a run
        logger.warning(f"Langfuse export error: {e}")


def export_trace_async(trace: Dict[str, Any]) -> None:
    """Mirror a trace row to Langfuse on a daemon thread. No-op when not configured."""
    if not is_enabled():
        return
    threading.Thread(target=_send, args=(trace,), daemon=True, name="langfuse-export").start()
