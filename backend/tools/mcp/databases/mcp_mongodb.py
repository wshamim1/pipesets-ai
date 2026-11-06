"""MCP MongoDB — built-in MCP server `mcp_mongodb` (mongodb-mcp-server, by MongoDB; version pinned).

The connection string is a secret, so it goes in ``MDB_MCP_CONNECTION_STRING`` rather than on the
command line. With a database and collection configured the default tool is ``find``; otherwise
the server lists databases or collections. Read-only unless you turn it off.
"""

import json
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_mongodb",
    name="MCP MongoDB",
    type="mcp",
    icon="🍃",
    group="mcp_servers",
    category="Databases & Data",
    description="MongoDB databases and collections: find documents, list collections, aggregate. Read-only by default.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "mongodb-mcp-server@3.2.2"],
        "mdb_connection_string": "mongodb://localhost:27017",
        "database": "",
        "collection": "",
        "read_only": "true",
    },
    required=("mdb_connection_string",),
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=350,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "mongodb-mcp-server@3.2.2"]
DEFAULT_TOOL = "list-databases"


def _json_object(text: str) -> Dict[str, Any]:
    """A JSON object from the node input, or an empty filter."""
    try:
        value = json.loads(text) if text.strip() else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["MDB_MCP_CONNECTION_STRING"] = config_value(config, "mdb_connection_string")
    if str(config.get("read_only", "true")).lower() != "false":
        args = [*args, "--readOnly"]

    database = config_value(config, "database")
    collection = config_value(config, "collection")
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments")
    if call_args is None:
        if database and collection:
            tool_name = config.get("tool_name") or "find"
            call_args = {"database": database, "collection": collection, "filter": _json_object(input_text)}
        elif database:
            tool_name = config.get("tool_name") or "list-collections"
            call_args = {"database": database}
        else:
            call_args = {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
