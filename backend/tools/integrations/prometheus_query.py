"""Prometheus — built-in tool `prometheus_query` (HTTP API v1; Prometheus, Thanos, Mimir, VictoriaMetrics).

Input is a PromQL expression. With ``lookback`` (e.g. 1h) it runs a range query over that window
and summarizes each series (min / max / last); otherwise an instant query returns current values.
"""

import re
import time
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Prometheus]"
_DURATION = re.compile(r"^(\d+)([smhdw])$")
_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
MAX_SERIES = 30

TOOL = ToolSpec(
    id="prometheus_query",
    name="Prometheus Query",
    icon="🔥",
    category="APIs & Integrations",
    description="Runs a PromQL query against Prometheus (or a compatible API) and returns current values, or min / max / last over a lookback window.",
    default_config={"base_url": "", "bearer_token": "", "username": "", "password": "", "lookback": ""},
    order=96,
    required=("base_url",),
    parameters=params(
        {"query": {"type": "string", "description": "PromQL expression, e.g. sum by (job) (rate(http_requests_total[5m]))"}},
        {"lookback": {"type": "string", "description": "Range query window like 30m, 6h or 7d; leave out for current values"}},
    ),
    input_param="query",
)


def _labels(metric: Dict[str, str]) -> str:
    name = metric.get("__name__", "")
    rest = ", ".join(f'{k}="{v}"' for k, v in sorted(metric.items()) if k != "__name__")
    return f"{name}{{{rest}}}" if rest or not name else name


def _num(v: str) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:.6g}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    if not base:
        return f"{LABEL} base_url (e.g. http://prometheus:9090) is required in config."
    if not inp:
        return f"{LABEL} Provide a PromQL query."
    lookback = str(cfg.get("lookback") or "").strip().lower()
    if lookback and not _DURATION.match(lookback):
        return f"{LABEL} lookback is a duration like 30m, 6h or 7d — got '{lookback}'."
    headers = {"Authorization": f"Bearer {cfg['bearer_token'].strip()}"} if (cfg.get("bearer_token") or "").strip() else {}
    auth = (cfg["username"], cfg.get("password") or "") if (cfg.get("username") or "").strip() else None
    if lookback:
        m = _DURATION.match(lookback)
        window = int(m.group(1)) * _SECONDS[m.group(2)]
        end = time.time()
        url, q = f"{base}/api/v1/query_range", {"query": inp, "start": end - window, "end": end,
                                                "step": max(15, window // 120)}
    else:
        url, q = f"{base}/api/v1/query", {"query": inp}
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=headers, auth=auth) as client:
            resp = await client.get(url, params=q)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {base}: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check bearer_token or username / password."
    try:
        body = resp.json()
    except ValueError:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    if body.get("status") != "success":
        return f"{LABEL} {body.get('errorType', 'error')}: {body.get('error', resp.text[:200])}"

    data = body.get("data") or {}
    kind, result = data.get("resultType"), data.get("result")
    if kind in ("scalar", "string"):
        return f"{LABEL} {inp}\n= {_num(result[1])}"
    if not result:
        return f"{LABEL} No data for {inp}" + (f" in the last {lookback}." if lookback else ".")
    lines = [f"{LABEL} {inp}" + (f" — last {lookback}" if lookback else ""),
             f"{len(result)} series" + (f" (showing {MAX_SERIES})" if len(result) > MAX_SERIES else "")]
    for s in result[:MAX_SERIES]:
        if kind == "matrix":
            vals = [float(v) for _, v in s.get("values", []) if v not in ("NaN", "+Inf", "-Inf")]
            summary = (f"min {_num(min(vals))} · max {_num(max(vals))} · last {_num(vals[-1])}" if vals else "no numeric samples")
            lines.append(f"- {_labels(s.get('metric', {}))}: {summary}")
        else:
            lines.append(f"- {_labels(s.get('metric', {}))}: {_num((s.get('value') or [None, ''])[1])}")
    return "\n".join(lines)
