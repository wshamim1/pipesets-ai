"""Asana — built-in tool `asana` (REST API 1.0, PAT).

Actions: ``tasks`` (search a project's incomplete tasks by name substring, or empty for the most
recent), ``create`` (a task titled by the input, attach it to the project, optional notes) and
``complete`` (the task gid in the input). Auth is a Personal Access Token in the node config.
"""

import json
import re
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Asana]"
API = "https://app.asana.com/api/1.0"


def _error(resp: httpx.Response) -> str:
    try:
        message = (resp.json().get("errors") or [{}])[0].get("message", "")[:300]
    except Exception:
        message = resp.text[:300]
    if resp.status_code in (401, 403):
        return f"{LABEL} The access_token is invalid or lacks this permission. {message}"
    if resp.status_code == 404:
        return f"{LABEL} Not found — check the ids. {message}"
    return f"{LABEL} HTTP {resp.status_code}: {message}"


def _line(t: Dict[str, Any]) -> str:
    done = "done" if t.get("completed") else "open"
    due = f" · due {t.get('due_on')}" if t.get("due_on") else ""
    who = ((t.get("assignee") or {}).get("name")) or "unassigned"
    return f"- {t.get('gid')} · {t.get('name')} [{done}] · {who}{due}"


def _notes(text: str) -> Optional[str]:
    """Lines after the first become the task notes (the linear 'create: …' convention)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[1:]).strip() or None


def _main_text(text: str) -> str:
    return (text.splitlines() or [""])[0].strip()


TOOL = ToolSpec(
    id="asana",
    name="Asana",
    icon="✅",
    category="Business Apps",
    description=("Reads and writes Asana tasks: search the tasks of a project, create one (the "
                 "first line is the title, the rest become notes) or complete one by gid. "
                 "Personal Access Token in the node config."),
    default_config={"access_token": "", "action": "tasks", "project_id": "", "max_results": 25},
    order=100,
    required=("access_token",),
    selects={"action": Select("Action", (("tasks", "Search / list a project's tasks"),
                                         ("create", "Create a task"), ("complete", "Complete a task")))},
    parameters=params(
        {"text": {"type": "string", "description": "tasks = name substring (empty = newest), create = title, complete = task gid"}},
        {
            "action": enum(["tasks", "create", "complete"], "What to do"),
            "project_id": {"type": "string", "description": "The project gid to work in (tasks / create)"},
            "notes": {"type": "string", "description": "Task notes (create); otherwise lines 2+ become notes"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Most tasks to fetch"},
        },
    ),
    input_param="text",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return f"{LABEL} access_token is required in config (a Personal Access Token)."
    action = (cfg.get("action") or "tasks").strip().lower()
    if action not in ("tasks", "create", "complete"):
        return f'{LABEL} Action is "tasks", "create" or "complete" — got "{action}".'
    text = str(inp or "").strip()
    project = (cfg.get("project_id") or "").strip()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=25.0, headers=headers) as client:
            if action == "complete":
                if not text:
                    return f"{LABEL} complete needs the task gid to mark done."
                resp = await client.put(f"{API}/tasks/{text}", json={"data": {"completed": True}})
                if resp.status_code != 200:
                    return _error(resp)
                task = (resp.json().get("data") or {})
                return f"{LABEL} Completed {text}: {task.get('name') or ''}".rstrip()

            if action == "create":
                title = _main_text(text)
                if not title:
                    return f'{LABEL} create needs a title — the first line of the input is the task name.'
                if not project:
                    return f"{LABEL} create needs project_id in config (the gid of the project to add the task to)."
                notes = (cfg.get("notes") or "").strip() or _notes(text) or ""
                body = {"data": {"name": title, "projects": [project]}}
                if notes:
                    body["data"]["notes"] = notes
                resp = await client.post(f"{API}/tasks", json=body)
                if resp.status_code != 200:
                    return _error(resp)
                task = resp.json().get("data") or {}
                return f"{LABEL} Created task {task.get('gid')}: {title}"

            # search / list a project's tasks
            if not project:
                return f"{LABEL} project_id is required in config for searching tasks."
            limit = min(max(int(cfg.get("max_results", 25) or 25), 1), 100)
            resp = await client.get(f"{API}/projects/{project}/tasks", params={
                "limit": limit, "completed_since": "now",
                "sort": "modified_date:desc", "opt_fields": "name,due_on,completed,assignee.name"})
            if resp.status_code != 200:
                return _error(resp)
            tasks = resp.json().get("data") or []
            if text:
                tasks = [t for t in tasks if text.casefold() in str(t.get("name") or "").casefold()]
            if not tasks:
                return (f'{LABEL} No open tasks match "{text}".' if text
                        else f"{LABEL} The project has no open tasks.")
            return f"{LABEL} {len(tasks)} open task(s) in the project" + \
                (f' matching "{text}"' if text else "") + "\n\n" + "\n".join(_line(t) for t in tasks)
    except Exception as e:
        return f"{LABEL} Error: {e}"
