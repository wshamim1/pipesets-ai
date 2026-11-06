"""MCP Stripe — built-in MCP server `mcp_stripe` (@stripe/mcp).

Stripe operations and documentation search through the Stripe MCP server (read actions like
``search_docs`` plus the create_* tools the account enables). Launched over stdio with npx; auth
is a secret key (``sk_test_…`` / ``sk_live_…`` — secret:// ref) passed as ``STRIPE_SECRET_KEY``.
"""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_stripe",
    name="MCP Stripe",
    type="mcp",
    icon="🧾",
    group="mcp_servers",
    category="Developer Tools",
    description=("Stripe via the Stripe MCP server — search the docs and call the enabled tools "
                 "(customers, products, prices, payment links, invoices). Needs a secret key."),
    default_config={"transport": "stdio", "command": "npx", "args": ["-y", "@stripe/mcp@0.3.3"],
                    "stripe_secret_key": ""},
    order=270,
)

COMMAND = "npx"
ARGS = ["-y", "@stripe/mcp@0.3.3"]
DEFAULT_TOOL = "search_docs"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    key = (config.get("stripe_secret_key") or config.get("STRIPE_SECRET_KEY")
           or os.environ.get("STRIPE_SECRET_KEY", ""))
    if key:
        env_vars["STRIPE_SECRET_KEY"] = key
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
