"""Time zone converter — built-in tool `timezone_converter`."""

from datetime import datetime
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="timezone_converter",
    name="Time Zone Converter",
    icon="🕰️",
    category="Everyday Utilities",
    description="Converts a time between zones, e.g. '3pm PST to IST' or 'now in Asia/Tokyo'.",
    default_config={"default_timezone": "UTC"},
    order=60,
    parameters=params({"request": {"type": "string", "description": "e.g. '3pm PST to IST' or 'now in Asia/Tokyo'"}}),
    input_param="request",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import re
    import zoneinfo
    aliases = {"pst": "America/Los_Angeles", "pdt": "America/Los_Angeles", "pt": "America/Los_Angeles",
               "mst": "America/Denver", "cst": "America/Chicago", "ct": "America/Chicago",
               "est": "America/New_York", "edt": "America/New_York", "et": "America/New_York",
               "gmt": "Europe/London", "bst": "Europe/London", "utc": "UTC", "cet": "Europe/Paris",
               "cest": "Europe/Paris", "ist": "Asia/Kolkata", "jst": "Asia/Tokyo", "aest": "Australia/Sydney",
               "sgt": "Asia/Singapore", "hkt": "Asia/Hong_Kong", "kst": "Asia/Seoul", "gst": "Asia/Dubai"}

    def zone(name: str):
        name = name.strip()
        try:
            return zoneinfo.ZoneInfo(aliases.get(name.lower(), name))
        except Exception:
            return None

    # "3pm PST to IST", "14:30 Europe/Paris in Asia/Tokyo", "now in Asia/Tokyo"
    m = re.match(r"\s*(now|\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*([A-Za-z_/+-]+)?\s+(?:to|in|->)\s+([A-Za-z_/+-]+)\s*$", inp, re.I)
    if not m:
        return "[Time zones] Input like '3pm PST to IST', '14:30 Europe/Paris to Asia/Tokyo' or 'now in Asia/Tokyo'."
    src = zone(m.group(2) or cfg.get("default_timezone", "UTC"))
    dst = zone(m.group(3))
    if not src or not dst:
        return f"[Time zones] Unknown time zone '{m.group(2) if not src else m.group(3)}'. Use IANA names like America/New_York."
    now = datetime.now(src)
    if m.group(1).lower() == "now":
        t = now
    else:
        tm = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", m.group(1), re.I)
        hour, minute, ampm = int(tm.group(1)), int(tm.group(2) or 0), (tm.group(3) or "").lower()
        hour = hour % 12 + (12 if ampm == "pm" else 0) if ampm else hour
        t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    out = t.astimezone(dst)
    day = "" if out.date() == t.date() else (" (next day)" if out.date() > t.date() else " (previous day)")
    return (f"[Time zones] {t.strftime('%a %H:%M')} {t.tzname()} ({src.key}) = "
            f"{out.strftime('%a %H:%M')} {out.tzname()} ({dst.key}){day}")
