"""Air quality (Open-Meteo) — built-in tool `air_quality`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="air_quality",
    name="Air Quality",
    icon="🌫️",
    category="Everyday Utilities",
    description="Current air quality index and pollutants for a city (Open-Meteo, free, no key).",
    default_config={},
    order=70,
    parameters=params({"city": {"type": "string", "description": "City, e.g. Delhi"}}),
    input_param="city",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    place = inp.strip()
    if not place:
        return "[Air quality] Provide a city name."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            geo = await client.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": place, "count": 1})
            geo.raise_for_status()
            hits = geo.json().get("results") or []
            if not hits:
                return f"[Air quality] Unknown place: {place}"
            g = hits[0]
            aq = await client.get("https://air-quality-api.open-meteo.com/v1/air-quality", params={
                "latitude": g["latitude"], "longitude": g["longitude"],
                "current": "us_aqi,european_aqi,pm2_5,pm10,ozone,nitrogen_dioxide,carbon_monoxide",
            })
            aq.raise_for_status()
            cur = aq.json().get("current", {})
        aqi = cur.get("us_aqi")
        band = next((label for limit, label in ((50, "Good"), (100, "Moderate"), (150, "Unhealthy for sensitive groups"),
                                                (200, "Unhealthy"), (300, "Very unhealthy"), (10**9, "Hazardous"))
                     if aqi is not None and aqi <= limit), "unknown")
        return (f"[Air quality: {g['name']}, {g.get('country', '')}]\n"
                f"  US AQI      : {aqi} ({band})\n  European AQI: {cur.get('european_aqi')}\n"
                f"  PM2.5 {cur.get('pm2_5')} µg/m³ · PM10 {cur.get('pm10')} µg/m³ · O₃ {cur.get('ozone')} µg/m³ · "
                f"NO₂ {cur.get('nitrogen_dioxide')} µg/m³")
    except Exception as e:
        return f"[Air quality] Error: {e}"
