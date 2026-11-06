"""MCP Perplexity — built-in MCP server `mcp_perplexity` (@perplexity-ai/mcp-server, by Perplexity; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_perplexity",
    name="MCP Perplexity",
    type="mcp",
    icon="❓",
    group="mcp_servers",
    category="Web & Browser",
    description="Web search, cited answers, deep research and reasoning through the Perplexity API.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@perplexity-ai/mcp-server@1.3.0"],
        "perplexity_api_key": "",
    },
    required=("perplexity_api_key",),
    order=320,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@perplexity-ai/mcp-server@1.3.0"]
DEFAULT_TOOL = "perplexity_search"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["PERPLEXITY_API_KEY"] = config_value(config, "perplexity_api_key")
    call_args = config.get("arguments") or {"query": input_text.strip()}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
