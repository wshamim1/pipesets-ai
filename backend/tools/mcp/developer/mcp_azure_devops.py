"""MCP Azure DevOps — built-in MCP server `mcp_azure_devops` (@azure-devops/mcp, by Microsoft; version pinned).

Projects, work items and queries, repos and pull requests, builds and pipelines, wikis and code
search. It runs with ``--authentication pat``: the personal access token goes base64-encoded in
``PERSONAL_ACCESS_TOKEN`` (the server uses it as the Basic credential), never on the command line;
only the organization name is an argument. ``domains`` limits which tool groups load. The default
tool lists the organization's projects.
"""

import base64
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_azure_devops",
    name="MCP Azure DevOps",
    type="mcp",
    icon="🔷",
    group="mcp_servers",
    category="Developer Tools",
    description="Azure DevOps work items, repos and pull requests, pipelines, wikis and code search, with a personal access token.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@azure-devops/mcp@2.10.0"],
        "organization": "",
        "azure_devops_pat": "",
        "domains": "all",
    },
    required=("organization", "azure_devops_pat"),
    selects={"domains": Select("Tool groups", (
        ("all", "All"), ("core work work-items", "Projects and work items"),
        ("core repositories", "Projects and repos"), ("core pipelines", "Projects and pipelines"),
        ("core wiki search", "Projects, wikis and search"),
    ))},
    order=390,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@azure-devops/mcp@2.10.0"]
DEFAULT_TOOL = "core_list_projects"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → launch args / env vars, and the MCP tool to call with its arguments."""
    org = config_value(config, "organization")
    pat = config_value(config, "azure_devops_pat")
    env_vars["PERSONAL_ACCESS_TOKEN"] = base64.b64encode(f"pipesets:{pat}".encode()).decode() if pat else ""
    domains = (config_value(config, "domains") or "all").split()
    args = [*args, org, "--authentication", "pat", "--domains", *domains]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
