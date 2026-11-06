"""Grafana — built-in tool `grafana` (Grafana HTTP API, read-only).

Actions: ``alerts`` (Grafana-managed alert rules that are firing or pending, with their labels and the
last error), ``dashboards`` (search dashboards by name or tag; the input is the search text),
``annotations`` (recent annotations such as deploys, over ``lookback``) and ``datasources``. Auth is a
service-account token (Viewer is enough). Unlike the MCP Grafana server it needs nothing installed.
"""

import time
from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params
from tools.integrations._grafana_stack import base_url, client, failed, lookback_seconds

LABEL = "[Grafana]"
ACTIONS = ("alerts", "dashboards", "annotations", "datasources")

TOOL = ToolSpec(
    id="grafana",
    name="Grafana",
    icon="📈",
    category="APIs & Integrations",
    description="Reads Grafana (read-only): firing and pending alert rules, dashboard search, recent annotations such as deploys, and data sources. Input: search text (dashboards) or a filter on alert / annotation text.",
    default_config={"base_url": "", "token": "", "action": "alerts", "lookback": "6h", "max_results": 20},
    order=105,
    required=("base_url",),
    selects={"action": Select("Action", (("alerts", "Firing alerts"), ("dashboards", "Search dashboards"),
                                         ("annotations", "Recent annotations"), ("datasources", "Data sources")))},
    parameters=params({}, {"search": {"type": "string", "description": "Dashboard search text, or text to filter alerts / annotations by"},
                           "action": enum(list(ACTIONS), "What to read"),
                           "lookback": {"type": "string", "description": "How far back for annotations, e.g. 30m, 6h, 2d"}}),
    input_param="search",
    is_new=True,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = base_url(cfg)
    if not api:
        return f"{LABEL} base_url (e.g. https://grafana.example.com or https://<stack>.grafana.net) is required in config."
    action = cfg.get("action") or "alerts"
    if action not in ACTIONS:
        return f"{LABEL} Action is one of {', '.join(ACTIONS)} — got '{action}'."
    text = inp.strip().strip("'\"")
    limit = max(1, min(int(cfg.get("max_results") or 20), 100))
    try:
        async with client(cfg) as c:
            if action == "alerts":
                resp = await c.get(f"{api}/api/prometheus/grafana/api/v1/rules")
            elif action == "dashboards":
                resp = await c.get(f"{api}/api/search", params={"query": text, "type": "dash-db", "limit": limit})
            elif action == "annotations":
                now_ms = int(time.time() * 1000)
                resp = await c.get(f"{api}/api/annotations", params={
                    "from": now_ms - lookback_seconds(cfg.get("lookback"), 6 * 3600) * 1000, "to": now_ms, "limit": limit})
            else:
                resp = await c.get(f"{api}/api/datasources")
    except Exception as e:  # httpx errors, bad TLS
        return f"{LABEL} Couldn't reach {api}: {e}"
    if (err := failed(LABEL, resp)):
        return err
    data = resp.json()

    if action == "alerts":
        rules = [r | {"_group": g.get("name"), "_folder": g.get("file")}
                 for g in (data.get("data") or {}).get("groups") or [] for r in g.get("rules") or []]
        active = [r for r in rules if r.get("state") in ("firing", "pending") or r.get("health") == "error"]
        if text:
            active = [r for r in active if text.lower() in (r.get("name") or "").lower()]
        if not active:
            return f"{LABEL} No firing or pending alerts ({len(rules)} rule(s) checked)."
        active.sort(key=lambda r: {"firing": 0, "pending": 1}.get(r.get("state"), 2))
        lines = [f"{LABEL} {len(active)} active alert rule(s) of {len(rules)}"]
        for r in active[:limit]:
            lines.append(f"- {r.get('state', '').upper()} · {r.get('name')} · {r.get('_folder')}/{r.get('_group')}"
                         + (f" · error: {r['lastError']}" if r.get("lastError") else ""))
            for a in (r.get("alerts") or [])[:3]:
                labels = ", ".join(f"{k}={v}" for k, v in (a.get("labels") or {}).items() if k not in ("alertname", "grafana_folder"))
                summary = (a.get("annotations") or {}).get("summary") or (a.get("annotations") or {}).get("description") or ""
                lines.append(f"    {labels}" + (f" — {summary}" if summary else "") + (f" (since {a['activeAt'][:16]})" if a.get("activeAt") else ""))
        return "\n".join(lines)
    if action == "dashboards":
        if not data:
            return f"{LABEL} No dashboards match '{text}'."
        return f"{LABEL} {len(data)} dashboard(s)\n" + "\n".join(
            f"- {d.get('title')} · {d.get('folderTitle') or 'General'} · {api}{d.get('url')}"
            + (f" · tags: {', '.join(d['tags'])}" if d.get("tags") else "") for d in data)
    if action == "annotations":
        items = [a for a in data if not text or text.lower() in (a.get("text") or "").lower()
                 or any(text.lower() in t.lower() for t in a.get("tags") or [])]
        if not items:
            return f"{LABEL} No annotations in the last {cfg.get('lookback') or '6h'}" + (f" matching '{text}'." if text else ".")
        return f"{LABEL} {len(items)} annotation(s), newest first\n" + "\n".join(
            f"- {time.strftime('%Y-%m-%d %H:%M', time.gmtime((a.get('time') or 0) / 1000))} UTC · {a.get('text')}"
            + (f" · tags: {', '.join(a['tags'])}" if a.get("tags") else "") for a in items)
    return f"{LABEL} {len(data)} data source(s)\n" + "\n".join(
        f"- {d.get('name')} · {d.get('type')}{' · default' if d.get('isDefault') else ''}" for d in data)
