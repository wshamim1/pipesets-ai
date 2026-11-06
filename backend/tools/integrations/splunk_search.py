"""Splunk — built-in tool `splunk_search` (Splunk REST API, management port 8089).

Input: an SPL search, e.g. ``index=web status>=500 | stats count by host``; a query without a leading
``search`` / ``|`` gets ``search`` prepended. Runs as a one-shot export over ``earliest`` (default the
last hour) and returns the results as rows. Auth is an authentication token (Bearer) or username and
password. Read-only as far as this tool goes — the token's role decides what it can search.
"""

import json
from typing import Any, Dict, List, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Splunk]"

TOOL = ToolSpec(
    id="splunk_search",
    name="Splunk",
    icon="🟩",
    category="APIs & Integrations",
    description="Runs an SPL search on Splunk (Enterprise or Cloud, REST on port 8089) over a time window and returns the results as rows. Input: the SPL query.",
    default_config={"base_url": "", "token": "", "username": "", "password": "", "earliest": "-1h", "max_results": 50,
                    "verify_tls": True},
    order=110,
    required=("base_url",),
    parameters=params({"query": {"type": "string", "description": "SPL, e.g. index=web status>=500 | stats count by host"}},
                      {"earliest": {"type": "string", "description": "Start of the window, e.g. -15m, -1h, -1d@d"},
                       "max_results": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Max rows"}}),
    input_param="query",
    is_new=True,
)


def _rows(text: str) -> List[Dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("result"), dict) and not obj.get("preview"):
            rows.append(obj["result"])
        elif isinstance(obj, dict) and obj.get("messages"):
            rows.append({"_message": "; ".join(m.get("text", "") for m in obj["messages"])})
    return rows


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = (cfg.get("base_url") or "").strip().rstrip("/")
    if not api:
        return f"{LABEL} base_url (the management port, e.g. https://splunk.example.com:8089) is required in config."
    query = inp.strip()
    if not query:
        return f"{LABEL} Provide an SPL search, e.g. index=web status>=500 | stats count by host."
    if not query.startswith(("search ", "|")):
        query = f"search {query}"
    token = (cfg.get("token") or "").strip()
    user = (cfg.get("username") or "").strip()
    if not token and not user:
        return f"{LABEL} Set token (an authentication token) or username and password in config."
    limit = max(1, min(int(cfg.get("max_results") or 50), 500))
    form = {"search": query, "earliest_time": cfg.get("earliest") or "-1h", "latest_time": "now",
            "output_mode": "json", "count": limit}
    verify = cfg.get("verify_tls") not in (False, "false", "off", "no", 0)
    try:
        async with httpx.AsyncClient(timeout=60.0, verify=verify,
                                     headers={"Authorization": f"Bearer {token}"} if token else {},
                                     auth=(user, cfg.get("password") or "") if user and not token else None) as client:
            resp = await client.post(f"{api}/services/search/v2/jobs/export", data=form)
            if resp.status_code == 404:   # Splunk before 9.0.1 has only the v1 endpoint
                resp = await client.post(f"{api}/services/search/jobs/export", data=form)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {api}: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check the token (or username / password) and its role's search permissions."
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:300]}"
    rows = _rows(resp.text)[:limit]
    errors = [r["_message"] for r in rows if "_message" in r]
    rows = [r for r in rows if "_message" not in r]
    if not rows:
        return f"{LABEL} No results for: {query} (since {form['earliest_time']})" + (f"\nSplunk says: {errors[0]}" if errors else "")
    fields = [f for f in rows[0] if not f.startswith("_") or f in ("_time", "_raw")][:8]
    lines = [f"{LABEL} {len(rows)} result(s) for: {query}", " | ".join(fields)]
    lines += [" | ".join(str(r.get(f, ""))[:200].replace("\n", " ") for f in fields) for r in rows]
    return "\n".join(lines)
