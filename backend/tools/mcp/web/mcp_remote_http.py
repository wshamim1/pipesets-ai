"""MCP Remote HTTP — built-in MCP server `mcp_remote_http`."""

import json
from typing import Any, Dict, List

from tools.base import ToolSpec
from tools.mcp._http import CALL_TIMEOUT, discover_remote, call_remote

TOOL = ToolSpec(
    id="mcp_remote_http",
    name="MCP Remote HTTP",
    type="mcp",
    icon="🌐",
    group="mcp_servers",
    category="Web & Browser",
    description="Connect to a remote MCP endpoint over Streamable HTTP (auto-falls back when needed).",
    default_config={
        "transport": "http",
        "url": "https://example.com/mcp",
        "headers": {},
    },
    order=85,
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
        "MCP Remote HTTP",
        url,
        _headers(cfg.get("headers")),
        "http",
        tool_name,
        arguments,
        float(cfg.get("call_timeout") or CALL_TIMEOUT),
    )


async def discover(cfg: Dict[str, Any], tool_type: str = "") -> List[Dict[str, Any]]:
    url = str(cfg.get("url") or "").strip()
    if not url:
        raise RuntimeError(f"[{tool_type or 'mcp_remote_http'}] Set config.url to discover tools.")
    return await discover_remote(
        url,
        _headers(cfg.get("headers")),
        "http",
        float(cfg.get("call_timeout") or CALL_TIMEOUT),
    )


run.discover = discover
