"""MCP Jina AI — built-in MCP server `mcp_jina`: Jina's managed remote server, reached over
Streamable HTTP. It exposes web, arXiv and SSRN search, URL reading, screenshots and reranking.
Authentication uses a Jina API key in the ``Authorization`` header. A URL input reads that page;
anything else becomes a web search.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value

URL = "https://mcp.jina.ai/v1"

TOOL = ToolSpec(
    id="mcp_jina",
    name="MCP Jina AI",
    type="mcp",
    icon="🔎",
    group="mcp_servers",
    category="Web & Browser",
    description="Search the web, arXiv and SSRN, and read pages or PDFs as clean markdown through Jina.",
    default_config={
        "transport": "http",
        "url": URL,
        "jina_api_key": "",
    },
    required=("jina_api_key",),
    order=350,
    is_new=True,
)

DEFAULT_TOOL = "search_web"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    token = config_value(config, "jina_api_key")
    headers = {"Authorization": f"Bearer {token}"}
    text = input_text.strip()
    if config.get("tool_name"):
        tool_name = config["tool_name"]
        call_args = config.get("arguments") or {}
    elif text.startswith(("http://", "https://")):
        tool_name = "read_url"
        call_args = {"url": text}
    elif text:
        tool_name = defaults["default_tool"]
        call_args = {"query": text}
    else:
        tool_name = "primer"
        call_args = {}
    return URL, headers, tool_name, call_args


run = remote_server("MCP Jina AI", DEFAULT_TOOL, prepare, TOOL.required)
