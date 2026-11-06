"""MCP Puppeteer — built-in MCP server `mcp_puppeteer`.

The reference server is deprecated upstream and pinned to its last release (use MCP Playwright instead)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_puppeteer",
    name="MCP Puppeteer",
    type="mcp",
    icon="🤖",
    group="mcp_servers",
    category="Web & Browser",
    description="Browser automation — scrape, screenshot, and interact with web pages.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer@2025.5.12"],
    },
    hidden=True,   # deprecated upstream; MCP Playwright covers it. Old pipelines still run
    order=60,
)

COMMAND = "npx"
ARGS = ["-y", "@modelcontextprotocol/server-puppeteer@2025.5.12"]
DEFAULT_TOOL = "puppeteer_navigate"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"url": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
