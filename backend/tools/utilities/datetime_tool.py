"""Date / time — built-in tool `datetime_tool`."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="datetime_tool",
    name="Date & Time",
    icon="🕐",
    category="Everyday Utilities",
    description="Returns current date/time or applies offsets like '+7d', '-2h'.",
    default_config={"timezone": "UTC", "format": "%Y-%m-%d %H:%M:%S %Z"},
    order=10,
    parameters=params({}, {"offset": {"type": "string", "description": "Offset from now, e.g. +7d or -2h; leave out for now"}}),
    input_param="offset",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    tz_name = cfg.get("timezone", "UTC")
    fmt = cfg.get("format", "%Y-%m-%d %H:%M:%S %Z")
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    if inp.strip().lower() in ("", "now", "current", "time", "date"):
        return now.strftime(fmt)
    # Try to parse a date math expression like "+7d", "-2h"
    import re
    m = re.match(r"([+-]\d+)([smhdwM])", inp.strip())
    if m:
        from datetime import timedelta
        amount, unit = int(m.group(1)), m.group(2)
        deltas = {"s": timedelta(seconds=amount), "m": timedelta(minutes=amount),
                  "h": timedelta(hours=amount), "d": timedelta(days=amount),
                  "w": timedelta(weeks=amount), "M": timedelta(days=amount * 30)}
        result = now + deltas.get(unit, timedelta(0))
        return result.strftime(fmt)
    return f"Current time ({tz_name}): {now.strftime(fmt)}"
