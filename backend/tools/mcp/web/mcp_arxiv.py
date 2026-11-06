"""MCP arXiv — built-in MCP server `mcp_arxiv` (arxiv-mcp-server; version pinned).

Searches arXiv, reads abstracts and full papers, exports citations and watches topics for new
papers. No key needed. An arXiv id input (2401.12345 or hep-th/9901001) reads that paper's abstract;
anything else becomes a search. Downloaded papers go in ``storage_path`` (the server's default is
~/.arxiv-mcp-server/papers).
"""

import re
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

_ARXIV_ID = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)$", re.I)

TOOL = ToolSpec(
    id="mcp_arxiv",
    name="MCP arXiv",
    type="mcp",
    icon="📄",
    group="mcp_servers",
    category="Web & Browser",
    description="Search arXiv, read abstracts and full papers, and export citations. Input: a search or an arXiv id. No key needed.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["arxiv-mcp-server@0.8.2"],
        "storage_path": "",
    },
    order=390,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["arxiv-mcp-server@0.8.2"]
DEFAULT_TOOL = "search_papers"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args, and the MCP tool to call with its arguments."""
    storage = config_value(config, "storage_path")
    if storage:
        args = [*args, "--storage-path", storage]
    if config.get("tool_name"):
        return args, config["tool_name"], config.get("arguments") or {}
    text = input_text.strip()
    m = _ARXIV_ID.match(text)
    if m:
        return args, "get_abstract", {"paper_id": m.group(1)}
    return args, defaults["default_tool"], {"query": text}


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
