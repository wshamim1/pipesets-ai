"""Linear — built-in tool `linear` (Linear GraphQL API with a personal API key).

Actions: ``search`` (issues matching text), ``read`` (one issue by identifier, e.g. ENG-123, with
its latest comments) and ``create`` (an issue in the configured team: the first line is its
title, the rest its description). ``auto`` reads an identifier, creates on "create: …", and
searches otherwise.
"""

import re
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Linear]"
API = "https://api.linear.app/graphql"
_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,9}-\d+$")

TOOL = ToolSpec(
    id="linear",
    name="Linear",
    icon="📐",
    category="Business Apps",
    description="Searches Linear issues, reads one with its comments, or creates an issue. Input: search text, an issue id like ENG-123, or 'create: Title' + description.",
    default_config={"api_key": "", "action": "auto", "team_key": "", "max_results": 10},
    order=15,
    required=("api_key",),
    selects={"action": Select("Action", (("auto", "Auto (ENG-123 → read, 'create:' → create, else search)"),
                                         ("search", "Search issues"), ("read", "Read issue"), ("create", "Create issue")))},
    parameters=params(
        {"request": {"type": "string", "description": "Search text, an issue identifier (ENG-123), or 'create: Title' + the description on the next lines"}},
        {
            "action": enum(["auto", "search", "read", "create"], "What to do (auto works it out from the request)"),
            "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Issues to return (search)"},
        },
    ),
    input_param="request",
)

SEARCH = """query($term: String!, $first: Int) {
  searchIssues(term: $term, first: $first) {
    nodes { identifier title url priorityLabel updatedAt state { name } assignee { name } team { key } }
  }
}"""
READ = """query($id: String!) {
  issue(id: $id) {
    identifier title description url priorityLabel createdAt updatedAt
    state { name } assignee { name } creator { name } team { key name }
    labels { nodes { name } }
    comments(first: 10) { nodes { body createdAt user { name } } }
  }
}"""
TEAM = """query($key: String!) { teams(filter: { key: { eq: $key } }) { nodes { id key name } } }"""
CREATE = """mutation($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { identifier title url } }
}"""


async def _gql(client: httpx.AsyncClient, query: str, variables: Dict[str, Any]) -> Any:
    """The response's data, or an error string."""
    try:
        resp = await client.post(API, json={"query": query, "variables": variables})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach Linear: {e}"
    try:
        body = resp.json()
    except ValueError:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    errors = body.get("errors") or []
    if errors:
        err = errors[0]
        code = ((err.get("extensions") or {}).get("code") or "").upper()
        if resp.status_code == 401 or code == "AUTHENTICATION_ERROR":
            return f"{LABEL} The api_key is invalid."
        return f"{LABEL} {err.get('message', 'GraphQL error')}"
    if resp.status_code != 200:
        return f"{LABEL} HTTP {resp.status_code}"
    return body.get("data") or {}


def _issue_line(i: Dict[str, Any]) -> str:
    bits = [(i.get("state") or {}).get("name"), i.get("priorityLabel"), (i.get("assignee") or {}).get("name"),
            f"updated {i['updatedAt'][:10]}" if i.get("updatedAt") else None]
    return f"- {i.get('identifier')} {i.get('title', '')}" + "".join(f" · {b}" for b in bits if b) + f"\n  {i.get('url', '')}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    key = (cfg.get("api_key") or "").strip()
    if not key:
        return f"{LABEL} api_key (Settings → Security & access → Personal API keys) is required in config."
    text = inp.strip()
    action = (cfg.get("action") or "auto").strip().lower()
    if action == "auto":
        if text.lower().startswith("create:"):
            action, text = "create", text[len("create:"):].strip()
        elif _IDENT.match(text):
            action = "read"
        else:
            action = "search"
    elif action == "create" and text.lower().startswith("create:"):
        text = text[len("create:"):].strip()
    if action not in ("search", "read", "create"):
        return f'{LABEL} Action is "auto", "search", "read" or "create" — got "{action}".'

    # Personal API keys go as is; OAuth access tokens as Bearer
    auth = key if key.startswith("lin_api_") else f"Bearer {key}"
    async with httpx.AsyncClient(timeout=20.0, headers={"Authorization": auth}) as client:
        if action == "read":
            if not _IDENT.match(text):
                return f"{LABEL} Give an issue identifier like ENG-123."
            data = await _gql(client, READ, {"id": text.upper()})
            if isinstance(data, str):
                return data
            i = data.get("issue")
            if not i:
                return f"{LABEL} Issue {text} not found."
            labels = ", ".join(n["name"] for n in (i.get("labels") or {}).get("nodes", []))
            out = [f"{LABEL} {i['identifier']}: {i.get('title', '')}", i.get("url", ""),
                   f"Status: {(i.get('state') or {}).get('name', '—')} · Priority: {i.get('priorityLabel') or '—'}"
                   f" · Assignee: {(i.get('assignee') or {}).get('name', 'unassigned')}"
                   f" · Team: {(i.get('team') or {}).get('key', '')}" + (f" · Labels: {labels}" if labels else ""),
                   "", (i.get("description") or "(no description)")[:6000]]
            comments = (i.get("comments") or {}).get("nodes", [])
            if comments:
                out += ["", f"Comments ({len(comments)}):"]
                out += [f"- {(c.get('user') or {}).get('name', '?')} ({(c.get('createdAt') or '')[:10]}): {c.get('body', '')[:800]}"
                        for c in comments]
            return "\n".join(out)

        if action == "create":
            team_key = str(cfg.get("team_key") or "").strip().upper()
            if not team_key:
                return f"{LABEL} Set team_key (e.g. ENG) to create issues."
            title, _, desc = text.partition("\n")
            if not title.strip():
                return f"{LABEL} Provide the issue title."
            data = await _gql(client, TEAM, {"key": team_key})
            if isinstance(data, str):
                return data
            teams = (data.get("teams") or {}).get("nodes", [])
            if not teams:
                return f"{LABEL} No team with key {team_key}."
            data = await _gql(client, CREATE, {"input": {"teamId": teams[0]["id"], "title": title.strip(),
                                                         **({"description": desc.strip()} if desc.strip() else {})}})
            if isinstance(data, str):
                return data
            res = data.get("issueCreate") or {}
            if not res.get("success"):
                return f"{LABEL} Linear didn't create the issue."
            issue = res.get("issue") or {}
            return f"{LABEL} Created {issue.get('identifier')}: {issue.get('title')}\n{issue.get('url', '')}"

        if not text:
            return f"{LABEL} Provide text to search for."
        limit = max(1, min(int(cfg.get("max_results") or 10), 50))
        data = await _gql(client, SEARCH, {"term": text, "first": limit})
        if isinstance(data, str):
            return data
        issues = (data.get("searchIssues") or {}).get("nodes", [])
        if not issues:
            return f"{LABEL} No issues match '{text}'."
        return f"{LABEL} {len(issues)} issue(s) matching '{text}'\n\n" + "\n".join(_issue_line(i) for i in issues)
