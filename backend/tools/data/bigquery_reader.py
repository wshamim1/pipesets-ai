"""Google BigQuery — built-in tool `bigquery_reader` (BigQuery REST API v2, read queries).

Runs one SQL statement with Standard SQL by name. Auth is a Google OAuth access token (+ refresh
token / client id / secret when present) in the node config, resolved from a ``secret://`` ref like
the other Google tools — an authorized user or service account JWT with the
``https://www.googleapis.com/auth/bigquery.readonly`` scope (env GOOGLE_OAUTH_CLIENT_ID / SECRET).
"""

import asyncio
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, markdown_table, params
from tools.productivity._google_auth import call as google_call
from tools.productivity._google_auth import http_error

LABEL = "[BigQuery]"
API = "https://bigquery.googleapis.com/bigquery/v2"
READONLY_SCOPES = ("select", "explain", "show")
MAX_WAIT_POLLS = 10


def _cell(value: Any) -> str:
    """A cell value as text (bytes / records come back as base64-encoded strings)."""
    if isinstance(value, list):
        return ", ".join(_cell(v) for v in value)
    return _str(value)


def _str(value: Optional[str]) -> str:
    s = "" if value is None else str(value)
    return s[:120] + "…" if len(s) > 120 else s


def _table(schema: Dict[str, Any], rows: list) -> str:
    header = [str(f.get("name") or "?") for f in (schema.get("fields") or [])]
    body = [[_cell(c.get("v")) for c in (r.get("f") or [])] for r in rows]
    return markdown_table(header, body)


TOOL = ToolSpec(
    id="bigquery_reader",
    name="Google BigQuery",
    icon="⚡",
    category="Data & Files",
    description="Runs one read SQL statement on the user's Google BigQuery project via the BigQuery REST API (Standard SQL) and returns a markdown table. OAuth access token with the bigquery.readonly scope.",
    default_config={"project_id": "", "access_token": "", "max_results": 50},
    order=190,
    required=("access_token",),
    parameters=params(
        {"sql": {"type": "string", "description": "One BigQuery SQL statement — SELECT, EXPLAIN, SHOW, or WITH"}},
        {
            "project_id": {"type": "string", "description": "The BigQuery project id"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Most rows per page"},
        },
    ),
    input_param="sql",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide a Google OAuth access token (or a "
                "secret:// ref) with the bigquery.readonly scope.")
    sql = str(inp or "").strip()
    if not sql:
        return f"{LABEL} Pass the SQL statement to run."
    keyword = sql.split(None, 1)[0].lower().rstrip("(")
    if keyword not in READONLY_SCOPES and cfg.get("allow_write") is not True:
        return f"{LABEL} Only {', '.join(READONLY_SCOPES)} statements are allowed (read-only) — got {keyword.upper()}."

    project = str(cfg.get("project_id") or "").strip()
    if not project:
        return f"{LABEL} project_id is required in config (the BigQuery project id)."
    max_rows = min(max(int(cfg.get("max_results", 50) or 50), 1), 100)
    body = {"query": sql, "useLegacySql": False, "maxResults": max_rows, "timeoutMs": 10000}
    resp = await google_call(cfg, "POST", f"{API}/projects/{project}/queries", json_body=body)
    if resp.status_code not in (200, 404):
        return http_error(LABEL, resp)
    result = resp.json()
    if resp.status_code == 404:
        return f"{LABEL} Project {project} not found (check project_id)."

    attempt = 0
    while not result.get("jobComplete") and attempt < MAX_WAIT_POLLS:
        attempt += 1
        await asyncio.sleep(1.5)
        poll = await google_call(
            cfg, "GET", f"{API}/projects/{project}/queries/{result.get('jobReference', {}).get('jobId')}",
            query={"location": result.get("jobReference", {}).get("location", "US"),
                   "timeoutMs": 6000, "maxResults": max_rows})
        if poll.status_code != 200:
            return http_error(LABEL, poll)
        result = poll.json()
    if not result.get("jobComplete"):
        return f"{LABEL} The query job is still running — try again shortly."

    return _present(result, sql, max_rows)


def _present(result: Dict[str, Any], sql: str, max_rows: int) -> str:
    rows = result.get("rows") or []
    total = int(result.get("totalRows") or len(rows) or 0)
    out = [f"{LABEL} {total} row(s)", ""]
    if rows:
        out.append(_table(result.get("schema") or {}, rows))
    else:
        out.append("(the query returned no rows)")
    if total > len(rows):
        out.append(f"Showing {len(rows)} of {total} rows — narrow the query or raise max_results for more.")
    errors = result.get("errors") or []
    if errors:
        out.insert(1, f"Job errors: {errors[0].get('message', '')[:200]}")
    return "\n".join(out).rstrip()
