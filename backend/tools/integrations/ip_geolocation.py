"""IP geolocation — built-in tool `ip_geolocation`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="ip_geolocation",
    name="IP Geolocation",
    icon="📍",
    category="APIs & Integrations",
    description="Looks up the location, timezone and network of an IP address (free, no key). Empty input = server IP.",
    default_config={},
    order=30,
    parameters=params(
        {},
        {"ip": {"type": "string", "description": "IPv4 / IPv6 address; leave out for the server's"}},
    ),
    input_param="ip",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    ip = inp.split()[0] if inp else ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://ipwho.is/{ip}")
            resp.raise_for_status()
            d = resp.json()
        if not d.get("success", False):
            return f"[IP Geolocation] {d.get('message', 'Lookup failed')} for '{ip}'"
        conn = d.get("connection", {})
        return (
            f"[IP Geolocation: {d.get('ip')}]\n"
            f"  Location : {d.get('city')}, {d.get('region')}, {d.get('country')} ({d.get('country_code')})\n"
            f"  Coords   : {d.get('latitude')}, {d.get('longitude')}\n"
            f"  Timezone : {d.get('timezone', {}).get('id', '?')}\n"
            f"  Network  : {conn.get('isp', '?')} (AS{conn.get('asn', '?')})"
        )
    except Exception as e:
        return f"[IP Geolocation] Error: {e}"
