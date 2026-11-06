"""Cron helper — built-in tool `cron_helper` (croniter; offline).

Explains a cron expression field by field and lists its next run times in a timezone. Accepts
five fields (minute hour day month weekday), an optional sixth seconds field, and the @hourly /
@daily / @weekly / @monthly / @yearly shortcuts.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tools.base import ToolSpec, params

LABEL = "[Cron]"
FIELDS = ("minute", "hour", "day of month", "month", "day of week", "second")
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
DAYS = "Sun Mon Tue Wed Thu Fri Sat".split()
SHORTCUTS = {"@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
             "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@hourly": "0 * * * *"}

TOOL = ToolSpec(
    id="cron_helper",
    name="Cron Expression Helper",
    icon="⏰",
    category="Everyday Utilities",
    description="Explains a cron expression field by field and lists its next run times in any timezone. Input like '*/15 9-17 * * 1-5'.",
    default_config={"timezone": "UTC", "count": 5},
    order=90,
    parameters=params(
        {"expression": {"type": "string", "description": "Cron expression, e.g. '0 9 * * 1-5' or '@daily'"}},
        {"timezone": {"type": "string", "description": "IANA timezone for the run times, e.g. Europe/Berlin"},
         "count": {"type": "integer", "minimum": 1, "maximum": 20, "description": "How many next runs to list"}},
    ),
    input_param="expression",
)


def _name(field: int, value: str) -> str:
    if field == 3 and value.isdigit() and 1 <= int(value) <= 12:
        return MONTHS[int(value) - 1]
    if field == 4 and value.isdigit() and 0 <= int(value) <= 7:
        return DAYS[int(value) % 7]
    return value


def _explain(field: int, part: str) -> str:
    if part in ("*", "?"):
        return "every " + FIELDS[field]
    pieces = []
    for item in part.split(","):
        base, _, step = item.partition("/")
        if base in ("*", ""):
            text = f"every {step} {FIELDS[field]}s" if step else f"every {FIELDS[field]}"
        elif "-" in base:
            lo, _, hi = base.partition("-")
            text = f"{_name(field, lo)} through {_name(field, hi)}" + (f", every {step}" if step else "")
        else:
            text = _name(field, base) + (f" and every {step} after" if step else "")
        pieces.append(text)
    return ", ".join(pieces)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    from croniter import CroniterBadCronError, croniter

    expr = inp.strip().strip("'\"")
    if not expr:
        return f"{LABEL} Provide a cron expression, e.g. '0 9 * * 1-5'."
    expanded = SHORTCUTS.get(expr.lower(), expr)
    tz_name = (cfg.get("timezone") or "UTC").strip()
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return f"{LABEL} Unknown timezone '{tz_name}'. Use an IANA name like UTC or America/New_York."
    parts = expanded.split()
    if len(parts) not in (5, 6):
        return f"{LABEL} A cron expression has 5 fields (minute hour day month weekday), or 6 with seconds — got {len(parts)}."
    try:
        it = croniter(expanded, datetime.now(tz))
        count = max(1, min(int(cfg.get("count") or 5), 20))
        runs = [it.get_next(datetime) for _ in range(count)]
    except (CroniterBadCronError, ValueError, KeyError) as e:
        return f"{LABEL} Invalid cron expression '{expr}': {e}"

    lines = [f"{LABEL} {expr}" + (f"  (= {expanded})" if expanded != expr else "")]
    for i, part in enumerate(parts):
        lines.append(f"  {FIELDS[i]:<13} {part:<10} {_explain(i, part)}")
    if parts[2] not in ("*", "?") and parts[4] not in ("*", "?"):
        lines.append("  Note: day of month and day of week are both set, so it runs when either matches.")
    lines.append(f"\nNext {count} run(s) in {tz_name}:")
    lines += [f"  {r.strftime('%a %Y-%m-%d %H:%M:%S %Z')}" for r in runs]
    return "\n".join(lines)
