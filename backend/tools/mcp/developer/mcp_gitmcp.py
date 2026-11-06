"""MCP GitMCP — built-in MCP server `mcp_gitmcp`: the hosted GitMCP server (gitmcp.io), reached over
Streamable HTTP with no key. It reads the documentation (llms.txt, README, docs) and searches the
code of any public GitHub repository.

Input ``owner/repo: question`` searches that repo's docs; ``owner/repo`` alone reads its main
documentation; a URL reads that page. With ``repo_name`` set, the whole input is the question.
"""

import re
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server

URL = "https://gitmcp.io/docs"
_REPO = re.compile(r"^(?:https://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)/?\s*(?::\s*(.*))?$", re.S)

TOOL = ToolSpec(
    id="mcp_gitmcp",
    name="MCP GitMCP",
    type="mcp",
    icon="🐈",
    group="mcp_servers",
    category="Developer Tools",
    description="Read the docs and search the code of any public GitHub repo, so answers use the library's current documentation. Input: 'owner/repo: question'. No key needed.",
    default_config={
        "transport": "http",
        "url": URL,
        "repo_name": "",
    },
    order=395,
    is_new=True,
)

DEFAULT_TOOL = "search_generic_documentation"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    if config.get("tool_name"):
        return URL, {}, config["tool_name"], config.get("arguments") or {}
    text = input_text.strip()
    repo = str(config.get("repo_name") or "").strip()
    if not repo and re.match(r"^https?://", text) and not text.startswith("https://github.com/"):
        return URL, {}, "fetch_generic_url_content", {"url": text}
    m = _REPO.match(f"{repo}: {text}" if repo else text)
    if not m:
        return URL, {}, "match_common_libs_owner_repo_mapping", {"library": text}
    owner, name, question = m.group(1), m.group(2), (m.group(3) or "").strip()
    if not question:
        return URL, {}, "fetch_generic_documentation", {"owner": owner, "repo": name}
    return URL, {}, defaults["default_tool"], {"owner": owner, "repo": name, "query": question}


run = remote_server("MCP GitMCP", DEFAULT_TOOL, prepare)
