"""Alertmanager — built-in tool `alertmanager` (Prometheus Alertmanager API v2, read-only).

Actions: ``alerts`` (active alerts, not silenced or inhibited unless ``include_silenced``; the input
is an optional matcher such as ``severity="critical"`` or an alert name) and ``silences`` (active and
pending silences: who, why, until when). Bearer token or none — Alertmanager itself has no auth, a
proxy in front usually does.
"""

from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params
from tools.integrations._grafana_stack import base_url, client, failed

LABEL = "[Alertmanager]"
ACTIONS = ("alerts", "silences")

TOOL = ToolSpec(
    id="alertmanager",
    name="Alertmanager",
    icon="🚨",
    category="APIs & Integrations",
    description="Reads Prometheus Alertmanager (read-only): active alerts grouped by severity, or current silences. Input: an optional matcher (severity=\"critical\") or alert name.",
    default_config={"base_url": "", "token": "", "action": "alerts", "include_silenced": False},
    order=108,
    required=("base_url",),
    selects={"action": Select("Action", (("alerts", "Active alerts"), ("silences", "Silences")))},
    parameters=params({}, {"filter": {"type": "string", "description": "A matcher like severity=\"critical\", or an alert name"},
                           "action": enum(list(ACTIONS), "What to read")}),
    input_param="filter",
    is_new=True,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = base_url(cfg)
    if not api:
        return f"{LABEL} base_url (e.g. http://alertmanager:9093) is required in config."
    action = cfg.get("action") or "alerts"
    if action not in ACTIONS:
        return f"{LABEL} Action is one of {', '.join(ACTIONS)} — got '{action}'."
    text = inp.strip()
    matcher = text if ("=" in text or "~" in text) else (f'alertname="{text}"' if text else "")
    try:
        async with client(cfg) as c:
            if action == "alerts":
                include = cfg.get("include_silenced") in (True, "true", "on", "yes", 1)
                q: Dict[str, Any] = {"active": "true", "silenced": str(include).lower(), "inhibited": str(include).lower()}
                if matcher:
                    q["filter"] = matcher
                resp = await c.get(f"{api}/api/v2/alerts", params=q)
            else:
                resp = await c.get(f"{api}/api/v2/silences", params={"filter": matcher} if matcher else {})
    except Exception as e:
        return f"{LABEL} Couldn't reach {api}: {e}"
    if resp.status_code == 400:
        return f"{LABEL} Bad matcher '{matcher}': {resp.text[:200]}"
    if (err := failed(LABEL, resp)):
        return err
    data = resp.json()

    if action == "silences":
        live = [s for s in data if (s.get("status") or {}).get("state") in ("active", "pending")]
        if not live:
            return f"{LABEL} No active silences."
        return f"{LABEL} {len(live)} silence(s)\n" + "\n".join(
            f"- {(s.get('status') or {}).get('state')} · until {(s.get('endsAt') or '')[:16].replace('T', ' ')} · by {s.get('createdBy')} · "
            + ", ".join(f"{m.get('name')}{'=~' if m.get('isRegex') else ('=' if m.get('isEqual', True) else '!=')}{m.get('value')}"
                        for m in s.get("matchers") or []) + (f" — {s['comment']}" if s.get("comment") else "") for s in live)
    if not data:
        return f"{LABEL} No active alerts" + (f" matching {matcher}." if matcher else ".")
    rank = {"critical": 0, "page": 0, "error": 1, "warning": 2, "info": 3}
    data.sort(key=lambda a: (rank.get(((a.get("labels") or {}).get("severity") or "").lower(), 4), a.get("startsAt") or ""))
    lines = [f"{LABEL} {len(data)} active alert(s), most severe first"]
    for a in data[:50]:
        labels = a.get("labels") or {}
        ann = a.get("annotations") or {}
        extra = ", ".join(f"{k}={v}" for k, v in labels.items() if k not in ("alertname", "severity"))
        lines.append(f"- {labels.get('severity', 'none')} · {labels.get('alertname')} · {extra} · since "
                     f"{(a.get('startsAt') or '')[:16].replace('T', ' ')}"
                     + (f" — {ann.get('summary') or ann.get('description')}" if ann.get("summary") or ann.get("description") else "")
                     + (" (silenced)" if (a.get("status") or {}).get("state") == "suppressed" else ""))
    return "\n".join(lines)
