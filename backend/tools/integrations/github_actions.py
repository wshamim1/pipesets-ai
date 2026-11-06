"""GitHub Actions — built-in tool `github_actions` (GitHub REST API).

Input: ``owner/repo`` lists recent workflow runs (``status`` filters, default failures);
``owner/repo#<run id>`` reads one run: its jobs, the failed steps, and the end of each failed job's
log. A token (fine-grained, Actions: read) is needed for private repos and for logs.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[GitHub Actions]"
API = "https://api.github.com"
STATUSES = ("failure", "success", "in_progress", "queued", "cancelled", "any")
LOG_TAIL = 3000

TOOL = ToolSpec(
    id="github_actions",
    name="GitHub Actions",
    icon="🔁",
    category="APIs & Integrations",
    description="Lists a repo's recent GitHub Actions workflow runs (failures by default), or reads one run's jobs, failed steps and log tail. Input: owner/repo, or owner/repo#<run id>.",
    default_config={"token": "", "status": "failure", "branch": "", "max_results": 10},
    order=103,
    selects={"status": Select("Runs to list", (("failure", "Failed"), ("success", "Succeeded"),
                                               ("in_progress", "In progress"), ("queued", "Queued"),
                                               ("cancelled", "Cancelled"), ("any", "Any")))},
    parameters=params({"repo": {"type": "string", "description": "owner/repo, or owner/repo#<run id> for one run"}},
                      {"status": enum(list(STATUSES), "Which runs to list"),
                       "branch": {"type": "string", "description": "Only runs on this branch"}}),
    input_param="repo",
    is_new=True,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    ref = inp.strip().strip("'\"").removeprefix("https://github.com/")
    repo, _, run_id = ref.partition("#")
    repo = repo.strip("/ ")
    if repo.count("/") != 1:
        return f"{LABEL} Input is owner/repo, or owner/repo#<run id>."
    status = cfg.get("status") or "failure"
    if status not in STATUSES:
        return f"{LABEL} status is one of {', '.join(STATUSES)} — got '{status}'."
    token = (cfg.get("token") or "").strip()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               **({"Authorization": f"Bearer {token}"} if token else {})}
    base = f"{API}/repos/{repo}/actions"
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
            if not run_id:
                q: Dict[str, Any] = {"per_page": max(1, min(int(cfg.get("max_results") or 10), 50))}
                if status != "any":
                    q["status"] = status
                if (cfg.get("branch") or "").strip():
                    q["branch"] = cfg["branch"].strip()
                resp = await client.get(f"{base}/runs", params=q)
                jobs = logs = None
            else:
                resp = await client.get(f"{base}/runs/{run_id.strip()}")
                jobs = await client.get(f"{base}/runs/{run_id.strip()}/jobs") if resp.status_code < 400 else None
                logs = {}
                if jobs is not None and jobs.status_code < 400:
                    for j in jobs.json().get("jobs") or []:
                        if j.get("conclusion") == "failure":
                            lr = await client.get(f"{base}/jobs/{j['id']}/logs")
                            logs[j["id"]] = lr.text if lr.status_code < 400 else f"(log not available: HTTP {lr.status_code}{' — needs a token' if not token else ''})"
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach GitHub: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check the token (Actions: read) or the rate limit."
    if resp.status_code == 404:
        return f"{LABEL} Not found: {repo}{'#' + run_id if run_id else ''} (private repos need a token)."
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()

    if not run_id:
        runs = data.get("workflow_runs") or []
        if not runs:
            return f"{LABEL} No {'' if status == 'any' else status + ' '}runs in {repo}."
        return f"{LABEL} {len(runs)} {'' if status == 'any' else status + ' '}run(s) in {repo}\n" + "\n".join(
            f"- #{r.get('id')} · {r.get('name')} · {r.get('conclusion') or r.get('status')} · {r.get('head_branch')} · "
            f"{(r.get('head_commit') or {}).get('message', '').splitlines()[0][:60] if r.get('head_commit') else ''} · "
            f"{(r.get('created_at') or '')[:16].replace('T', ' ')}" for r in runs)

    lines = [f"{LABEL} {data.get('name')} run {data.get('id')} · {data.get('conclusion') or data.get('status')}",
             f"  Branch: {data.get('head_branch')} · Commit: {(data.get('head_sha') or '')[:7]} · Event: {data.get('event')}",
             f"  URL: {data.get('html_url')}"]
    for j in (jobs.json().get("jobs") if jobs is not None and jobs.status_code < 400 else []) or []:
        lines.append(f"  - job {j.get('name')}: {j.get('conclusion') or j.get('status')}")
        lines += [f"      ✗ step {s.get('number')} {s.get('name')}" for s in j.get("steps") or [] if s.get("conclusion") == "failure"]
        if j["id"] in (logs or {}):
            lines.append("      Log (end):\n" + "\n".join("        " + ln for ln in logs[j["id"]][-LOG_TAIL:].splitlines()))
    return "\n".join(lines)
