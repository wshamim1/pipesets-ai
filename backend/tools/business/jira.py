"""Jira Cloud — built-in tool `jira`."""

import re
from typing import Any, Dict, Optional

from tools.base import MAX_RESULTS, Select, ToolSpec, params
from tools.business._atlassian import adf_to_text, atlassian_client, http_error, text_to_adf

TOOL = ToolSpec(
    id="jira",
    name="Jira",
    icon="🎫",
    category="Business Apps",
    description="Search Jira issues (text or JQL), read an issue with its comments, or create one. Input: an issue key like 'OPS-12', search text / JQL, or 'create: Summary' + description.",
    default_config={"base_url": "", "email": "", "api_token": "", "action": "auto", "project_key": "",
                    "issue_type": "Task", "max_results": 10},
    order=10,
    required=("base_url", "email", "api_token"),
    selects={
        "action": Select("Action", (("auto", "Auto (key → read, 'create:' → create, else search)"),
                                    ("search", "Search"), ("get", "Read issue"), ("create", "Create issue"))),
    },
    parameters=params(
        {
            "request": {"type": "string", "description": "An issue key like OPS-12, search text or JQL, or 'create: Summary' + a description on the next lines"},
        },
        {"max_results": MAX_RESULTS},
    ),
    input_param="request",
)

_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
_FIELDS = "summary,status,assignee,priority,updated,issuetype"


def _line(base: str, issue: Dict[str, Any]) -> str:
    f = issue.get("fields", {})
    who = (f.get("assignee") or {}).get("displayName", "unassigned")
    return (f"{issue.get('key')} [{(f.get('status') or {}).get('name', '?')}] {f.get('summary', '')}\n"
            f"   {(f.get('issuetype') or {}).get('name', '')} · {(f.get('priority') or {}).get('name', 'no priority')} · "
            f"{who} · updated {(f.get('updated') or '')[:10]}\n   {base}/browse/{issue.get('key')}")


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    client, base, err = atlassian_client(cfg, "Jira")
    if err:
        return err
    action = cfg.get("action", "auto")
    text = inp.strip()
    if action == "auto":
        if text.lower().startswith("create:"):
            action, text = "create", text[len("create:"):].strip()
        elif _KEY.match(text.upper()):
            action = "get"
        else:
            action = "search"
    if not text:
        return "[Jira] Provide an issue key, search text or the issue to create."

    async with client:
        if action == "get":
            key = text.upper()
            resp = await client.get(f"{base}/rest/api/3/issue/{key}", params={
                "fields": _FIELDS + ",reporter,created,description,comment"})
            if resp.status_code != 200:
                return http_error("Jira", resp)
            issue = resp.json()
            f = issue.get("fields", {})
            desc = adf_to_text(f.get("description")).strip() or "(no description)"
            comments = (f.get("comment") or {}).get("comments", [])[-3:]
            out = [f"[Jira] {_line(base, issue)}", f"   reporter {(f.get('reporter') or {}).get('displayName', '?')} · "
                   f"created {(f.get('created') or '')[:10]}", "", desc[:4000]]
            if comments:
                out.append(f"\nLatest comments ({len(comments)} of {(f.get('comment') or {}).get('total', len(comments))}):")
                for c in comments:
                    out.append(f"- {(c.get('author') or {}).get('displayName', '?')} ({(c.get('created') or '')[:10]}): "
                               f"{adf_to_text(c.get('body')).strip()[:500]}")
            return "\n".join(out)

        if action == "create":
            project = (cfg.get("project_key") or "").strip()
            if not project:
                return "[Jira] Set project_key in config to create issues."
            summary, _, description = text.partition("\n")
            resp = await client.post(f"{base}/rest/api/3/issue", json={"fields": {
                "project": {"key": project}, "summary": summary.strip()[:255],
                "issuetype": {"name": cfg.get("issue_type") or "Task"},
                "description": text_to_adf(description.strip() or summary.strip()),
            }})
            if resp.status_code not in (200, 201):
                return http_error("Jira", resp)
            key = resp.json().get("key")
            return f"[Jira] Created {key}: {summary.strip()}\n   {base}/browse/{key}"

        # search: JQL as-is, or a text search (optionally within the configured project)
        looks_like_jql = bool(re.search(r"(\b(AND|OR|ORDER BY)\b|[=~]|!=)", text))
        if looks_like_jql:
            jql = text
        else:
            jql = 'text ~ "' + text.replace('"', '\\"') + '"'
            if cfg.get("project_key"):
                jql += f' AND project = "{cfg["project_key"]}"'
            jql += " ORDER BY updated DESC"
        resp = await client.get(f"{base}/rest/api/3/search/jql", params={
            "jql": jql, "maxResults": int(cfg.get("max_results", 10)), "fields": _FIELDS})
        if resp.status_code != 200:
            return http_error("Jira", resp)
        issues = resp.json().get("issues", [])
        if not issues:
            return f"[Jira] No issues match: {jql}"
        return f"[Jira: {jql}]\n\n" + "\n".join(_line(base, i) for i in issues)
