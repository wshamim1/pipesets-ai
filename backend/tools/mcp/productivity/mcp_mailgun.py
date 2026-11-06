"""MCP Mailgun — built-in MCP server `mcp_mailgun` (@mailgun/mcp-server, by Mailgun; version pinned).

Sending and deliverability: send and resend email, domains and their DNS verification, tracking
settings, webhooks, routes, mailing lists, templates, sending metrics and logs, bounces and other
suppressions, IP pools, address validation, inbox-placement and email-preview results. No delete
tools. The API key goes in ``MAILGUN_API_KEY`` and the region in ``MAILGUN_API_REGION``, never on the
command line. ``tags`` narrows the tools to one Mailgun product (``--tags``).

No input lists the account's domains; a sending domain as input reads its last day of metrics.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_mailgun",
    name="MCP Mailgun",
    type="mcp",
    icon="📮",
    group="mcp_servers",
    category="Productivity",
    description="Mailgun email: send messages, check domains and DNS, sending metrics, logs, bounces and suppressions, templates and mailing lists, and address validation.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@mailgun/mcp-server@2.1.3"],
        "mailgun_api_key": "",
        "region": "us",
        "tags": "all",
    },
    required=("mailgun_api_key",),
    selects={
        "region": Select("Region", (("us", "US"), ("eu", "EU"))),
        "tags": Select("Tools", (("all", "All"), ("send", "Sending, domains and analytics"), ("validate", "Address validation"),
                                 ("optimize", "Inbox placement"), ("inspect", "Email previews"))),
    },
    order=460,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@mailgun/mcp-server@2.1.3"]
DEFAULT_TOOL = "get-v4-domains"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars and ``--tags``, and the MCP tool to call with its arguments."""
    env_vars["MAILGUN_API_KEY"] = config_value(config, "mailgun_api_key")
    env_vars["MAILGUN_API_REGION"] = "eu" if str(config.get("region", "us")).lower() == "eu" else "us"
    tags = str(config.get("tags") or "all").lower()
    if tags in ("send", "validate", "optimize", "inspect"):
        args = [*args, "--tags", tags]
    if config.get("tool_name"):
        return args, config["tool_name"], config.get("arguments") or {}
    domain = input_text.strip()
    if domain:
        return args, "get_metrics_summary", {"domain": domain}
    return args, defaults["default_tool"], {}


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
