"""MCP Supabase — built-in MCP server `mcp_supabase` (@supabase/mcp-server-supabase, by Supabase; version pinned)."""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_supabase",
    name="MCP Supabase",
    type="mcp",
    icon="⚡",
    group="mcp_servers",
    category="Databases & Data",
    description="Supabase projects: tables, SQL, migrations, logs and docs. Read-only unless you turn it off.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@supabase/mcp-server-supabase@0.15.0"],
        "supabase_access_token": "",
        "project_ref": "",
        "read_only": "true",
    },
    required=("supabase_access_token",),
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=300,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@supabase/mcp-server-supabase@0.15.0"]
DEFAULT_TOOL = "list_projects"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["SUPABASE_ACCESS_TOKEN"] = config_value(config, "supabase_access_token")
    if str(config.get("read_only", "true")).lower() != "false":
        args = [*args, "--read-only"]
    project = config_value(config, "project_ref")
    if project:
        args = [*args, f"--project-ref={project}"]
    # Scoped to one project, the account-level tools (list_projects) aren't offered
    tool_name = config.get("tool_name") or ("list_tables" if project else defaults["default_tool"])
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
