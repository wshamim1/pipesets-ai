"""MCP Remote SSE — built-in MCP server `mcp_remote_sse`."""

import json
from typing import Any, Dict, List

from tools.base import ToolSpec
from tools.mcp._http import CALL_TIMEOUT, discover_remote, call_remote

TOOL = ToolSpec(
    id="mcp_remote_sse",
    name="MCP Remote SSE",
    type="mcp",
    icon="📡",
    group="mcp_servers",
    category="Web & Browser",
    description="Connect to a legacy MCP HTTP+SSE endpoint.",
    default_config={
        "transport": "sse",
        "url": "https://example.com/sse",
        "headers": {},
    },
    order=86,
    is_new=True,
)


def _headers(value: Any) -> Dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    return {}


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> str:
    url = str(cfg.get("url") or "").strip()
    if not url:
        return f"[{tool_type}] Set config.url to your remote MCP endpoint."
    tool_name = str(cfg.get("tool_name") or "query").strip()
    arguments = cfg.get("arguments")
    if not isinstance(arguments, dict):
        text = inp.strip()
        arguments = {"input": text, "query": text}
    return await call_remote(
        "MCP Remote SSE",
        url,
        _headers(cfg.get("headers")),
        "sse",
        tool_name,
        arguments,
        float(cfg.get("call_timeout") or CALL_TIMEOUT),
    )


async def discover(cfg: Dict[str, Any], tool_type: str = "") -> List[Dict[str, Any]]:
    url = str(cfg.get("url") or "").strip()
    if not url:
        raise RuntimeError(f"[{tool_type or 'mcp_remote_sse'}] Set config.url to discover tools.")
    return await discover_remote(
        url,
        _headers(cfg.get("headers")),
        "sse",
        float(cfg.get("call_timeout") or CALL_TIMEOUT),
    )


run.discover = discover
