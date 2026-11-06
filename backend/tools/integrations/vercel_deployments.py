"""Vercel — built-in tool `vercel_deployments` (Vercel REST API with an access token; read-only).

Input: empty or a project name lists recent deployments (``state`` filters, default failed ones);
a deployment id (``dpl_…``) or URL reads that deployment: its state, error and the end of its build
log. ``team_id`` is needed for projects owned by a team.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Vercel]"
API = "https://api.vercel.com"
STATES = ("ERROR", "READY", "BUILDING", "QUEUED", "CANCELED", "any")
LOG_LINES = 60
_DEPLOYMENT = re.compile(r"^(dpl_[A-Za-z0-9]+|(?:https?://)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.vercel\.app/?)$")

TOOL = ToolSpec(
    id="vercel_deployments",
    name="Vercel Deployments",
    icon="▲",
    category="APIs & Integrations",
    description="Vercel deployments (read-only): recent ones (failed by default) for all projects or one, or one deployment's state, error and build log tail. Input: empty, a project name, or a deployment id / URL.",
    default_config={"token": "", "team_id": "", "state": "ERROR", "max_results": 10},
    order=112,
    required=("token",),
    selects={"state": Select("Deployments to list", (("ERROR", "Failed"), ("READY", "Ready"), ("BUILDING", "Building"),
                                                     ("QUEUED", "Queued"), ("CANCELED", "Canceled"), ("any", "Any")))},
    parameters=params({}, {"target": {"type": "string", "description": "A project name, a deployment id (dpl_…) or URL, or empty"},
                           "state": enum(list(STATES), "Which deployments to list")}),
    input_param="target",
    is_new=True,
)


def _when(ms: Any) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M") if isinstance(ms, (int, float)) else ""


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = str(cfg.get("token") or "").strip()
    if not token:
        return f"{LABEL} token (Account settings → Tokens) is required in config."
    state = str(cfg.get("state") or "ERROR").strip()
    state = state.upper() if state.lower() != "any" else "any"
    if state not in STATES:
        return f"{LABEL} state is one of {', '.join(STATES)} — got '{state}'."
    target = inp.strip().strip("'\"")
    team = {"teamId": cfg["team_id"].strip()} if str(cfg.get("team_id") or "").strip() else {}
    limit = max(1, min(int(cfg.get("max_results") or 10), 100))
    events = None
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"Authorization": f"Bearer {token}"}) as client:
            if _DEPLOYMENT.match(target):
                ref = re.sub(r"^https?://", "", target).strip("/")
                resp = await client.get(f"{API}/v13/deployments/{ref}", params=team)
                if resp.status_code == 200:
                    events = await client.get(f"{API}/v3/deployments/{resp.json()['id']}/events",
                                              params={**team, "direction": "backward", "limit": LOG_LINES})
            elif not target or re.match(r"^[A-Za-z0-9._-]+$", target):
                q: Dict[str, Any] = {**team, "limit": limit}
                if target:
                    q["projectId"] = target
                if state != "any":
                    q["state"] = state
                resp = await client.get(f"{API}/v6/deployments", params=q)
            else:
                return f"{LABEL} Input is a project name, a deployment id (dpl_…) or URL, or empty."
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach Vercel: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check the token, and team_id for team projects."
    if resp.status_code == 404:
        return f"{LABEL} Not found: {target} (team projects need team_id)."
    if resp.status_code >= 400:
        try:
            detail = (resp.json().get("error") or {}).get("message")
        except (ValueError, AttributeError):
            detail = None
        return f"{LABEL} HTTP {resp.status_code}: {detail or resp.text[:200]}"
    data = resp.json()

    if events is not None:
        lines = [f"{LABEL} {data.get('name')} · {data.get('readyState') or data.get('status')} · {data.get('target') or 'preview'}",
                 f"  https://{data.get('url')} · created {_when(data.get('createdAt'))}"]
        meta = data.get("meta") or {}
        if meta.get("githubCommitMessage"):
            lines.append(f"  Commit: {(meta.get('githubCommitSha') or '')[:7]} {meta['githubCommitMessage'].splitlines()[0][:80]}"
                         f" ({meta.get('githubCommitRef', '')})")
        if data.get("errorMessage") or data.get("errorCode"):
            lines.append(f"  Error: {data.get('errorCode') or ''} {data.get('errorMessage') or ''}".rstrip())
        if events.status_code < 400:
            evs = events.json()
            evs = evs if isinstance(evs, list) else evs.get("events") or []
            text = [e.get("text") or (e.get("payload") or {}).get("text") or "" for e in reversed(evs)]
            if any(text):
                lines.append("  Build log (end):\n" + "\n".join("    " + t for t in text if t))
        else:
            lines.append(f"  (build log not available: HTTP {events.status_code})")
        return "\n".join(lines)
    deps = data.get("deployments") or []
    what = ("" if state == "any" else state.lower() + " ") + "deployment(s)" + (f" of {target}" if target else "")
    if not deps:
        return f"{LABEL} No {what}."
    return f"{LABEL} {len(deps)} recent {what}\n" + "\n".join(
        f"- {d.get('uid')} · {d.get('name')} · {d.get('state') or d.get('readyState')} · {d.get('target') or 'preview'}"
        f" · {_when(d.get('created'))}"
        f"{' · ' + (d.get('meta') or {})['githubCommitMessage'].splitlines()[0][:60] if (d.get('meta') or {}).get('githubCommitMessage') else ''}"
        f"\n    https://{d.get('url')}" for d in deps)
