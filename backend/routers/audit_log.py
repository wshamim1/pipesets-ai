"""
audit_log.py — read the admin audit log (written by services/audit.AuditMiddleware).

GET /api/audit-log          — entries for the caller's tenant, newest first
                              ?limit=1..500  &before=<created_at of the last entry seen>
                              &action=<prefix, e.g. "secret.">  &actor=<user id>
                              &outcome=success|denied  &since=<ISO time>  &until=<ISO time>
GET /api/audit-log/export   — every entry matching the same filters, as CSV or JSON Lines
                              (?format=csv|jsonl); the export itself is logged as audit.export
GET /api/audit-log/policy   — retention period (set by the operator) and the action names

Requires the ``audit:read`` ACL (tenant owners have it implicitly). There is no route to change
or delete entries; only the retention purge removes them.
"""

import csv
import io
import json
from datetime import datetime
from typing import Iterator, Literal, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from services import audit
from services.acl import require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/audit-log", tags=["audit-log"])

COLUMNS = ["created_at", "actor", "action", "target_id", "outcome", "status", "method", "path",
           "project_id", "ip", "id"]


def _filters(action, actor, outcome, since, until):
    return {"action": action, "actor": actor, "outcome": outcome, "since": since, "until": until}


@router.get("")
def list_audit_log(request: Request, limit: int = Query(100, ge=1, le=500), before: Optional[str] = None,
                   action: Optional[str] = None, actor: Optional[str] = None,
                   outcome: Optional[Literal["success", "denied"]] = None,
                   since: Optional[str] = None, until: Optional[str] = None):
    ctx = get_request_context(request)
    require_access(ctx, "audit", "read")
    entries = audit.list_entries(ctx.tenant_id, limit=limit, before=before,
                                 **_filters(action, actor, outcome, since, until))
    return {"entries": entries, "next_before": entries[-1]["created_at"] if len(entries) == limit else None}


@router.get("/policy")
def audit_policy(request: Request):
    require_access(get_request_context(request), "audit", "read")
    return {
        "retention_days": audit.retention_days(),
        "actions": sorted(set(audit.AUDITED.values()) | set(audit.SYSTEM_ACTIONS)),
    }


def _csv_rows(entries: Iterator[dict]) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    for e in entries:
        # A leading = + - @ would make a spreadsheet run the cell as a formula
        writer.writerow([("'" + v) if isinstance(v, str) and v[:1] in "=+-@" else v
                         for v in (e.get(c, "") for c in COLUMNS)])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()
    yield buf.getvalue()


@router.get("/export")
def export_audit_log(request: Request, format: Literal["csv", "jsonl"] = "csv",
                     action: Optional[str] = None, actor: Optional[str] = None,
                     outcome: Optional[Literal["success", "denied"]] = None,
                     since: Optional[str] = None, until: Optional[str] = None):
    ctx = get_request_context(request)
    require_access(ctx, "audit", "read")
    # Logged before streaming: who took a copy of the trail is part of the trail
    client = request.client
    audit.record(tenant_id=ctx.tenant_id, project_id=ctx.project_id, actor=ctx.user_id, action="audit.export",
                 target_id=format, outcome="success", status=200, method="GET",
                 path=f"{request.url.path}?{request.url.query}" if request.url.query else request.url.path,
                 ip=client.host if client else "")

    entries = audit.iter_entries(ctx.tenant_id, **_filters(action, actor, outcome, since, until))
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    if format == "jsonl":
        body = (json.dumps({c: e.get(c) for c in COLUMNS}) + "\n" for e in entries)
        media = "application/x-ndjson"
    else:
        body = _csv_rows(entries)
        media = "text/csv; charset=utf-8"
    return StreamingResponse(body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="audit-log-{ctx.tenant_id}-{stamp}.{format}"',
        "Cache-Control": "no-store",
    })
