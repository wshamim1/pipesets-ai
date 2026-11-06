"""Date calculator — built-in tool `date_calculator`."""

import re
from datetime import date, timedelta
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="date_calculator",
    name="Date Calculator",
    icon="📅",
    category="Everyday Utilities",
    description="Days or business days between two dates, add/subtract days or business days, and the weekday of a date. E.g. 'business days between 2026-11-02 and 2026-12-24' or '2026-10-26 + 30 days'.",
    default_config={"weekend": "sat,sun", "holidays": ""},
    order=80,
    parameters=params(
        {
            "request": {"type": "string", "description": "e.g. 'business days between 2026-11-02 and 2026-12-24' or '2026-10-26 + 30 days'"},
        },
    ),
    input_param="request",
)

_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_DATE = r"(today|tomorrow|yesterday|\d{4}-\d{1,2}-\d{1,2}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2} [A-Za-z]{3,9}\.? \d{4}|\d{1,2}/\d{1,2}/\d{4})"


def _parse(text: str) -> date:
    t = text.strip().lower()
    today = date.today()
    if t in ("today", "tomorrow", "yesterday"):
        return today + timedelta(days={"today": 0, "tomorrow": 1, "yesterday": -1}[t])
    from dateutil import parser
    return parser.parse(text, dayfirst=False).date()


def _business_days(start: date, end: date, weekend: set, holidays: set) -> int:
    step = 1 if end >= start else -1
    count, d = 0, start
    while d != end:
        d += timedelta(days=step)
        if d.weekday() not in weekend and d not in holidays:
            count += step
    return count


def _add_business(start: date, n: int, weekend: set, holidays: set) -> date:
    step = 1 if n >= 0 else -1
    d, left = start, abs(n)
    while left:
        d += timedelta(days=step)
        if d.weekday() not in weekend and d not in holidays:
            left -= 1
    return d


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    text = inp.strip()
    weekend = {_DAYS[d.strip()[:3].lower()] for d in str(cfg.get("weekend", "sat,sun")).split(",") if d.strip()[:3].lower() in _DAYS}
    holidays = set()
    for h in str(cfg.get("holidays", "")).split(","):
        if h.strip():
            try:
                holidays.add(_parse(h))
            except Exception:
                pass
    fmt = lambda d: f"{d:%Y-%m-%d} ({d:%A})"  # noqa: E731
    try:
        m = re.search(rf"(business|working|week)?\s*days?\s+(?:between|from)\s+{_DATE}\s+(?:and|to|until)\s+{_DATE}", text, re.I)
        if m:
            a, b = _parse(m.group(2)), _parse(m.group(3))
            calendar = (b - a).days
            if m.group(1):
                biz = _business_days(a, b, weekend, holidays)
                return (f"[Dates] {biz} business days from {fmt(a)} to {fmt(b)} "
                        f"({calendar} calendar days; start date excluded, end date included)")
            weeks, days = divmod(abs(calendar), 7)
            return f"[Dates] {calendar} days from {fmt(a)} to {fmt(b)} ({weeks} weeks {days} days)"

        m = (re.search(rf"{_DATE}\s*([+-])\s*(\d+)\s*(business|working)?\s*(day|week|month|year)s?", text, re.I)
             or re.search(rf"(add|subtract)\s+(\d+)\s*(business|working)?\s*(day|week|month|year)s?\s+(?:to|from)\s+{_DATE}", text, re.I))
        if m:
            if m.group(1).lower() in ("add", "subtract"):
                sign, n, biz, unit, base = ("-" if m.group(1).lower() == "subtract" else "+"), int(m.group(2)), m.group(3), m.group(4), m.group(5)
            else:
                base, sign, n, biz, unit = m.group(1), m.group(2), int(m.group(3)), m.group(4), m.group(5)
            start, n = _parse(base), n if sign == "+" else -n
            unit = unit.lower()
            if biz:
                if unit != "day":
                    return "[Dates] Business-day arithmetic works in days, e.g. '+ 10 business days'."
                result = _add_business(start, n, weekend, holidays)
            elif unit in ("day", "week"):
                result = start + timedelta(days=n * (7 if unit == "week" else 1))
            else:
                from dateutil.relativedelta import relativedelta
                result = start + (relativedelta(months=n) if unit == "month" else relativedelta(years=n))
            plural = "" if abs(n) == 1 else "s"
            return f"[Dates] {fmt(start)} {sign} {abs(n)} {'business ' if biz else ''}{unit}{plural} = {fmt(result)}"

        m = re.search(_DATE, text, re.I)
        if m:
            d = _parse(m.group(1))
            delta = (d - date.today()).days
            when = "today" if delta == 0 else (f"in {delta} days" if delta > 0 else f"{-delta} days ago")
            return f"[Dates] {fmt(d)} — week {d.isocalendar()[1]}, day {d.timetuple().tm_yday} of the year, {when}"
    except (ValueError, OverflowError) as e:
        return f"[Dates] Couldn't read a date: {e}"
    return ("[Dates] Try: 'days between 2026-01-01 and 2026-03-15', 'business days between today and 2026-12-24', "
            "'2026-10-26 + 30 days', 'add 10 business days to today', or a single date.")

