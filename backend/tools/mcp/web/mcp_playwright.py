"""MCP Playwright — built-in MCP server `mcp_playwright` (@playwright/mcp).

Browser automation: navigate, click, fill forms, screenshot, read back a page snapshot. Launched
over stdio with npx; the browser can be set (default Chrome) and headless configured. The bare
input becomes the URL to navigate; stored tools (``mcp_tools``) call each browser action directly.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_playwright",
    name="MCP Playwright",
    type="mcp",
    icon="🎭",
    group="mcp_servers",
    category="Web & Browser",
    description=("Browser automation via the Playwright MCP server — navigate, click, type, take "
                 "screenshots and read a page's accessibility snapshot."),
    default_config={"transport": "stdio", "command": "npx", "args": ["-y", "@playwright/mcp@0.0.84"],
                    "browser": "chrome", "headless": "off"},
    order=70,
    selects={"browser": Select("Browser", (("chrome", "Chrome"), ("firefox", "Firefox"),
                                           ("webkit", "WebKit (Safari)"), ("msedge", "Edge"))),
             "headless": Select("Headless", (("off", "No — open a real browser window"),
                                             ("on", "Yes — no window"),),)},
)

COMMAND = "npx"
ARGS = ["-y", "@playwright/mcp@0.0.84"]
DEFAULT_TOOL = "browser_navigate"
BROWSERS = ("chrome", "firefox", "webkit", "msedge")


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    args = list(args)
    browser = (config.get("browser") or "").strip().lower()
    if browser in BROWSERS:
        args += ["--browser", browser]
    if str(config.get("headless") or "off").lower() in ("on", "true", "yes"):
        args.append("--headless")
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"url": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
