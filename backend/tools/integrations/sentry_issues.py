"""Sentry — built-in tool `sentry_issues` (Sentry REST API with an auth token).

A numeric issue id reads that issue with its latest event's stack trace; anything else searches the
organization's issues (or one project's, with ``project`` set) using Sentry's search syntax, with
``is:unresolved`` added unless the input sets ``is:``.
"""

from typing import Any, Dict, List, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Sentry]"

TOOL = ToolSpec(
    id="sentry_issues",
    name="Sentry Issues",
    icon="🚨",
    category="APIs & Integrations",
    description="Searches unresolved Sentry issues, or reads one issue with its latest stack trace. Input: search text (Sentry syntax works) or an issue id.",
    default_config={"auth_token": "", "organization": "", "project": "", "base_url": "https://sentry.io",
                    "stats_period": "14d", "max_results": 10},
    order=95,
    required=("auth_token", "organization"),
    parameters=params(
        {"request": {"type": "string", "description": "Search text such as 'TypeError checkout' or 'level:error', or a numeric issue id"}},
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Issues to return (search)"}},
    ),
    input_param="request",
)


def _frames(event: Dict[str, Any]) -> List[str]:
    """The last frames of the event's first exception, innermost last."""
    for entry in event.get("entries") or []:
        if entry.get("type") != "exception":
            continue
        for exc in (entry.get("data") or {}).get("values") or []:
            frames = ((exc.get("stacktrace") or {}).get("frames") or [])[-8:]
            out = [f"{exc.get('type', 'Exception')}: {exc.get('value', '')}"]
            out += [f"  at {f.get('function') or '?'} ({f.get('filename') or f.get('module') or '?'}:{f.get('lineNo') or '?'})"
                    for f in frames]
            return out
    return []


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("auth_token") or "").strip()
    org = (cfg.get("organization") or "").strip()
    if not token:
        return f"{LABEL} auth_token (Settings → Auth Tokens, scopes event:read and project:read) is required in config."
    if not org:
        return f"{LABEL} organization (the slug in your Sentry URL) is required in config."
    base = (cfg.get("base_url") or "https://sentry.io").strip().rstrip("/")
    api = f"{base}/api/0/organizations/{org}"
    text = inp.strip()
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"Authorization": f"Bearer {token}"}) as client:
            if text.isdigit():
                resp = await client.get(f"{api}/issues/{text}/")
                if resp.status_code == 200:
                    issue = resp.json()
                    ev = await client.get(f"{api}/issues/{text}/events/latest/")
                    trace = _frames(ev.json()) if ev.status_code == 200 else []
                    out = [f"{LABEL} {issue.get('shortId', text)}: {issue.get('title', '')}", issue.get("permalink", ""),
                           f"Status: {issue.get('status')} · Level: {issue.get('level')} · Events: {issue.get('count')}"
                           f" · Users: {issue.get('userCount')} · Project: {(issue.get('project') or {}).get('slug', '')}",
                           f"First seen {(issue.get('firstSeen') or '')[:16]} · last seen {(issue.get('lastSeen') or '')[:16]}"]
                    if issue.get("culprit"):
                        out.append(f"Culprit: {issue['culprit']}")
                    if trace:
                        out += ["", "Latest stack trace:", *trace]
                    return "\n".join(out)
            else:
                query = text if "is:" in text else f"is:unresolved {text}".strip()
                q: Dict[str, Any] = {"query": query, "statsPeriod": cfg.get("stats_period") or "14d",
                                     "limit": max(1, min(int(cfg.get("max_results") or 10), 50))}
                project = (cfg.get("project") or "").strip()
                url = f"{base}/api/0/projects/{org}/{project}/issues/" if project else f"{api}/issues/"
                resp = await client.get(url, params=q)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {base}: {e}"
    if resp.status_code == 401:
        return f"{LABEL} The auth_token is invalid."
    if resp.status_code == 403:
        return f"{LABEL} The auth_token can't read this organization (needs event:read)."
    if resp.status_code == 404:
        return f"{LABEL} Not found — check organization / project, or the issue id."
    if resp.status_code != 200:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    issues = resp.json()
    if not issues:
        return f"{LABEL} No issues match '{query}'."
    lines = [f"{LABEL} {len(issues)} issue(s) for '{query}'"]
    for i in issues:
        lines.append(f"- {i.get('id')} {i.get('shortId', '')}: {i.get('title', '')}\n"
                     f"  {i.get('level')} · {i.get('count')} events · {i.get('userCount')} users"
                     f" · last seen {(i.get('lastSeen') or '')[:16]}\n  {i.get('permalink', '')}")
    return "\n".join(lines)
