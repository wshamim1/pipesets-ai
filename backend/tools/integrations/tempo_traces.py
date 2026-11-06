"""Tempo — built-in tool `tempo_traces` (Grafana Tempo HTTP API).

Input: a TraceQL query, e.g. ``{resource.service.name="checkout" && status=error}``, searches traces in
the ``lookback`` window (slowest first); a 16- or 32-character hex trace id reads that trace — its
services, the slowest spans and the spans with errors. Self-hosted Tempo (bearer token or none,
optional ``org_id``) or Grafana Cloud Traces (``username`` = user id, ``token`` = access-policy token).
"""

import re
import time
from typing import Any, Dict, List, Optional

from tools.base import ToolSpec, params
from tools.integrations._grafana_stack import base_url, client, failed, lookback_seconds

LABEL = "[Tempo]"
TRACE_ID = re.compile(r"^[0-9a-fA-F]{16}([0-9a-fA-F]{16})?$")

TOOL = ToolSpec(
    id="tempo_traces",
    name="Tempo",
    icon="🧵",
    category="APIs & Integrations",
    description="Searches traces in Grafana Tempo with TraceQL (slowest first), or reads one trace by id: services, slowest spans and spans with errors. Input: a TraceQL query or a trace id.",
    default_config={"base_url": "", "token": "", "username": "", "org_id": "", "lookback": "1h", "max_results": 20},
    order=107,
    required=("base_url",),
    parameters=params({"query": {"type": "string", "description": "TraceQL, e.g. {resource.service.name=\"api\" && status=error}, or a trace id"}},
                      {"lookback": {"type": "string", "description": "Search window, e.g. 15m, 1h"}}),
    input_param="query",
    is_new=True,
)


def _spans(trace: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten OTLP JSON (``resourceSpans`` / ``batches``, ``scopeSpans`` / ``instrumentationLibrarySpans``)."""
    out = []
    for rs in trace.get("resourceSpans") or trace.get("batches") or []:
        attrs = {a.get("key"): (a.get("value") or {}).get("stringValue") for a in (rs.get("resource") or {}).get("attributes") or []}
        for ss in rs.get("scopeSpans") or rs.get("instrumentationLibrarySpans") or []:
            for sp in ss.get("spans") or []:
                start, end = int(sp.get("startTimeUnixNano") or 0), int(sp.get("endTimeUnixNano") or 0)
                status = sp.get("status") or {}
                out.append({"service": attrs.get("service.name") or "?", "name": sp.get("name"),
                            "ms": (end - start) / 1e6, "error": status.get("code") in (2, "STATUS_CODE_ERROR"),
                            "message": status.get("message") or ""})
    return out


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = base_url(cfg)
    if not api:
        return f"{LABEL} base_url (e.g. http://tempo:3200 or https://tempo-prod-xx.grafana.net/tempo) is required in config."
    query = inp.strip()
    if not query:
        return f'{LABEL} Provide a TraceQL query, e.g. {{status=error}}, or a trace id.'
    is_id = bool(TRACE_ID.match(query))
    try:
        async with client(cfg) as c:
            if is_id:
                resp = await c.get(f"{api}/api/v2/traces/{query}")
                if resp.status_code == 404:
                    resp = await c.get(f"{api}/api/traces/{query}")
            else:
                now = int(time.time())
                resp = await c.get(f"{api}/api/search", params={
                    "q": query, "limit": max(1, min(int(cfg.get("max_results") or 20), 100)),
                    "start": now - lookback_seconds(cfg.get("lookback"), 3600), "end": now})
    except Exception as e:
        return f"{LABEL} Couldn't reach {api}: {e}"
    if resp.status_code == 400:
        return f"{LABEL} Tempo rejected the query: {resp.text[:300]}"
    if (err := failed(LABEL, resp, f"trace {query}" if is_id else "")):
        return err
    data = resp.json()

    if not is_id:
        traces = sorted(data.get("traces") or [], key=lambda t: t.get("durationMs") or 0, reverse=True)
        if not traces:
            return f"{LABEL} No traces in the last {cfg.get('lookback') or '1h'} for {query}"
        return f"{LABEL} {len(traces)} trace(s), slowest first\n" + "\n".join(
            f"- {t.get('traceID')} · {t.get('rootServiceName')} {t.get('rootTraceName') or ''} · {t.get('durationMs', 0)} ms · "
            f"{time.strftime('%H:%M:%S', time.gmtime(int(t.get('startTimeUnixNano') or 0) / 1e9))} UTC" for t in traces)
    spans = _spans(data.get("trace") or data)
    if not spans:
        return f"{LABEL} Trace {query} has no spans."
    errors = [s for s in spans if s["error"]]
    lines = [f"{LABEL} Trace {query}: {len(spans)} span(s) across {', '.join(sorted({s['service'] for s in spans}))}"
             + (f" · {len(errors)} with errors" if errors else "")]
    lines += ["  Slowest spans:"] + [f"    {s['ms']:.1f} ms · {s['service']} · {s['name']}" for s in sorted(spans, key=lambda s: -s["ms"])[:8]]
    if errors:
        lines += ["  Errors:"] + [f"    {s['service']} · {s['name']}" + (f" — {s['message']}" if s["message"] else "") for s in errors[:10]]
    return "\n".join(lines)
