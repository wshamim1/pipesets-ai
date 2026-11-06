"""Snowflake task — built-in tool `snowflake_task`: a task's definition, state and recent runs, or
run / resume / suspend it."""

from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params
from tools.data import _snowflake as sf

LABEL = "Snowflake Task"
ACTIONS = ("status", "execute", "resume", "suspend")

TOOL = ToolSpec(
    id="snowflake_task",
    name=LABEL,
    icon="⏱️",
    category="Data & Files",
    description="Shows a Snowflake task's state, schedule and recent runs, or runs, resumes or suspends it.",
    default_config={**sf.DEFAULT_CONFIG, "action": "status"},
    required=sf.REQUIRED,
    selects={"token_type": sf.TOKEN_SELECT,
             "action": Select("Action", [("status", "Status"), ("execute", "Run now"), ("resume", "Resume"),
                                         ("suspend", "Suspend")])},
    order=395,
    parameters=params(
        {"task_name": {"type": "string", "description": "Fully qualified task name: db.schema.task"}},
        {"action": enum(ACTIONS, "Read the status, or run, resume or suspend the task")},
    ),
    input_param="task_name",
    config_args=("action",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    problem = sf.credentials_missing(LABEL, cfg) or sf.missing(LABEL, task_name=inp)
    if problem:
        return problem
    parts = sf.name_parts(inp, 3)
    if not parts:
        return f"[{LABEL}] Expected db.schema.task, got '{inp}'"
    action = str(cfg.get("action") or "status").lower()
    if action not in ACTIONS:
        return f"[{LABEL}] Unknown action '{action}'. Use one of: {', '.join(ACTIONS)}"
    db, schema, task = parts
    path = f"/api/v2/databases/{sf.url_part(db)}/schemas/{sf.url_part(schema)}/tasks/{sf.url_part(task)}"

    if action != "status":
        _, error = await sf.request(LABEL, cfg, "POST", f"{path}:{action}")
        if error:
            return error
        return sf.report(LABEL, {"task": ".".join(parts), "action": action, "requested": True})

    data, error = await sf.request(LABEL, cfg, "GET", path)
    if error:
        return error
    history, history_error = await sf.statement(
        LABEL, cfg,
        "SELECT name, state, scheduled_time, completed_time, error_message "
        f"FROM TABLE({db}.INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME => {sf.sql_string(task.strip('\"'))}, "
        "RESULT_LIMIT => 5)) ORDER BY scheduled_time DESC", max_rows=5)
    return sf.report(LABEL, {
        "task": ".".join(parts),
        "state": data.get("state"),
        "schedule": data.get("schedule"),
        "warehouse": data.get("warehouse"),
        "predecessors": data.get("predecessors"),
        "definition": data.get("definition"),
        "recent_runs": history if history is not None else history_error,
    })
