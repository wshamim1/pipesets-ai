"""Datadog — built-in tool `datadog` (Datadog API, read-only).

Actions: ``monitors`` (monitors in Alert / Warn / No Data, optionally filtered by tags or name),
``logs`` (search logs with Datadog query syntax over ``lookback``, newest first) and ``events``
(recent events such as deploys). Auth is an API key plus an application key; ``site`` picks the
region. A direct REST alternative to the MCP Datadog server.
"""

import time
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params
from tools.integrations._grafana_stack import lookback_seconds

LABEL = "[Datadog]"
ACTIONS = ("monitors", "logs", "events")
SITES = {"us1": "datadoghq.com", "us3": "us3.datadoghq.com", "us5": "us5.datadoghq.com", "eu1": "datadoghq.eu",
         "ap1": "ap1.datadoghq.com", "ap2": "ap2.datadoghq.com", "gov": "ddog-gov.com"}

TOOL = ToolSpec(
    id="datadog",
    name="Datadog",
    icon="🐶",
    category="APIs & Integrations",
    description="Reads Datadog (read-only): monitors in alert, log search with Datadog query syntax, and recent events such as deploys. Input: a log query, monitor tags / name, or event search text.",
    default_config={"site": "us1", "api_key": "", "application_key": "", "action": "monitors", "lookback": "1h",
                    "max_results": 25},
    order=109,
    required=("api_key", "application_key"),
    selects={"site": Select("Site", tuple((k, f"{k.upper()} ({v})") for k, v in SITES.items())),
             "action": Select("Action", (("monitors", "Monitors in alert"), ("logs", "Search logs"), ("events", "Recent events")))},
    parameters=params({}, {"query": {"type": "string", "description": "Log query (service:web status:error), monitor tags / name, or event text"},
                           "action": enum(list(ACTIONS), "What to read"),
                           "lookback": {"type": "string", "description": "Window for logs and events, e.g. 15m, 1h, 1d"}}),
    input_param="query",
    is_new=True,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    key, app = (cfg.get("api_key") or "").strip(), (cfg.get("application_key") or "").strip()
    if not key or not app:
        return f"{LABEL} api_key and application_key are required in config."
    action = cfg.get("action") or "monitors"
    if action not in ACTIONS:
        return f"{LABEL} Action is one of {', '.join(ACTIONS)} — got '{action}'."
    site = SITES.get(str(cfg.get("site") or "us1").lower(), SITES["us1"])
    api = f"https://api.{site}"
    query = inp.strip()
    limit = max(1, min(int(cfg.get("max_results") or 25), 100))
    window = lookback_seconds(cfg.get("lookback"), 3600)
    headers = {"DD-API-KEY": key, "DD-APPLICATION-KEY": app, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            if action == "monitors":
                q: Dict[str, Any] = {"group_states": "alert,warn,no data"}
                if ":" in query:
                    q["monitor_tags"] = query
                elif query:
                    q["name"] = query
                resp = await client.get(f"{api}/api/v1/monitor", params=q)
            elif action == "logs":
                resp = await client.post(f"{api}/api/v2/logs/events/search", json={
                    "filter": {"query": query or "*", "from": f"now-{window}s", "to": "now"},
                    "sort": "-timestamp", "page": {"limit": limit}})
            else:
                now = int(time.time())
                resp = await client.get(f"{api}/api/v1/events", params={"start": now - window, "end": now})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {api}: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check api_key / application_key (and its scopes) and the site ({site})."
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()

    if action == "monitors":
        bad = [m for m in data if m.get("overall_state") in ("Alert", "Warn", "No Data")]
        if not bad:
            return f"{LABEL} No monitors in Alert / Warn / No Data" + (f" for {query}." if query else ".")
        bad.sort(key=lambda m: {"Alert": 0, "Warn": 1, "No Data": 2}.get(m.get("overall_state"), 3))
        return f"{LABEL} {len(bad)} monitor(s) not OK\n" + "\n".join(
            f"- {m.get('overall_state')} · {m.get('name')} · id {m.get('id')} · {m.get('type')}"
            + (f" · tags: {', '.join(m['tags'][:5])}" if m.get("tags") else "") for m in bad[:limit])
    if action == "logs":
        logs = data.get("data") or []
        if not logs:
            return f"{LABEL} No logs in the last {cfg.get('lookback') or '1h'} for {query or '*'}."
        return f"{LABEL} {len(logs)} log(s), newest first\n" + "\n".join(
            f"{(a.get('timestamp') or '')[:19].replace('T', ' ')} {a.get('status', '')} {a.get('service', '')} {a.get('host', '')} | "
            f"{(a.get('message') or '')[:400]}" for a in ((l.get("attributes") or {}) for l in logs))
    events = [e for e in data.get("events") or [] if not query or query.lower() in f"{e.get('title')} {e.get('text')}".lower()]
    if not events:
        return f"{LABEL} No events in the last {cfg.get('lookback') or '1h'}" + (f" matching '{query}'." if query else ".")
    return f"{LABEL} {len(events)} event(s), newest first\n" + "\n".join(
        f"- {time.strftime('%Y-%m-%d %H:%M', time.gmtime(e.get('date_happened') or 0))} UTC · {e.get('alert_type', '')} · {e.get('title')}"
        for e in sorted(events, key=lambda e: -(e.get("date_happened") or 0))[:limit])
