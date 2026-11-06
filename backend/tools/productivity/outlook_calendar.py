"""Outlook Calendar — built-in tool `outlook_calendar` (Microsoft Graph events).

Actions: ``list`` (events in a window), ``create`` and ``delete`` (by Graph event id). All times
are written in UTC (``timeZone: UTC``); a passed ISO 8601 start / end with an offset is converted.
Auth is a delegated Microsoft OAuth access token (+ refresh token / client id / secret when
present) in the node config, resolved from a ``secret://`` ref. Delegate scopes:
``offline_access Calendars.ReadWrite``.
"""

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Optional

from tools.base import ToolSpec, enum, params
from tools.productivity._ms_auth import GRAPH, call as ms_call
from tools.productivity._ms_auth import ms_error

LABEL = "[Outlook Calendar]"
LIST_WINDOW_DAYS = 7
_EV_FIELDS = "id,subject,start,end,location,webLink,organizer,bodyPreview"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def _dt(raw: Any) -> Optional[datetime]:
    s = str(raw or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _graph_time(d: datetime) -> Dict[str, str]:
    """The Graph start / end body: naive UTC string + timeZone UTC."""
    return {"dateTime": d.strftime("%Y-%m-%dT%H:%M:%S.0000000"), "timeZone": "UTC"}


def _when(e: Dict[str, Any]) -> str:
    s, en = e.get("start") or {}, e.get("end") or {}
    return f"{(s.get('dateTime') or '?')[:16]} → {(en.get('dateTime') or '?')[:16]} UTC"


def _attendees(raw: Any) -> list:
    """The typed ``attendees`` argument (comma / semicolon separated) as Graph entries."""
    entries = []
    for p in str(raw or "").replace(";", ",").split(","):
        m = _EMAIL_RE.search(p)
        if m:
            entries.append({"emailAddress": {"address": m.group(0)}, "type": "required"})
    return entries


TOOL = ToolSpec(
    id="outlook_calendar",
    name="Outlook Calendar",
    icon="📅",
    category="Productivity",
    description=("Reads, creates and deletes events on the signed-in user's Outlook Calendar via "
                 "Microsoft Graph (UTC; an offset start / end is converted). Delegated Graph "
                 "scopes: Calendars.ReadWrite."),
    default_config={"access_token": "", "action": "list"},
    order=110,
    required=("access_token",),
    parameters=params(
        {"action": enum(["list", "create", "delete"], "What to do")},
        {
            "time_min": {"type": "string", "format": "date-time", "description": "Start of the event window, ISO 8601; default now (list)"},
            "time_max": {"type": "string", "format": "date-time", "description": "End of the event window, ISO 8601; default start + 7 days (list)"},
            "subject": {"type": "string", "description": "Event title (create)"},
            "start": {"type": "string", "format": "date-time", "description": "Start, ISO 8601, e.g. 2026-11-01T09:00:00Z (create)"},
            "end": {"type": "string", "format": "date-time", "description": "End, ISO 8601; defaults to start + 1 hour (create)"},
            "event_body": {"type": "string", "description": "Event description / notes (create)"},
            "location": {"type": "string", "description": "Location text (create)"},
            "attendees": {"type": "string", "description": "Attendee addresses, comma separated (create)"},
            "event_id": {"type": "string", "description": "Event id to delete"},
        },
    ),
    input_param="action",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide a Microsoft OAuth access token "
                "(or a secret:// ref) with the Calendars.ReadWrite delegated scope.")
    action = str(inp or cfg.get("action") or "").strip().lower()
    if action not in ("list", "create", "delete"):
        return f'{LABEL} Action is "list", "create" or "delete" — got "{inp}".'

    if action == "delete":
        event_id = str(cfg.get("event_id") or "").strip()
        if not event_id:
            return f"{LABEL} delete needs an event_id — pass the id of the event to remove."
        resp = await ms_call(cfg, "DELETE", f"{GRAPH}/me/events/{event_id}")
        if resp.status_code == 204:
            return f"{LABEL} Deleted event {event_id}."
        return ms_error(LABEL, resp)

    if action == "create":
        subject = str(cfg.get("subject") or "").strip()
        start = _dt(cfg.get("start"))
        if not subject or not start:
            return (f"{LABEL} create needs a subject and a start time — pass both "
                    "(start: 2026-11-01T09:00:00Z).")
        end = _dt(cfg.get("end")) or (start + timedelta(hours=1))
        body: Dict[str, Any] = {"subject": subject, "start": _graph_time(start), "end": _graph_time(end)}
        text = str(cfg.get("event_body") or "").strip()
        if text:
            body["body"] = {"contentType": "Text", "content": text}
        location = str(cfg.get("location") or "").strip()
        if location:
            body["location"] = {"displayName": location}
        attendees = _attendees(cfg.get("attendees"))
        if attendees:
            body["attendees"] = attendees
        resp = await ms_call(cfg, "POST", f"{GRAPH}/me/events", json_body=body)
        if resp.status_code not in (200, 201):
            return ms_error(LABEL, resp)
        event = resp.json() or {}
        link = event.get("webLink") or ""
        return (f"{LABEL} Created event {event.get('id')}: {subject}\n    {_when(event)}\n{link}").rstrip()

    # list — /me/calendarview is the documented way to read a window
    now = datetime.now(timezone.utc)
    time_min = _dt(cfg.get("time_min")) or now
    time_max = _dt(cfg.get("time_max")) or (now + timedelta(days=LIST_WINDOW_DAYS))
    resp = await ms_call(cfg, "GET", f"{GRAPH}/me/calendarview",
                         query={"startDateTime": _graph_time(time_min)["dateTime"],
                                "endDateTime": _graph_time(time_max)["dateTime"],
                                "$select": _EV_FIELDS, "$top": 25},
                         headers={"Prefer": 'outlook.timezone="UTC"'})
    if resp.status_code != 200:
        return ms_error(LABEL, resp)
    events = resp.json().get("value") or []
    if not events:
        return f"{LABEL} No events found in the window."
    lines = [f"{LABEL} {len(events)} event(s) in the window (UTC)", ""]
    for e in events:
        lines.append(f"  - {e.get('subject') or '(no title)'}  {_when(e)}")
        if e.get("webLink"):
            lines.append(f"    {e['webLink']}")
        organizer = (e.get("organizer") or {})
        who = str(((organizer.get("emailAddress") or {}).get("address")) or "").strip()
        if who:
            lines.append(f"    Organizer: {who}")
        preview = str(e.get("bodyPreview") or "").strip()
        if preview:
            lines.append(f"    {preview[:300]}")
    return "\n".join(lines)
