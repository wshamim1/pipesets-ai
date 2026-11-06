"""MCP Hugging Face — built-in MCP server `mcp_huggingface`: Hugging Face's managed remote server,
reached over Streamable HTTP. Authentication uses a user access token in the ``Authorization``
header. The tools exposed depend on the user's settings at huggingface.co/settings/mcp.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value

URL = "https://huggingface.co/mcp"

TOOL = ToolSpec(
    id="mcp_huggingface",
    name="MCP Hugging Face",
    type="mcp",
    icon="🤗",
    group="mcp_servers",
    category="AI & Memory",
    description="Search Hugging Face models, datasets, Spaces and papers, and browse Hub files and docs.",
    default_config={
        "transport": "http",
        "url": URL,
        "hf_token": "",
    },
    required=("hf_token",),
    order=320,
    is_new=True,
)

DEFAULT_TOOL = "hub_repo_search"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    token = config_value(config, "hf_token")
    headers = {"Authorization": f"Bearer {token}"}
    query = input_text.strip()
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"query": query} if query else {})
    return URL, headers, tool_name, call_args


run = remote_server("MCP Hugging Face", DEFAULT_TOOL, prepare, TOOL.required)
