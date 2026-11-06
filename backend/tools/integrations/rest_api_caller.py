"""HTTP / REST API — built-in tool `rest_api_caller`."""

import json
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, json_value, params

TOOL = ToolSpec(
    id="rest_api_caller",
    name="HTTP / REST API",
    icon="⚡",
    category="APIs & Integrations",
    description="Sends GET/POST requests with custom headers & payload.",
    default_config={"method": "GET", "url": "https://api.example.com", "headers": "{}"},
    order=10,
    selects={
        "method": Select("HTTP method", (("GET", "GET"), ("POST", "POST"), ("PUT", "PUT"), ("PATCH", "PATCH"), ("DELETE", "DELETE"))),
    },
    parameters=params(
        {},
        {"body": {"type": "object", "description": "JSON payload; the URL and method are set on the node"}},
    ),
    to_input=json_value("body"),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    method = cfg.get("method", "GET").upper()
    url = cfg.get("url", "https://httpbin.org/get")
    headers_raw = cfg.get("headers", "{}")
    try:
        headers = json.loads(headers_raw) if isinstance(headers_raw, str) else headers_raw
    except json.JSONDecodeError:
        headers = {}

    # Try to parse inp as JSON body; otherwise use as query param
    body = None
    params = None
    try:
        body = json.loads(inp)
    except (json.JSONDecodeError, TypeError):
        params = {"q": inp} if method == "GET" else None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method, url,
                headers=headers,
                json=body if method != "GET" else None,
                params=params,
            )
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                try:
                    payload = json.dumps(resp.json(), indent=2)[:1000]
                except Exception:
                    payload = resp.text[:1000]
            else:
                payload = resp.text[:1000]
            return f"HTTP {resp.status_code} {method} {url}\n\n{payload}"
    except Exception as e:
        return f"HTTP Request Error: {e}"
