"""Google Calendar — built-in tool `google_calendar` (Google Calendar REST API v3).

Actions: list upcoming events in a window, create an event, delete one by id. Auth is an OAuth
access token (+ refresh token / client id / secret when present) in the node config, resolved from
a ``secret://`` ref like any other credential.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from tools.base import ToolSpec, enum, params
from tools.productivity._google_auth import call as google_call
from tools.productivity._google_auth import http_error as http_error

LABEL = "[Google Calendar]"
GOOGLE_CAL_API = "https://www.googleapis.com/calendar/v3"
LIST_WINDOW_DAYS = 7


def _dt(raw: Any) -> Optional[datetime]:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


TOOL = ToolSpec(
    id="google_calendar",
    name="Google Calendar",
    icon="🗓️",
    category="Productivity",
    description="Reads, creates and deletes events on the user's Google Calendar via the Google Calendar API.",
    default_config={"calendar_id": "primary", "access_token": ""},
    order=10,
    required=("access_token",),
    parameters=params(
        {"action": enum(["list", "create", "delete"], "What to do")},
        {
            "calendar_id": {"type": "string", "description": "Calendar id or 'primary' (list / create / delete)"},
            "time_min": {"type": "string", "format": "date-time", "description": "Start of the event window, ISO 8601 (list)"},
            "time_max": {"type": "string", "format": "date-time", "description": "End of the event window, ISO 8601 (list)"},
            "summary": {"type": "string", "description": "Event title (create)"},
            "description": {"type": "string", "description": "Event description / notes (create)"},
            "start": {"type": "string", "format": "date-time", "description": "Start, ISO 8601, e.g. 2026-11-01T09:00:00Z (create)"},
            "end": {"type": "string", "format": "date-time", "description": "End, ISO 8601; defaults to start + 1 hour (create)"},
            "event_id": {"type": "string", "description": "Event id to delete"},
        },
    ),
    input_param="action",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return f"{LABEL} access_token is required in config — provide an OAuth access token (or a secret:// ref) for the Google Calendar API."
    calendar_id = str(cfg.get("calendar_id") or "primary").strip() or "primary"
    action = str(inp or "").strip().lower()
    if action not in ("list", "create", "delete"):
        return f'{LABEL} Action is "list", "create" or "delete" — got "{inp}".'

    if action == "delete":
        event_id = str(cfg.get("event_id") or "").strip()
        if not event_id:
            return f"{LABEL} delete needs an event_id — pass the id of the event to remove."
        resp = await google_call(cfg, "DELETE", f"{GOOGLE_CAL_API}/calendars/{calendar_id}/events/{event_id}")
        if resp.status_code == 204:
            return f"{LABEL} Deleted event {event_id}."
        return http_error(LABEL, resp)

    if action == "create":
        summary = str(cfg.get("summary") or "").strip()
        start = _dt(cfg.get("start"))
        if not summary or not start:
            return f"{LABEL} create needs a summary and a start time — pass both (start: 2026-11-01T09:00:00Z)."
        end = _dt(cfg.get("end")) or (start + timedelta(hours=1))
        body: Dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": _iso(start), "timeZone": "UTC"},
            "end": {"dateTime": _iso(end), "timeZone": "UTC"},
        }
        description = str(cfg.get("description") or "").strip()
        if description:
            body["description"] = description
        resp = await google_call(cfg, "POST", f"{GOOGLE_CAL_API}/calendars/{calendar_id}/events", json_body=body)
        if resp.status_code not in (200, 201):
            return http_error(LABEL, resp)
        event = resp.json() or {}
        return f"{LABEL} Created event {event.get('id')}: {summary}\n   {event.get('htmlLink') or ''}"

    # list
    now = datetime.now(timezone.utc)
    time_min = _dt(cfg.get("time_min")) or now
    time_max = _dt(cfg.get("time_max")) or (now + timedelta(days=LIST_WINDOW_DAYS))
    resp = await google_call(cfg, "GET", f"{GOOGLE_CAL_API}/calendars/{calendar_id}/events",
                       query={"timeMin": _iso(time_min), "timeMax": _iso(time_max), "maxResults": 50})
    if resp.status_code != 200:
        return http_error(LABEL, resp)
    events = resp.json().get("items") or []
    if not events:
        return f"{LABEL} No events found in the window."
    lines = [f"{LABEL} {len(events)} event(s) in calendar {calendar_id}", ""]
    for e in events:
        start = e.get("start") or {}
        end = e.get("end") or {}
        lines.append(f"  - {e.get('summary') or '(no title)'}  {start.get('dateTime') or start.get('date') or '?'} → "
                     f"{end.get('dateTime') or end.get('date') or '?'}  [{e.get('status') or 'confirmed'}]")
        if e.get("htmlLink"):
            lines.append(f"    {e['htmlLink']}")
        desc = str(e.get("description") or "").strip()
        if desc:
            lines.append(f"    {desc[:300]}")
    return "\n".join(lines)
