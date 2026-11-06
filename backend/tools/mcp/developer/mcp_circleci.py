"""MCP CircleCI — built-in MCP server `mcp_circleci` (@circleci/mcp-server-circleci, by CircleCI;
version pinned).

Pipeline status, build failure logs, flaky tests, test results and artifacts, plus re-running
workflows. The token goes in ``CIRCLECI_TOKEN``, never on the command line; ``circleci_base_url``
is for CircleCI server installs. The default tool lists the projects the token's user follows.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_circleci",
    name="MCP CircleCI",
    type="mcp",
    icon="⭕",
    group="mcp_servers",
    category="DevOps & Observability",
    description="CircleCI pipeline status, build failure logs, flaky tests and test results; re-run workflows.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@circleci/mcp-server-circleci@0.20.0"],
        "circleci_token": "",
        "circleci_base_url": "",
    },
    required=("circleci_token",),
    order=370,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@circleci/mcp-server-circleci@0.20.0"]
DEFAULT_TOOL = "list_followed_projects"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["CIRCLECI_TOKEN"] = config_value(config, "circleci_token")
    base_url = config_value(config, "circleci_base_url")
    if base_url:
        env_vars["CIRCLECI_BASE_URL"] = base_url
    env_vars["DISABLE_TELEMETRY"] = "true"
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
