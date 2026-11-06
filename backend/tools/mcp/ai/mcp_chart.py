"""MCP Chart — built-in MCP server `mcp_chart` (@antv/mcp-server-chart, by AntV; version pinned).

25+ chart and diagram tools (line, bar, pie, scatter, sankey, treemap, funnel, mind maps, flow and
org charts …) that return an image URL. No key needed, but the server sends the chart data to
AntV's public rendering service (antv-studio.alipay.com), so keep confidential data out of it.

The input is the chart data as JSON: a list of rows goes to ``chart_type`` (default line) as its
``data``; an object is passed as the tool's arguments.
"""

import json
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import stdio_server

CHART_TYPES = ("line", "area", "bar", "column", "pie", "scatter", "histogram", "radar", "funnel", "treemap", "sankey")

TOOL = ToolSpec(
    id="mcp_chart",
    name="MCP Chart (AntV)",
    type="mcp",
    icon="📊",
    group="mcp_servers",
    category="AI & Memory",
    description="Generate line, bar, pie, sankey and 20+ other charts and diagrams as images. Data is rendered by AntV's public service.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@antv/mcp-server-chart@0.9.10"],
        "chart_type": "line",
    },
    selects={"chart_type": Select("Chart type (JSON-list input)", tuple((t, t.title()) for t in CHART_TYPES))},
    order=350,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@antv/mcp-server-chart@0.9.10"]
DEFAULT_TOOL = "generate_line_chart"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → the MCP tool to call with its arguments."""
    chart = str(config.get("chart_type") or "line").strip().lower()
    tool_name = config.get("tool_name") or f"generate_{chart}_chart"
    if config.get("arguments"):
        return args, tool_name, config["arguments"]
    try:
        data = json.loads(input_text) if input_text.strip() else []
    except json.JSONDecodeError:
        data = []
    call_args = data if isinstance(data, dict) else {"data": data if isinstance(data, list) else []}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
