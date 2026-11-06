"""MCP Wikipedia — built-in MCP server `mcp_wikipedia` (wikipedia-mcp; version pinned).

Search Wikipedia and read articles, summaries, sections, links, related topics and coordinates, in
any language edition (``--language``). No key needed. The input becomes a search.
"""

from typing import Any, Dict

from tools._choices import WIKIPEDIA_LANGUAGES
from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_wikipedia",
    name="MCP Wikipedia",
    type="mcp",
    icon="📖",
    group="mcp_servers",
    category="Web & Browser",
    description="Search Wikipedia and read articles, summaries, sections, key facts and related topics in any language. No key needed.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["wikipedia-mcp@2.0.1"],
        "language": "en",
    },
    selects={"language": Select("Language", WIKIPEDIA_LANGUAGES)},
    order=410,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["wikipedia-mcp@2.0.1"]
DEFAULT_TOOL = "search_wikipedia"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → launch args, and the MCP tool to call with its arguments."""
    args = [*args, "--language", config_value(config, "language") or "en"]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
