"""Jenkins — built-in tool `jenkins` (Jenkins remote access API).

Input is a job name; jobs in folders use slashes (``team/service/deploy``). Actions: ``status``
(last build: result, number, duration, who started it), ``log`` (the end of the last build's
console), ``build`` (queue a build) and ``list`` (jobs at the top level, or in the folder given).
Authentication is a username plus API token, which needs no CSRF crumb.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Jenkins]"
ACTIONS = ("status", "log", "build", "list")
LOG_TAIL = 4000

TOOL = ToolSpec(
    id="jenkins",
    name="Jenkins",
    icon="🤵",
    category="APIs & Integrations",
    description="Checks a Jenkins job's last build, reads the end of its console log, starts a build, or lists jobs. Input is the job name (folder/job for jobs in folders).",
    default_config={"base_url": "", "username": "", "api_token": "", "action": "status"},
    order=97,
    required=("base_url",),
    selects={"action": Select("Action", (("status", "Last build status"), ("log", "Last build console log"),
                                         ("build", "Start a build"), ("list", "List jobs")))},
    parameters=params({"job": {"type": "string", "description": "Job name, folder/job for jobs in folders; a folder (or nothing) for list"}},
                      {"action": enum(list(ACTIONS), "What to do")}),
    input_param="job",
)


def _job_path(job: str) -> str:
    return "".join(f"/job/{quote(part, safe='')}" for part in job.strip("/ ").split("/") if part)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    if not base:
        return f"{LABEL} base_url (e.g. https://jenkins.example.com) is required in config."
    action = cfg.get("action") or "status"
    if action not in ACTIONS:
        return f"{LABEL} Action is one of {', '.join(ACTIONS)} — got '{action}'."
    job = inp.strip().strip("'\"")
    if action != "list" and not job:
        return f"{LABEL} Provide the job name."
    user = (cfg.get("username") or "").strip()
    auth = (user, cfg.get("api_token") or "") if user else None
    path = base + _job_path(job)
    try:
        async with httpx.AsyncClient(timeout=20.0, auth=auth) as client:
            if action == "list":
                resp = await client.get(f"{path}/api/json", params={"tree": "jobs[name,color,url]"})
            elif action == "status":
                resp = await client.get(f"{path}/lastBuild/api/json",
                                        params={"tree": "number,result,building,duration,timestamp,url,actions[causes[shortDescription]]"})
            elif action == "log":
                resp = await client.get(f"{path}/lastBuild/consoleText")
            else:
                resp = await client.post(f"{path}/build")
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {base}: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check username and api_token, and that the user may {action} this job."
    if resp.status_code == 404:
        return f"{LABEL} {'Job' if job else 'Server'} '{job or base}' not found" + (" (or it has no builds yet)." if action in ("status", "log") else ".")
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"

    if action == "build":
        queued = resp.headers.get("location", "")
        return f"{LABEL} Build of '{job}' queued." + (f"\nQueue item: {queued}" if queued else "")
    if action == "log":
        text = resp.text
        cut = len(text) > LOG_TAIL
        return f"{LABEL} Console of the last '{job}' build" + (f" (last {LOG_TAIL} characters)" if cut else "") + ":\n" + text[-LOG_TAIL:]
    data = resp.json()
    if action == "list":
        jobs = data.get("jobs") or []
        if not jobs:
            return f"{LABEL} No jobs in {job or 'the top level'}."
        state = lambda color: {"blue": "passing", "red": "failing", "yellow": "unstable", "disabled": "disabled",  # noqa: E731
                               "notbuilt": "never built", "aborted": "aborted"}.get((color or "").replace("_anime", ""), color or "folder")
        return f"{LABEL} {len(jobs)} job(s) in {job or 'the top level'}\n" + "\n".join(
            f"- {j.get('name')} · {state(j.get('color'))}{' (building)' if (j.get('color') or '').endswith('_anime') else ''}" for j in jobs)
    started = datetime.fromtimestamp(data.get("timestamp", 0) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    causes = [c.get("shortDescription") for a in data.get("actions") or [] if a for c in a.get("causes") or []]
    result = "BUILDING" if data.get("building") else (data.get("result") or "UNKNOWN")
    return (f"{LABEL} {job} #{data.get('number')}: {result}\n"
            f"  Started  : {started}" + (f" ({causes[0]})" if causes else "") + "\n"
            f"  Duration : {round((data.get('duration') or 0) / 1000)}s\n"
            f"  URL      : {data.get('url', '')}")
