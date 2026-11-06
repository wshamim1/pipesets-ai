"""MCP DeepWiki — built-in MCP server `mcp_deepwiki`: Cognition's hosted DeepWiki server
(mcp.deepwiki.com), reached over Streamable HTTP with no key. It answers questions about public
GitHub repositories from their generated wikis.

Input ``owner/repo: question`` asks that question; ``owner/repo`` alone lists the wiki's topics.
With ``repo_name`` set, the whole input is the question.
"""

import re
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server

URL = "https://mcp.deepwiki.com/mcp"
_REPO = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\s*(?::\s*(.*))?$", re.S)

TOOL = ToolSpec(
    id="mcp_deepwiki",
    name="MCP DeepWiki",
    type="mcp",
    icon="📚",
    group="mcp_servers",
    category="Developer Tools",
    description="Ask questions about any public GitHub repo and read its generated wiki. Input: 'owner/repo: question'. No key needed.",
    default_config={
        "transport": "http",
        "url": URL,
        "repo_name": "",
    },
    order=360,
    is_new=True,
)

DEFAULT_TOOL = "ask_wiki_question"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    if config.get("tool_name"):
        return URL, {}, config["tool_name"], config.get("arguments") or {}
    text = input_text.strip()
    repo = str(config.get("repo_name") or "").strip()
    question = text
    if not repo:
        m = _REPO.match(text)
        repo, question = (m.group(1), (m.group(2) or "").strip()) if m else ("", text)
    if repo and not question:
        return URL, {}, "read_wiki_structure", {"repoName": repo}
    return URL, {}, defaults["default_tool"], {"repoName": repo, "question": question}


run = remote_server("MCP DeepWiki", DEFAULT_TOOL, prepare)
