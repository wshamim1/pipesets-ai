"""Salesforce — built-in tool `salesforce` (REST API v60.0, read-only).

Runs one SOQL query and returns the records as a markdown table. Auth is a Bearer access token
(connected app OAuth, or OAuth token from the password / client-credentials grant) for the domain
in the node config — ``instance_url`` (https://org.my.salesforce.com) and ``access_token``,
resolved from ``secret://`` refs.
"""

import json
from typing import Any, Dict, List, Optional

import httpx

from tools.base import ToolSpec, markdown_table, params

LABEL = "[Salesforce]"
API = "/services/data/v60.0"


def _cell(value: Any) -> Any:
    if isinstance(value, dict):
        name = value.get("Name") or value.get("name")
        return name or json.dumps(value, default=str)[:120]
    s = "" if value is None else str(value)
    return s[:120] + "…" if len(s) > 120 else s


def _error(resp: httpx.Response) -> str:
    try:
        err = resp.json()
        message = " ".join(e.get("message", "") for e in (err if isinstance(err, list) else [err]))[:300]
    except Exception:
        message = resp.text[:300]
    if resp.status_code == 401:
        return f"{LABEL} The session expired or the token is wrong ({message or 'unauthorized'}) — mint a new access_token."
    if resp.status_code == 403:
        return f"{LABEL} The user isn't allowed to query this: {message}"
    return f"{LABEL} HTTP {resp.status_code}: {message}"


def _records(records: List[Dict[str, Any]]) -> tuple:
    cols: List[str] = []
    for r in records:
        for k in r:
            if k != "attributes" and k not in cols:
                cols.append(k)
    rows = [[_cell(r.get(c)) for c in cols] for r in records]
    return cols, rows


TOOL = ToolSpec(
    id="salesforce",
    name="Salesforce",
    icon="☁️",
    category="Business Apps",
    description=("Runs one read SOQL query on the user's Salesforce org via the REST API, e.g. "
                 "SELECT Id, Name FROM Account LIMIT 20, and returns the records. Read-only; "
                 "Bearer access token + instance URL in the node config."),
    default_config={"instance_url": "", "access_token": "", "max_results": 25},
    order=80,
    required=("instance_url", "access_token"),
    parameters=params(
        {"query": {"type": "string", "description": "One SOQL SELECT statement"}},
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Most rows to return"}},
    ),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    base = (cfg.get("instance_url") or "").strip().rstrip("/")
    if not base:
        return f"{LABEL} instance_url is required in config (https://org.my.salesforce.com)."
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return f"{LABEL} access_token is required in config (a Bearer token from the connected app)."
    soql = str(inp or "").strip()
    if not soql:
        return f'{LABEL} Pass the SOQL query, e.g. SELECT Id, Name FROM Account LIMIT 20.'
    keyword = soql.split(None, 1)[0].lower()
    if keyword != "select" and cfg.get("allow_write") is not True:
        return f"{LABEL} Only SELECT is allowed (read-only) — got {keyword.upper()}."

    limit = min(max(int(cfg.get("max_results", 25) or 25), 1), 100)
    if "limit " not in soql.lower():
        soql = soql.rstrip(";") + f" LIMIT {limit}"
    try:
        async with httpx.AsyncClient(timeout=25.0, headers={"Authorization": f"Bearer {token}",
                                                            "Accept": "application/json"}) as client:
            resp = await client.get(f"{base}{API}/query", params={"q": soql})
    except Exception as e:
        return f"{LABEL} Error: {e}"
    if resp.status_code != 200:
        return _error(resp)
    result = resp.json()
    records: List[Dict[str, Any]] = result.get("records") or []
    total = int(result.get("totalSize") or len(records))
    if not records:
        return f"{LABEL} 0 rows — the query returned no records."
    cols, rows = _records(records)
    out = [f"{LABEL} {total} row(s)", "", markdown_table(cols, rows)]
    if result.get("done") is False:
        out.append(f"More records exist — narrow the WHERE clause; nextRecordsUrl is in the response body.")
    return "\n".join(out).rstrip()
