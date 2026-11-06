"""Google Tasks — built-in tool `google_tasks` (Google Tasks REST API v1, read-only).

Actions: ``lists`` (the task lists) and ``list`` (tasks in one list: title, status, due date,
notes). Auth is an OAuth access token with the https://www.googleapis.com/auth/tasks.readonly
scope (+ refresh token / client id / secret when present) in the node config, resolved from a
``secret://`` ref.
"""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, enum, params
from tools.productivity._google_auth import call as google_call
from tools.productivity._google_auth import http_error

LABEL = "[Google Tasks]"
TASKS_API = "https://tasks.googleapis.com/tasks/v1"


TOOL = ToolSpec(
    id="google_tasks",
    name="Google Tasks",
    icon="✅",
    category="Productivity",
    description="Reads the user's Google Tasks: the task lists and the tasks in one (title, status, due date, notes).",
    default_config={"access_token": "", "tasklist_id": "@default", "max_results": 25, "show_completed": True},
    order=40,
    required=("access_token",),
    parameters=params(
        {"action": enum(["lists", "list"], "lists = the task lists, list = the tasks in one list")},
        {
            "tasklist_id": {"type": "string", "description": "Task list id, or '@default' (list)"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Most tasks to return (list)"},
            "show_completed": {"type": "boolean", "description": "Include completed tasks (default true) (list)"},
        },
    ),
    input_param="action",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide an OAuth access token (or a secret:// ref) "
                "with the tasks.readonly scope.")
    action = str(inp or "").strip().lower()
    if action not in ("lists", "list"):
        return f'{LABEL} Action is "lists" or "list" — got "{inp}".'

    if action == "lists":
        resp = await google_call(cfg, "GET", f"{TASKS_API}/users/@me/lists", query={"maxResults": 100})
        if resp.status_code != 200:
            return http_error(LABEL, resp)
        items = resp.json().get("items") or []
        if not items:
            return f"{LABEL} No task lists on this account."
        lines = [f"{LABEL} {len(items)} task list(s)", ""]
        for l in items:
            done = int(l.get("numCompletedTasks") or 0)
            todo = int(l.get("numTasks") or done) - done
            lines.append(f'  {l.get("title") or "(untitled)"}  id={l.get("id")}  ({todo} open, {done} done)')
        return "\n".join(lines) + "\n\nTo see one list's tasks: google_tasks list with its tasklist_id."

    tasklist_id = str(cfg.get("tasklist_id") or "@default").strip() or "@default"
    max_results = min(max(int(cfg.get("max_results", 25) or 25), 1), 100)
    show_completed = str(cfg.get("show_completed", True)).lower() != "false"
    resp = await google_call(cfg, "GET", f"{TASKS_API}/lists/{tasklist_id}/tasks", query={
        "maxResults": max_results,
        "showCompleted": "true" if show_completed else "false",
        "showHidden": "false"})
    if resp.status_code != 200:
        return http_error(LABEL, resp)
    tasks = resp.json().get("items") or []
    if not tasks:
        return f"{LABEL} No tasks in this list."
    lines = [f"{LABEL} {len(tasks)} task(s)", ""]
    for t in tasks:
        mark = "x" if t.get("status") == "completed" else " "
        line = f"  [{mark}] {t.get('title') or '(no title)'}"
        if t.get("due"):
            line += f"  due {str(t['due'])[:10]}"
        lines.append(line)
        notes = str(t.get("notes") or "").strip()
        if notes:
            lines.append(f"      {notes[:300]}")
    return "\n".join(lines)
