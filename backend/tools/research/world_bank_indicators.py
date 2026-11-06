"""World Bank indicators — built-in tool `world_bank_indicators` (World Bank API v2; free, no key).

Input: ``<indicator> <countries> [years]``, e.g. ``gdp US;IN 2015:2024``. The indicator is a World
Bank code (NY.GDP.MKTP.CD) or a short name from ALIASES; countries are ISO codes separated by ``;``
(or ``all``, WLD for the world); years is one year or a ``start:end`` range (default: the last ten).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[World Bank]"
API = "https://api.worldbank.org/v2/country/{countries}/indicator/{indicator}"
ALIASES = {
    "gdp": "NY.GDP.MKTP.CD", "gdp_per_capita": "NY.GDP.PCAP.CD", "gdp_growth": "NY.GDP.MKTP.KD.ZG",
    "population": "SP.POP.TOTL", "inflation": "FP.CPI.TOTL.ZG", "unemployment": "SL.UEM.TOTL.ZS",
    "life_expectancy": "SP.DYN.LE00.IN", "co2_per_capita": "EN.GHG.CO2.PC.CE.AR5", "exports": "NE.EXP.GNFS.CD",
    "internet_users": "IT.NET.USER.ZS", "literacy": "SE.ADT.LITR.ZS", "gini": "SI.POV.GINI",
}

TOOL = ToolSpec(
    id="world_bank_indicators",
    name="World Bank Indicators",
    icon="🌍",
    category="Research & Knowledge",
    description="Country statistics from the World Bank: GDP, population, inflation, unemployment, life expectancy and 1,400+ other indicators by year. Free, no key.",
    default_config={},
    order=155,
    parameters=params(
        {"indicator": {"type": "string", "description": f"World Bank indicator code, or one of: {', '.join(ALIASES)}"},
         "countries": {"type": "string", "description": "ISO country codes separated by ';' (e.g. US;IN;DE), WLD for the world"}},
        {"years": {"type": "string", "description": "A year or range like 2015:2024; default the last ten years"}},
    ),
    to_input=lambda a: " ".join(str(a[k]) for k in ("indicator", "countries", "years") if a.get(k)),
)


def _fmt(v: float) -> str:
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= size:
            return f"{v / size:,.2f}{unit}"
    return f"{v:,.2f}" if v != int(v) else f"{int(v):,}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    parts = inp.split()
    if len(parts) < 2:
        return f"{LABEL} Input is '<indicator> <countries> [years]', e.g. 'gdp US;IN 2015:2024'. Short names: {', '.join(ALIASES)}."
    indicator = ALIASES.get(parts[0].lower(), parts[0].upper())
    countries = parts[1].replace(",", ";").upper()
    this_year = datetime.now().year
    years = parts[2] if len(parts) > 2 else f"{this_year - 10}:{this_year}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(API.format(countries=countries, indicator=indicator),
                                    params={"format": "json", "date": years, "per_page": 1000})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach the World Bank API: {e}"
    try:
        body = resp.json()
    except ValueError:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    if isinstance(body, list) and body and isinstance(body[0], dict) and body[0].get("message"):
        return f"{LABEL} {body[0]['message'][0].get('value', 'Request rejected')}"
    rows: List[Dict[str, Any]] = (body[1] if isinstance(body, list) and len(body) > 1 else None) or []
    rows = [r for r in rows if r.get("value") is not None]
    if not rows:
        return f"{LABEL} No data for {indicator} in {countries} for {years}."
    name = (rows[0].get("indicator") or {}).get("value", indicator)
    out = [f"{LABEL} {name} ({indicator}), {years}"]
    by_country: Dict[str, List[str]] = {}
    for r in sorted(rows, key=lambda r: ((r.get("country") or {}).get("value", ""), r.get("date", ""))):
        by_country.setdefault((r.get("country") or {}).get("value", "?"), []).append(f"{r['date']}: {_fmt(float(r['value']))}")
    for country, values in by_country.items():
        out.append(f"\n{country}\n  " + "\n  ".join(values))
    return "\n".join(out)
