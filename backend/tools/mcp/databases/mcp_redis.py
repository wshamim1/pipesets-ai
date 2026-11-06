"""MCP Redis — built-in MCP server `mcp_redis` (redis-mcp-server, by Redis; version pinned).

Replaces the npm `mcp-redis`, which had no source repository and an unknown publisher."""

import os
from typing import Any, Dict
from urllib.parse import unquote, urlparse

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_redis",
    name="MCP Redis",
    type="mcp",
    icon="🔴",
    group="mcp_servers",
    category="Databases & Data",
    description="Redis strings, hashes, lists, sets, streams, JSON and vector search. Useful for cache inspection.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "redis-mcp-server@0.5.1", "redis-mcp-server"],
        "env_vars": {"REDIS_URL": "redis://localhost:6379"},
    },
    order=250,
)

COMMAND = "uvx"
ARGS = ["--from", "redis-mcp-server@0.5.1", "redis-mcp-server"]
DEFAULT_TOOL = "get"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    redis_url = (
        config.get("redis_url")
        or config.get("REDIS_URL")
        or os.environ.get("REDIS_URL", "redis://localhost:6379")
    )
    # As env vars, not --url: the URL may hold a password, and a command line is visible to `ps`
    url = urlparse(redis_url if "://" in redis_url else f"redis://{redis_url}")
    env_vars["REDIS_HOST"] = url.hostname or "localhost"
    env_vars["REDIS_PORT"] = str(url.port or 6379)
    env_vars["REDIS_SSL"] = "true" if url.scheme == "rediss" else "false"
    if url.username:
        env_vars["REDIS_USERNAME"] = unquote(url.username)
    if url.password:
        env_vars["REDIS_PWD"] = unquote(url.password)
    if url.path.strip("/").isdigit():
        env_vars["REDIS_DB"] = url.path.strip("/")
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"key": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
