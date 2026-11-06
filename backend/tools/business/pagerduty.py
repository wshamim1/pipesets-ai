"""PagerDuty — built-in tool `pagerduty`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, params

TOOL = ToolSpec(
    id="pagerduty",
    name="PagerDuty",
    icon="📟",
    category="Business Apps",
    description="Triggers, acknowledges or resolves a PagerDuty incident (Events API v2), or lists open incidents (REST API). Input: the alert summary, or the dedup key to acknowledge / resolve.",
    default_config={"routing_key": "", "api_token": "", "action": "trigger", "severity": "error",
                    "source": "pipesets-ai", "max_results": 10},
    order=50,
    required=("routing_key",),
    selects={
        "action": Select("Action", (("trigger", "Trigger incident"), ("acknowledge", "Acknowledge"),
                                    ("resolve", "Resolve"), ("list", "List open incidents (needs api_token)"))),
        "severity": Select("Severity", (("critical", "Critical"), ("error", "Error"), ("warning", "Warning"), ("info", "Info"))),
    },
    parameters=params(
        {
            "request": {"type": "string", "description": "The alert summary to trigger, or the dedup key to acknowledge / resolve"},
        },
    ),
    input_param="request",
)

EVENTS = "https://events.pagerduty.com/v2/enqueue"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    action = cfg.get("action", "trigger")
    text = inp.strip()
    async with httpx.AsyncClient(timeout=15.0) as client:
        if action == "list":
            token = (cfg.get("api_token") or "").strip()
            if not token:
                return "[PagerDuty] Listing incidents needs a REST api_token in config."
            resp = await client.get("https://api.pagerduty.com/incidents", params={
                "statuses[]": ["triggered", "acknowledged"], "limit": int(cfg.get("max_results", 10)),
                "sort_by": "created_at:desc"},
                headers={"Authorization": f"Token token={token}", "Accept": "application/vnd.pagerduty+json;version=2"})
            if resp.status_code == 401:
                return "[PagerDuty] The api_token is invalid."
            if resp.status_code != 200:
                return f"[PagerDuty] HTTP {resp.status_code}: {resp.text[:300]}"
            incidents = resp.json().get("incidents", [])
            if not incidents:
                return "[PagerDuty] No open incidents. 🎉"
            lines = [f"[PagerDuty] {len(incidents)} open incident(s)\n"]
            for i in incidents:
                lines.append(f"#{i.get('incident_number')} [{i.get('status')}, {i.get('urgency')} urgency] {i.get('title', '')}\n"
                             f"   {(i.get('service') or {}).get('summary', '')} · since {(i.get('created_at') or '')[:16].replace('T', ' ')}"
                             f"\n   {i.get('html_url', '')}")
            return "\n".join(lines)

        routing_key = (cfg.get("routing_key") or "").strip()
        if not routing_key:
            return "[PagerDuty] routing_key (the service's Events API v2 integration key) is required in config."
        if action in ("acknowledge", "resolve"):
            dedup = text or (cfg.get("dedup_key") or "").strip()
            if not dedup:
                return f"[PagerDuty] Provide the dedup key of the incident to {action}."
            event = {"routing_key": routing_key, "event_action": action, "dedup_key": dedup}
        else:
            if not text:
                return "[PagerDuty] Provide a summary for the incident."
            event = {"routing_key": routing_key, "event_action": "trigger", "payload": {
                "summary": text[:1024], "source": cfg.get("source") or "pipesets-ai",
                "severity": cfg.get("severity") if cfg.get("severity") in ("critical", "error", "warning", "info") else "error"}}
            if cfg.get("dedup_key"):
                event["dedup_key"] = cfg["dedup_key"]
        resp = await client.post(EVENTS, json=event)
        if resp.status_code == 202:
            dedup_key = resp.json().get("dedup_key", "")
            done = {"trigger": "Incident triggered", "acknowledge": "Incident acknowledged", "resolve": "Incident resolved"}
            return f"[PagerDuty] {done.get(event['event_action'], 'Event sent')} (dedup key: {dedup_key})"
        try:
            detail = "; ".join(resp.json().get("errors", [])) or resp.json().get("message", "")
        except ValueError:
            detail = resp.text[:300]
        return f"[PagerDuty] HTTP {resp.status_code}: {detail}"
