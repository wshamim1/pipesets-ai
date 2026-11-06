"""GitLab API — built-in tool `gitlab_api` (REST v4; gitlab.com or a self-managed instance)."""

import re
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[GitLab]"
ACTIONS = ("project_info", "issues", "merge_requests", "pipelines", "commits")

TOOL = ToolSpec(
    id="gitlab_api",
    name="GitLab API",
    icon="🦊",
    category="APIs & Integrations",
    description="Fetch project info, open issues, merge requests, pipelines or commits from GitLab (gitlab.com or self-managed). Input is group/project or a GitLab URL.",
    default_config={"base_url": "https://gitlab.com", "token": "", "action": "project_info", "max_results": 10},
    order=22,
    selects={"action": Select("Action", (("project_info", "Project info"), ("issues", "Open issues"),
                                         ("merge_requests", "Open merge requests"), ("pipelines", "Recent pipelines"),
                                         ("commits", "Recent commits")))},
    parameters=params({"project": {"type": "string", "description": "group/project (subgroups allowed) or a GitLab URL"}},
                      {"action": enum(list(ACTIONS), "What to fetch")}),
    input_param="project",
)


def _project_path(inp: str, base: str) -> str:
    text = inp.strip().strip("'\"")
    if text.startswith(("http://", "https://")):
        text = urlparse(text).path
    text = text.split("/-/")[0].strip("/")
    return re.sub(r"\.git$", "", text)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    base = (cfg.get("base_url") or "https://gitlab.com").strip().rstrip("/")
    path = _project_path(inp, base)
    if "/" not in path:
        return f"{LABEL} Provide a project as group/project or a GitLab URL."
    action = cfg.get("action") or "project_info"
    if action not in ACTIONS:
        return f"{LABEL} Action is one of {', '.join(ACTIONS)} — got '{action}'."
    token = (cfg.get("token") or "").strip()
    headers = {"PRIVATE-TOKEN": token} if token else {}
    limit = max(1, min(int(cfg.get("max_results") or 10), 50))
    api = f"{base}/api/v4/projects/{quote(path, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            if action == "project_info":
                resp = await client.get(api)
            elif action in ("issues", "merge_requests"):
                resp = await client.get(f"{api}/{action}", params={"state": "opened", "per_page": limit})
            else:
                resp = await client.get(f"{api}/{'pipelines' if action == 'pipelines' else 'repository/commits'}",
                                        params={"per_page": limit})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {base}: {e}"
    if resp.status_code == 401:
        return f"{LABEL} The token is invalid or expired."
    if resp.status_code == 404:
        return f"{LABEL} Project {path} not found (private projects need a token with read_api)."
    if resp.status_code != 200:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    data = resp.json()

    if action == "project_info":
        return (f"{LABEL} {data.get('path_with_namespace', path)}\n"
                f"  Description : {data.get('description') or 'N/A'}\n"
                f"  Stars       : {data.get('star_count', 0)}\n"
                f"  Forks       : {data.get('forks_count', 0)}\n"
                f"  Open issues : {data.get('open_issues_count', 'N/A')}\n"
                f"  Default br. : {data.get('default_branch', 'main')}\n"
                f"  Last active : {(data.get('last_activity_at') or '')[:10]}\n"
                f"  URL         : {data.get('web_url', '')}")
    if not data:
        return f"{LABEL} No {action.replace('_', ' ')} for {path}."
    lines = [f"{LABEL} {action.replace('_', ' ').title()}: {path}"]
    for item in data:
        if action == "issues":
            lines.append(f"  #{item['iid']} {item.get('title', '')} — {(item.get('author') or {}).get('username', '?')}")
        elif action == "merge_requests":
            lines.append(f"  !{item['iid']} {item.get('title', '')} ({item.get('source_branch')} → {item.get('target_branch')})"
                         f" — {(item.get('author') or {}).get('username', '?')}")
        elif action == "pipelines":
            lines.append(f"  #{item['id']} {item.get('status', '?')} on {item.get('ref', '?')} · {(item.get('created_at') or '')[:16]}")
        else:
            lines.append(f"  {item.get('short_id', '')} {item.get('author_name', '?')}: {item.get('title', '')}")
    return "\n".join(lines)
