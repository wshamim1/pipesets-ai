"""MCP AWS Knowledge — built-in MCP server `mcp_aws_knowledge`: AWS's hosted knowledge server
(knowledge-mcp.global.api.aws), reached over Streamable HTTP with no key. It searches and reads AWS
documentation, What's New posts and blogs, and answers which services and APIs each region offers.
An aws.amazon.com URL input reads that page; anything else becomes a documentation search.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server

URL = "https://knowledge-mcp.global.api.aws"

TOOL = ToolSpec(
    id="mcp_aws_knowledge",
    name="MCP AWS Knowledge",
    type="mcp",
    icon="☁️",
    group="mcp_servers",
    category="Developer Tools",
    description="Search and read AWS docs, What's New and blogs, and check which regions offer a service or API. No key needed.",
    default_config={
        "transport": "http",
        "url": URL,
    },
    order=380,
    is_new=True,
)

DEFAULT_TOOL = "aws___search_documentation"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    if config.get("tool_name"):
        return URL, {}, config["tool_name"], config.get("arguments") or {}
    text = input_text.strip()
    if text.startswith(("http://", "https://")):
        return URL, {}, "aws___read_documentation", {"requests": [{"url": text}]}
    if not text:
        return URL, {}, "aws___list_regions", {}
    return URL, {}, defaults["default_tool"], {"search_phrase": text}


run = remote_server("MCP AWS Knowledge", DEFAULT_TOOL, prepare)
