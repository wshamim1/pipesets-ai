"""FRED — built-in tool `fred_economic_data` (St. Louis Fed FRED API; a free key from
fred.stlouisfed.org/docs/api/api_key.html).

Input: a series id (``UNRATE``, ``CPIAUCSL``, ``DGS10``) or a short name from ALIASES reads the
series' latest observations, newest first; anything else searches series by text, most popular
first. ``start`` (YYYY-MM-DD) reads from that date instead of the latest ``max_results``.
"""

import re
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[FRED]"
API = "https://api.stlouisfed.org/fred"
ALIASES = {
    "unemployment": "UNRATE", "cpi": "CPIAUCSL", "core_cpi": "CPILFESL", "inflation": "CPIAUCSL",
    "gdp": "GDP", "real_gdp": "GDPC1", "fed_funds": "FEDFUNDS", "10y_treasury": "DGS10", "2y_treasury": "DGS2",
    "mortgage_30y": "MORTGAGE30US", "payrolls": "PAYEMS", "pce": "PCEPI", "m2": "M2SL", "sp500": "SP500",
    "housing_starts": "HOUST", "retail_sales": "RSAFS", "industrial_production": "INDPRO", "vix": "VIXCLS",
}
_SERIES = re.compile(r"^[A-Z0-9][A-Z0-9_.]{1,40}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TOOL = ToolSpec(
    id="fred_economic_data",
    name="FRED Economic Data",
    icon="📈",
    category="Research & Knowledge",
    description="US and international economic time series from the St. Louis Fed (FRED): unemployment, CPI, GDP, rates, payrolls and 800,000+ more. Input: a series id like UNRATE, or words to search series.",
    default_config={"api_key": "", "start": "", "max_results": 12},
    order=165,
    required=("api_key",),
    parameters=params(
        {"series": {"type": "string", "description": f"A FRED series id (UNRATE, DGS10…), one of: {', '.join(ALIASES)}; or words to search for series"}},
        {"start": {"type": "string", "description": "Read observations from this date (YYYY-MM-DD) instead of the latest ones"}},
    ),
    input_param="series",
    is_new=True,
)


def _error(resp: httpx.Response) -> str:
    try:
        msg = resp.json().get("error_message")
    except ValueError:
        msg = None
    if resp.status_code in (400, 403) and msg and "api_key" in msg:
        return f"{LABEL} {msg} — check api_key."
    return f"{LABEL} HTTP {resp.status_code}: {msg or resp.text[:200]}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    key = str(cfg.get("api_key") or "").strip()
    if not key:
        return f"{LABEL} api_key is required in config (free at fred.stlouisfed.org/docs/api/api_key.html)."
    text = inp.strip().strip("'\"")
    if not text:
        return f"{LABEL} Give a series id like UNRATE, or words to search for."
    start = str(cfg.get("start") or "").strip()
    if start and not _DATE.match(start):
        return f"{LABEL} start is a date like 2020-01-01 — got '{start}'."
    limit = max(1, min(int(cfg.get("max_results") or 12), 100))
    series_id = ALIASES.get(text.lower().replace(" ", "_"), text if _SERIES.match(text) else "")
    base = {"api_key": key, "file_type": "json"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            if not series_id:
                resp = await client.get(f"{API}/series/search", params={
                    **base, "search_text": text, "order_by": "popularity", "sort_order": "desc", "limit": limit})
                if resp.status_code >= 400:
                    return _error(resp)
                found = resp.json().get("seriess") or []
                if not found:
                    return f"{LABEL} No series match '{text}'."
                return f"{LABEL} {len(found)} series for '{text}' (most popular first)\n" + "\n".join(
                    f"- {s.get('id')} · {s.get('title')} · {s.get('frequency_short')} · {s.get('units_short')}"
                    f" · {s.get('observation_start')} to {s.get('observation_end')}" for s in found)
            info = await client.get(f"{API}/series", params={**base, "series_id": series_id})
            if info.status_code >= 400:
                return _error(info)
            q = {**base, "series_id": series_id}
            q.update({"observation_start": start, "sort_order": "asc", "limit": 1000} if start
                     else {"sort_order": "desc", "limit": limit})
            resp = await client.get(f"{API}/series/observations", params=q)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach FRED: {e}"
    if resp.status_code >= 400:
        return _error(resp)
    s = (info.json().get("seriess") or [{}])[0]
    obs = [o for o in resp.json().get("observations") or [] if o.get("value") not in (None, ".")]
    if start:
        obs = list(reversed(obs))[:limit]
    head = (f"{LABEL} {series_id}: {s.get('title', '')} ({s.get('units', '')}, {s.get('frequency', '')}"
            f"{', ' + s['seasonal_adjustment_short'] if s.get('seasonal_adjustment_short') else ''})\n"
            f"  Last updated {(s.get('last_updated') or '')[:10]} · https://fred.stlouisfed.org/series/{series_id}")
    if not obs:
        return head + "\n  No observations" + (f" since {start}." if start else ".")
    return head + "\n" + "\n".join(f"- {o['date']}: {o['value']}" for o in obs)
