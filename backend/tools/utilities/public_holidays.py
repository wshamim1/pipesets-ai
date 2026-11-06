"""Public holidays (Nager.Date) — built-in tool `public_holidays`."""

from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="public_holidays",
    name="Public Holidays",
    icon="🎉",
    category="Everyday Utilities",
    description="Lists public holidays for a country and year (free, no key). Input like 'US 2026'.",
    default_config={"country": "US"},
    order=50,
    parameters=params(
        {"country": {"type": "string", "description": "ISO country code, e.g. US, DE"}},
        {"year": {"type": "integer", "minimum": 1900, "maximum": 2100, "description": "Year; default this year"}},
    ),
    to_input=lambda a: f"{a['country']} {a.get('year') or ''}".strip(),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import re
    # Country: an uppercase ISO code in the input ("US 2026", "holidays in DE"), else config
    country = re.search(r"\b([A-Z]{2})\b", inp) or re.fullmatch(r"\s*([A-Za-z]{2})\s*", inp.split(" ")[0] if inp else "")
    year_m = re.search(r"\b(19|20)\d{2}\b", inp)
    code = (country.group(1) if country else cfg.get("country", "US")).upper()
    year = year_m.group(0) if year_m else str(datetime.now().year)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://date.nager.at/api/v3/PublicHolidays/{year}/{code}")
        if resp.status_code == 404:
            return f"[Holidays] Unknown country code '{code}'. Use a 2-letter ISO code like US, GB, DE."
        resp.raise_for_status()
        holidays = resp.json() if resp.content else []
        if not holidays:
            return f"[Holidays] No data for {code} in {year}."
        lines = [f"[Public holidays — {code} {year}]"]
        for h in holidays:
            local = f" ({h['localName']})" if h.get("localName") and h["localName"] != h.get("name") else ""
            lines.append(f"  {h['date']}  {h.get('name', '')}{local}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Holidays] Error: {e}"
