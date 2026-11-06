"""MCP Browserbase — built-in MCP server `mcp_browserbase` (@browserbasehq/mcp, by Browserbase;
version pinned).

Cloud browser automation with Browserbase and Stagehand: navigate, act, observe and extract.
Credentials go in ``BROWSERBASE_API_KEY`` / ``BROWSERBASE_PROJECT_ID``; Stagehand also needs a
Gemini (or Google) API key for its model.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_browserbase",
    name="MCP Browserbase",
    type="mcp",
    icon="🧭",
    group="mcp_servers",
    category="Web & Browser",
    description="Drive cloud browsers with Browserbase and Stagehand: navigate, act, observe and extract.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@browserbasehq/mcp@3.0.0"],
        "browserbase_api_key": "",
        "browserbase_project_id": "",
        "gemini_api_key": "",
    },
    required=("browserbase_api_key", "browserbase_project_id"),
    order=330,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@browserbasehq/mcp@3.0.0"]
DEFAULT_TOOL = "navigate"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["BROWSERBASE_API_KEY"] = config_value(config, "browserbase_api_key")
    env_vars["BROWSERBASE_PROJECT_ID"] = config_value(config, "browserbase_project_id")
    gemini_key = config_value(config, "gemini_api_key")
    if gemini_key:
        env_vars["GEMINI_API_KEY"] = gemini_key
    url = input_text.strip()
    tool_name = config.get("tool_name") or ("navigate" if url else "start")
    call_args = config.get("arguments") or ({"url": url} if url else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
