"""MCP AWS Knowledge Base — built-in MCP server `mcp_aws_kb` (awslabs.bedrock-kb-retrieval-mcp-server, by AWS;
version pinned). Replaces the deprecated reference server; its tools are ListKnowledgeBases,
QueryKnowledgeBases and AgenticQueryKnowledgeBases."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_aws_kb",
    name="MCP AWS Knowledge Base",
    type="mcp",
    icon="☁️",
    group="mcp_servers",
    category="AI & Memory",
    description="List and query Amazon Bedrock Knowledge Bases (retrieval, optional reranking).",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["awslabs.bedrock-kb-retrieval-mcp-server@1.1.2"],
        "env_vars": {"AWS_ACCESS_KEY_ID": "", "AWS_SECRET_ACCESS_KEY": "", "AWS_REGION": "us-east-1", "BEDROCK_KB_ID": ""},
    },
    order=90,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["awslabs.bedrock-kb-retrieval-mcp-server@1.1.2"]
DEFAULT_TOOL = "QueryKnowledgeBases"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "AWS_PROFILE"):
        val = config.get(key.lower()) or config.get(key) or os.environ.get(key, "")
        if val:
            env_vars[key] = val
    env_vars["FASTMCP_LOG_LEVEL"] = "ERROR"
    kb_id = config.get("bedrock_kb_id") or config.get("BEDROCK_KB_ID") or os.environ.get("BEDROCK_KB_ID", "")
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip(), "knowledge_base_id": kb_id}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
