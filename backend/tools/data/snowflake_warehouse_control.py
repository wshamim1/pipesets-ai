"""Snowflake warehouse control — built-in tool `snowflake_warehouse_control`."""

from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params
from tools.data import _snowflake as sf

LABEL = "Snowflake Warehouse Control"
ACTIONS = ("resume", "suspend")

TOOL = ToolSpec(
    id="snowflake_warehouse_control",
    name=LABEL,
    icon="🎛️",
    category="Data & Files",
    description="Resumes or suspends a Snowflake virtual warehouse (suspending stops credit usage).",
    default_config={**sf.DEFAULT_CONFIG, "action": "resume"},
    required=sf.REQUIRED,
    selects={"token_type": sf.TOKEN_SELECT, "action": Select("Action", [("resume", "Resume"), ("suspend", "Suspend")])},
    order=380,
    parameters=params(
        {"warehouse_name": {"type": "string", "description": "Warehouse name"}},
        {"action": enum(ACTIONS, "Resume or suspend the warehouse")},
    ),
    input_param="warehouse_name",
    config_args=("action",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    problem = sf.credentials_missing(LABEL, cfg) or sf.missing(LABEL, warehouse_name=inp)
    if problem:
        return problem
    parts = sf.name_parts(inp, 1)
    if not parts:
        return f"[{LABEL}] '{inp}' isn't a warehouse name"
    action = str(cfg.get("action") or "resume").lower()
    if action not in ACTIONS:
        return f"[{LABEL}] Unknown action '{action}'. Use one of: {', '.join(ACTIONS)}"
    data, error = await sf.request(LABEL, cfg, "POST", f"/api/v2/warehouses/{sf.url_part(parts[0])}:{action}")
    if error:
        return error
    return sf.report(LABEL, {"warehouse": parts[0], "action": action,
                             "status": (data or {}).get("status") if isinstance(data, dict) else data})
