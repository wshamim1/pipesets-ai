"""
Observability & Tracing router.

Every call to /api/run writes a trace row via write_trace(), which also mirrors it to Langfuse
(when configured) and to metrics / OpenTelemetry (services/telemetry.py).
GET /api/traces              — list recent traces (last 200, newest first)
GET /api/traces/cost-summary — aggregated cost/token/latency breakdown
GET /api/traces/{run_id}     — all spans for a single run
DELETE /api/traces           — clear the caller's traces

Every read is limited to the caller's tenant / project: a trace takes the scope of the run that
wrote it (or of its app, outside one).
"""

import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from db import get_db_connection
from models import TraceRecord
from services.request_context import get_request_context

logger = logging.getLogger("pipesets-ai-backend")

router = APIRouter(tags=["traces"])


# ── Writer (called from run.py) ───────────────────────────────────────────────

def write_trace(
    *,
    run_id: str,
    app_id: Optional[str] = None,
    node_id: Optional[str] = None,
    node_type: str = "llm",
    provider: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: int = 0,
    cost_usd: float = 0.0,
    attempt_count: int = 1,
    used_fallback: bool = False,
    effective_provider: Optional[str] = None,
    effective_model: Optional[str] = None,
    status: str = "success",
    error: Optional[str] = None,
    prompt_preview: Optional[str] = None,
    output_preview: Optional[str] = None,
    metadata_json: Optional[str] = None,
    spans_json: Optional[str] = None,
) -> str:
    """Insert a trace row and return its id."""
    from services.secret_store import current_scope_ids   # lazy: avoids an import cycle with the runners

    trace_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    conn = get_db_connection()
    try:
        scope = current_scope_ids()
        if scope is None and app_id:   # a thread that lost the request's context: fall back to the app's scope
            row = conn.execute("SELECT tenant_id, project_id FROM apps WHERE id = ?", (app_id,)).fetchone()
            scope = (row["tenant_id"], row["project_id"]) if row else None
        tenant_id, project_id = scope or (None, None)
        conn.execute(
            """
            INSERT INTO traces (
                tenant_id, project_id, id, run_id, app_id, node_id, node_type,
                provider, model,
                prompt_tokens, completion_tokens, total_tokens,
                latency_ms, cost_usd,
                attempt_count, used_fallback, effective_provider, effective_model,
                status, error, prompt_preview, output_preview, metadata_json, spans_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id, project_id, trace_id, run_id, app_id, node_id, node_type,
                provider, model,
                prompt_tokens, completion_tokens, total_tokens,
                latency_ms, cost_usd,
                int(attempt_count), 1 if used_fallback else 0, effective_provider, effective_model,
                status, error, prompt_preview, output_preview, metadata_json, spans_json, created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    payload = {
        "id": trace_id, "run_id": run_id, "app_id": app_id, "node_id": node_id,
        "node_type": node_type, "provider": provider, "model": model,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "total_tokens": total_tokens, "latency_ms": latency_ms, "cost_usd": cost_usd,
        "attempt_count": attempt_count, "used_fallback": used_fallback,
        "effective_provider": effective_provider, "effective_model": effective_model,
        "status": status, "error": error, "prompt_preview": prompt_preview,
        "output_preview": output_preview, "metadata_json": metadata_json,
        "spans_json": spans_json,
    }
    try:
        from services.langfuse_export import export_trace_async
        export_trace_async(payload)
    except Exception as e:
        logger.warning(f"Langfuse export setup failed: {e}")
    from services import telemetry
    telemetry.record_run(payload)   # Prometheus metrics + an OpenTelemetry trace when OTLP is configured
    return trace_id


def _row_to_trace(row) -> TraceRecord:
    keys = row.keys() if hasattr(row, "keys") else []
    return TraceRecord(
        id=row["id"],
        run_id=row["run_id"],
        app_id=row["app_id"],
        node_id=row["node_id"],
        node_type=row["node_type"],
        provider=row["provider"],
        model=row["model"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        total_tokens=row["total_tokens"],
        latency_ms=row["latency_ms"],
        cost_usd=row["cost_usd"],
        attempt_count=row["attempt_count"] if "attempt_count" in keys else 1,
        used_fallback=row["used_fallback"] if "used_fallback" in keys else 0,
        effective_provider=row["effective_provider"] if "effective_provider" in keys else None,
        effective_model=row["effective_model"] if "effective_model" in keys else None,
        status=row["status"],
        error=row["error"],
        prompt_preview=row["prompt_preview"] if "prompt_preview" in keys else None,
        output_preview=row["output_preview"] if "output_preview" in keys else None,
        metadata_json=row["metadata_json"] if "metadata_json" in keys else None,
        spans_json=row["spans_json"] if "spans_json" in keys else None,
        created_at=row["created_at"],
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _scope(request: Request) -> tuple:
    ctx = get_request_context(request)
    return ctx.tenant_id, ctx.project_id


# Positional "?" only: the db wrapper binds params as a tuple, so named params would bind their keys
_IN_SCOPE = "tenant_id = ? AND project_id = ?"


@router.get("/api/traces/cost-summary")
def get_cost_summary(
    request: Request,
    app_id: Optional[str] = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> Dict[str, Any]:
    """
    Return aggregated cost, token, latency and error breakdown for the
    dashboard.  Grouped by (provider, model) and by calendar day (UTC).
    Optionally filtered to a single app.
    """
    conn = get_db_connection()
    try:
        base_filter = f"WHERE {_IN_SCOPE} AND created_at >= date('now', ?)"
        params: List[Any] = [*_scope(request), f"-{days} days"]
        if app_id:
            base_filter += " AND app_id = ?"
            params.append(app_id)

        # ── Overall totals ────────────────────────────────────────────────
        totals_row = conn.execute(
            f"""
            SELECT
                COUNT(*)                          AS total_traces,
                SUM(cost_usd)                     AS total_cost,
                SUM(total_tokens)                 AS total_tokens,
                SUM(prompt_tokens)                AS total_prompt_tokens,
                SUM(completion_tokens)            AS total_completion_tokens,
                AVG(latency_ms)                   AS avg_latency_ms,
                MAX(latency_ms)                   AS max_latency_ms,
                SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS error_count,
                SUM(CASE WHEN used_fallback>0  THEN 1 ELSE 0 END) AS fallback_count
            FROM traces {base_filter}
            """,
            params,
        ).fetchone()

        totals: Dict[str, Any] = dict(totals_row) if totals_row else {}

        # ── Per-model breakdown ───────────────────────────────────────────
        model_rows = conn.execute(
            f"""
            SELECT
                provider,
                model,
                COUNT(*)            AS traces,
                SUM(cost_usd)       AS cost_usd,
                SUM(total_tokens)   AS tokens,
                AVG(latency_ms)     AS avg_latency_ms,
                SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
            FROM traces {base_filter}
            GROUP BY provider, model
            ORDER BY cost_usd DESC
            """,
            params,
        ).fetchall()

        by_model = [dict(r) for r in model_rows]

        # ── Daily cost series (last N days, UTC date) ─────────────────────
        daily_rows = conn.execute(
            f"""
            SELECT
                substr(created_at, 1, 10)  AS day,
                SUM(cost_usd)              AS cost_usd,
                SUM(total_tokens)          AS tokens,
                COUNT(*)                   AS traces,
                SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
            FROM traces {base_filter}
            GROUP BY day
            ORDER BY day ASC
            """,
            params,
        ).fetchall()

        daily = [dict(r) for r in daily_rows]

        # ── Per-app breakdown (only when no app_id filter is active) ──────
        by_app: List[Dict[str, Any]] = []
        if not app_id:
            app_rows = conn.execute(
                f"""
                SELECT
                    COALESCE(app_id, 'unassigned') AS app_id,
                    COUNT(*)            AS traces,
                    SUM(cost_usd)       AS cost_usd,
                    SUM(total_tokens)   AS tokens,
                    AVG(latency_ms)     AS avg_latency_ms
                FROM traces {base_filter}
                GROUP BY app_id
                ORDER BY cost_usd DESC
                LIMIT 20
                """,
                params,
            ).fetchall()
            by_app = [dict(r) for r in app_rows]

    finally:
        conn.close()

    return {
        "days": days,
        "app_id": app_id,
        "totals": totals,
        "by_model": by_model,
        "by_app": by_app,
        "daily": daily,
    }


@router.get("/api/traces", response_model=List[TraceRecord])
def list_traces(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    app_id: Optional[str] = Query(default=None),
):
    """Return the most recent traces, newest first."""
    params: List[Any] = [*_scope(request)] + ([app_id] if app_id else []) + [limit]
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM traces WHERE {_IN_SCOPE}"
            + (" AND app_id = ?" if app_id else "")
            + " ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_trace(r) for r in rows]


@router.get("/api/traces/{run_id}", response_model=List[TraceRecord])
def get_run_traces(run_id: str, request: Request):
    """Return all spans for a single run_id."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM traces WHERE run_id = ? AND {_IN_SCOPE} ORDER BY created_at ASC",
            (run_id, *_scope(request)),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_trace(r) for r in rows]


@router.delete("/api/traces")
def clear_traces(request: Request):
    """Wipe the caller's trace rows (dev/debug use)."""
    conn = get_db_connection()
    try:
        conn.execute(f"DELETE FROM traces WHERE {_IN_SCOPE}", _scope(request))
        conn.commit()
    finally:
        conn.close()
    return {"cleared": True}
