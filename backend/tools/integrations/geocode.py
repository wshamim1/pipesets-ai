"""Geocoding (OpenStreetMap Nominatim) — built-in tool `geocode`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import MAX_RESULTS, ToolSpec, params

TOOL = ToolSpec(
    id="geocode",
    name="Geocoding (OpenStreetMap)",
    icon="🗺️",
    category="APIs & Integrations",
    description="Address/place → coordinates, or 'lat, lon' → address, via OpenStreetMap Nominatim.",
    default_config={"max_results": 3},
    order=60,
    parameters=params(
        {"query": {"type": "string", "description": "An address or place, or 'lat, lon' to look up its address"}},
        {"max_results": MAX_RESULTS},
    ),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import re
    if not inp:
        return "[Geocode] Provide an address/place, or 'lat, lon' to reverse-geocode."
    coords = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", inp)
    # Nominatim's usage policy requires an identifying User-Agent
    headers = {"User-Agent": "PipesetsAI/1.0 (https://github.com/pipesets-ai; tool: geocode)"}
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            if coords:
                resp = await client.get("https://nominatim.openstreetmap.org/reverse", params={
                    "lat": coords.group(1), "lon": coords.group(2), "format": "json"})
                resp.raise_for_status()
                d = resp.json()
                if "error" in d:
                    return f"[Geocode] {d['error']}"
                return f"[Reverse geocode: {coords.group(1)}, {coords.group(2)}]\n  {d.get('display_name', '')}"
            resp = await client.get("https://nominatim.openstreetmap.org/search", params={
                "q": inp, "format": "json", "limit": int(cfg.get("max_results", 3))})
            resp.raise_for_status()
            places = resp.json()
        if not places:
            return f"[Geocode] No place found for: {inp}"
        lines = [f"[Geocode: '{inp}']"]
        for p in places:
            lines.append(f"  {p.get('display_name', '')}\n    lat {float(p['lat']):.5f}, lon {float(p['lon']):.5f} ({p.get('type', '')})")
        return "\n".join(lines)
    except Exception as e:
        return f"[Geocode] Error: {e}"
