"""Loki — built-in tool `loki_query` (Loki HTTP API: /loki/api/v1/query_range).

Input: a LogQL query, e.g. ``{app="checkout"} |= "error"`` (log lines, newest first) or
``sum by (level) (count_over_time({app="checkout"}[5m]))`` (a metric query: the latest value per
series). ``lookback`` sets the window. Works with self-hosted Loki (bearer token or none, optional
tenant ``org_id``) and Grafana Cloud Logs (``username`` = the stack's user id, ``token`` = an
access-policy token).
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.integrations._grafana_stack import base_url, client, failed, lookback_seconds

LABEL = "[Loki]"

TOOL = ToolSpec(
    id="loki_query",
    name="Loki",
    icon="🪵",
    category="APIs & Integrations",
    description="Runs a LogQL query against Loki or Grafana Cloud Logs: matching log lines (newest first) or a metric query's latest values. Input: the LogQL query.",
    default_config={"base_url": "", "token": "", "username": "", "org_id": "", "lookback": "1h", "max_results": 50},
    order=106,
    required=("base_url",),
    parameters=params({"query": {"type": "string", "description": "LogQL, e.g. {app=\"checkout\"} |= \"error\""}},
                      {"lookback": {"type": "string", "description": "Time window, e.g. 15m, 1h, 1d"},
                       "max_results": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Max log lines"}}),
    input_param="query",
    is_new=True,
)


def _ts(ns: str) -> str:
    return datetime.fromtimestamp(int(ns) / 1e9, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = base_url(cfg)
    if not api:
        return f"{LABEL} base_url (e.g. http://loki:3100 or https://logs-prod-xx.grafana.net) is required in config."
    query = inp.strip()
    if not query:
        return f'{LABEL} Provide a LogQL query, e.g. {{app="checkout"}} |= "error".'
    window = lookback_seconds(cfg.get("lookback"), 3600)
    limit = max(1, min(int(cfg.get("max_results") or 50), 500))
    end = time.time_ns()
    try:
        async with client(cfg) as c:
            resp = await c.get(f"{api}/loki/api/v1/query_range", params={
                "query": query, "start": end - window * 10**9, "end": end, "limit": limit, "direction": "backward"})
    except Exception as e:
        return f"{LABEL} Couldn't reach {api}: {e}"
    if resp.status_code == 400:
        return f"{LABEL} Loki rejected the query: {resp.text[:300]}"
    if (err := failed(LABEL, resp)):
        return err
    data = resp.json().get("data") or {}
    result = data.get("result") or []
    if not result:
        return f"{LABEL} No results in the last {cfg.get('lookback') or '1h'} for {query}"
    if data.get("resultType") == "streams":
        lines = sorted(((ts, line, s.get("stream") or {}) for s in result for ts, line in s.get("values") or []),
                       key=lambda x: x[0], reverse=True)[:limit]
        return f"{LABEL} {len(lines)} line(s), newest first, from {len(result)} stream(s)\n" + "\n".join(
            f"{_ts(ts)} {', '.join(f'{k}={v}' for k, v in list(labels.items())[:3])} | {line[:500]}" for ts, line, labels in lines)
    return f"{LABEL} {len(result)} series (latest value over the last {cfg.get('lookback') or '1h'})\n" + "\n".join(
        f"- {', '.join(f'{k}={v}' for k, v in (r.get('metric') or {}).items()) or '{}'}: "
        f"{(r.get('values') or [[0, r.get('value', [0, '?'])[1]]])[-1][1]}" for r in result[:50])
