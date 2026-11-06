"""MCP Salesforce — built-in MCP server `mcp_salesforce` (@salesforce/mcp, by Salesforce; version
pinned). The org must already be authorized on this machine with the Salesforce CLI
(``sf org login web``); the server has no static credentials of its own.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_salesforce",
    name="MCP Salesforce",
    type="mcp",
    icon="☁️",
    group="mcp_servers",
    category="Productivity",
    description="Query Salesforce with SOQL and inspect org metadata. Authorize the org first with `sf org login web`.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@salesforce/mcp@0.30.15"],
        "salesforce_orgs": "DEFAULT_TARGET_ORG",
        "salesforce_toolsets": "orgs,data",
        "salesforce_username": "",
    },
    required=("salesforce_orgs",),
    selects={"salesforce_toolsets": Select("Toolsets", [
        ("orgs,data", "Orgs + data"),
        ("orgs", "Orgs only"),
        ("all", "All toolsets"),
    ])},
    order=410,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@salesforce/mcp@0.30.15"]
DEFAULT_TOOL = "run_soql_query"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    orgs = config_value(config, "salesforce_orgs", "DEFAULT_TARGET_ORG")
    toolsets = config_value(config, "salesforce_toolsets", "orgs,data")
    args = [*args, "--orgs", orgs, "--toolsets", toolsets]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments")
    if call_args is None:
        call_args = {"query": input_text.strip()}
        username = config_value(config, "salesforce_username")
        if username:
            call_args["usernameOrAlias"] = username
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
