"""ClickUp — built-in tool `clickup` (ClickUp API v2 with a personal API token).

Actions: ``list`` (open tasks in the configured list, filtered by the input text when given),
``read`` (one task by id, with its description and latest comments) and ``create`` (a task in the
configured list: the first line is its name, the rest its description). ``auto`` reads a task id
(#86abc123 or 86abc123), creates on "create: …", and lists otherwise.
"""

import re
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[ClickUp]"
API = "https://api.clickup.com/api/v2"
_TASK_ID = re.compile(r"^#?([a-z0-9]{6,12})$")

TOOL = ToolSpec(
    id="clickup",
    name="ClickUp",
    icon="☑️",
    category="Business Apps",
    description="Lists open ClickUp tasks in a list, reads a task with its comments, or creates a task. Input: filter text, a task id like #86abc123, or 'create: Name' + description.",
    default_config={"api_token": "", "list_id": "", "action": "auto", "max_results": 20},
    order=105,
    required=("api_token",),
    selects={"action": Select("Action", (("auto", "Auto (#id → read, 'create:' → create, else list)"),
                                         ("list", "List tasks"), ("read", "Read task"), ("create", "Create task")))},
    parameters=params(
        {"request": {"type": "string", "description": "Filter text, a task id (#86abc123), or 'create: Name' + the description on the next lines"}},
        {"action": enum(["auto", "list", "read", "create"], "What to do (auto works it out from the request)")},
    ),
    input_param="request",
)


def _task_line(t: Dict[str, Any]) -> str:
    assignees = ", ".join(a.get("username") or a.get("email", "") for a in t.get("assignees") or [])
    bits = [(t.get("status") or {}).get("status"), (t.get("priority") or {}).get("priority"), assignees or None]
    return f"- #{t.get('id')} {t.get('name', '')}" + "".join(f" · {b}" for b in bits if b) + f"\n  {t.get('url', '')}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("api_token") or "").strip()
    if not token:
        return f"{LABEL} api_token (Settings → Apps → API Token, starts with pk_) is required in config."
    text = inp.strip()
    action = (cfg.get("action") or "auto").strip().lower()
    if action == "auto":
        if text.lower().startswith("create:"):
            action, text = "create", text[len("create:"):].strip()
        elif _TASK_ID.match(text.lower()) and any(c.isdigit() for c in text):
            action = "read"
        else:
            action = "list"
    elif action == "create" and text.lower().startswith("create:"):
        text = text[len("create:"):].strip()
    if action not in ("list", "read", "create"):
        return f'{LABEL} Action is "auto", "list", "read" or "create" — got "{action}".'
    list_id = str(cfg.get("list_id") or "").strip()
    if action in ("list", "create") and not list_id:
        return f"{LABEL} Set list_id (the number in the list's URL) to {action} tasks."

    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"Authorization": token}) as client:
            if action == "read":
                task_id = text.lstrip("#")
                resp = await client.get(f"{API}/task/{task_id}")
                if resp.status_code == 200:
                    t = resp.json()
                    comments = await client.get(f"{API}/task/{task_id}/comment")
                    out = [f"{LABEL} #{t.get('id')}: {t.get('name', '')}", t.get("url", ""),
                           f"Status: {(t.get('status') or {}).get('status', '—')}"
                           f" · Priority: {(t.get('priority') or {}).get('priority') or '—'}"
                           f" · List: {(t.get('list') or {}).get('name', '')}",
                           "", (t.get("text_content") or t.get("description") or "(no description)")[:6000]]
                    items = (comments.json().get("comments") or [])[:10] if comments.status_code == 200 else []
                    if items:
                        out += ["", f"Comments ({len(items)}):"]
                        out += [f"- {(c.get('user') or {}).get('username', '?')}: {(c.get('comment_text') or '')[:800]}"
                                for c in items]
                    return "\n".join(out)
            elif action == "create":
                name, _, desc = text.partition("\n")
                if not name.strip():
                    return f"{LABEL} Provide the task name."
                resp = await client.post(f"{API}/list/{list_id}/task",
                                         json={"name": name.strip(), **({"description": desc.strip()} if desc.strip() else {})})
                if resp.status_code == 200:
                    t = resp.json()
                    return f"{LABEL} Created #{t.get('id')}: {t.get('name')}\n{t.get('url', '')}"
            else:
                resp = await client.get(f"{API}/list/{list_id}/task", params={"archived": "false", "subtasks": "true"})
                if resp.status_code == 200:
                    tasks = resp.json().get("tasks") or []
                    if text:
                        needle = text.lower()
                        tasks = [t for t in tasks if needle in (t.get("name") or "").lower()
                                 or needle in (t.get("text_content") or "").lower()]
                    limit = max(1, min(int(cfg.get("max_results") or 20), 100))
                    if not tasks:
                        return f"{LABEL} No open tasks" + (f" matching '{text}'." if text else " in this list.")
                    return (f"{LABEL} {len(tasks)} task(s)" + (f" matching '{text}'" if text else "") + "\n\n"
                            + "\n".join(_task_line(t) for t in tasks[:limit]))
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach ClickUp: {e}"
    if resp.status_code == 401:
        return f"{LABEL} The api_token is invalid."
    if resp.status_code == 404:
        return f"{LABEL} Not found — check the task id or list_id."
    try:
        err = resp.json().get("err")
    except ValueError:
        err = None
    return f"{LABEL} HTTP {resp.status_code}: {err or resp.text[:200]}"
