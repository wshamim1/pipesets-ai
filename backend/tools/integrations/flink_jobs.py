"""Flink jobs — built-in tool `flink_jobs` (self-managed Flink: the JobManager REST API).

``base_url`` is the JobManager's REST endpoint (``http://jobmanager:8081``), reached directly or through a
proxy that may want a basic-auth key and secret. For Flink SQL on Confluent Cloud use ``flink_statements``.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "Flink"
JOB_ID = re.compile(r"^[0-9a-f]{32}$")
UNHEALTHY = ("FAILED", "FAILING", "RESTARTING")
MAX_VERTICES = 10

TOOL = ToolSpec(
    id="flink_jobs",
    name="Flink Jobs",
    icon="🐿️",
    category="APIs & Integrations",
    description="Check a self-managed Apache Flink cluster: list jobs with their state (failing ones first), or show one job's vertices, backpressure, checkpoints and latest exception. Input: a job id or name, or empty to list.",
    default_config={"base_url": "http://localhost:8081", "api_key": "", "api_secret": "", "max_results": 50},
    order=46,
    required=("base_url",),
    parameters=params(
        {},
        {
            "job": {"type": "string", "description": "A job id or name to inspect; leave out to list jobs"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 200, "description": "How many jobs to list"},
        },
    ),
    input_param="job",
)


def _client(cfg: Dict[str, Any]) -> httpx.AsyncClient:
    key = (cfg.get("api_key") or "").strip()
    return httpx.AsyncClient(timeout=15.0, auth=(key, cfg.get("api_secret") or "") if key else None)


def _failed(resp: httpx.Response) -> Optional[str]:
    """The message for an error response, or None when the request worked."""
    if resp.status_code in (401, 403):
        return f"[{LABEL}] Authentication failed — check api_key and api_secret."
    if resp.status_code >= 400:
        try:
            errors = resp.json().get("errors") or []
            detail = "; ".join(str(e).strip().splitlines()[0] for e in errors if str(e).strip())
        except (ValueError, AttributeError):
            detail = ""
        if resp.status_code == 404:
            return f"[{LABEL}] Not found: {detail or resp.request.url.path}"
        return f"[{LABEL}] HTTP {resp.status_code}: {detail or resp.text[:300]}"
    return None


def _duration(ms: Any) -> str:
    try:
        seconds = int(ms) // 1000
    except (TypeError, ValueError):
        return "?"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {secs}s" if minutes else f"{secs}s"


def _size(n: Any) -> str:
    try:
        size = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "?"


def _when(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def _line(text: Any, limit: int = 200) -> str:
    """The first line of a (stack trace) text, shortened."""
    first = (str(text or "").strip().splitlines() or [""])[0].strip()
    return first if len(first) <= limit else first[:limit - 1] + "…"


async def _job_id(client: httpx.AsyncClient, base: str, ref: str):
    """(job id, error): a 32-hex id as is, else the newest job with this name."""
    if JOB_ID.match(ref):
        return ref, None
    resp = await client.get(f"{base}/jobs/overview")
    if err := _failed(resp):
        return None, err
    matches = [j for j in resp.json().get("jobs", []) if j.get("name") == ref]
    if not matches:
        return None, f"[{LABEL}] No job named '{ref}'."
    return max(matches, key=lambda j: j.get("start-time") or 0)["jid"], None


async def _optional(client: httpx.AsyncClient, url: str) -> Optional[Dict[str, Any]]:
    """A GET whose failure just leaves a section out (checkpoints, for one, don't exist for batch jobs)."""
    try:
        resp = await client.get(url)
        return resp.json() if resp.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    if not base:
        return f"[{LABEL}] base_url (the JobManager REST endpoint, e.g. http://localhost:8081) is required in config."
    ref = inp.strip()
    try:
        limit = max(1, min(int(cfg.get("max_results", 50)), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        async with _client(cfg) as client:
            if not ref:
                resp = await client.get(f"{base}/jobs/overview")
                if err := _failed(resp):
                    return err
                jobs = resp.json().get("jobs", [])
                if not jobs:
                    return f"[{LABEL}] No jobs."
                rows = sorted(jobs, key=lambda j: (j.get("state") not in UNHEALTHY, str(j.get("name")), j.get("jid")))
                bad = sum(1 for j in rows if j.get("state") in UNHEALTHY)
                lines = [f"[{LABEL}] {len(rows)} job(s), " + (f"{bad} unhealthy" if bad else "none unhealthy")
                         + (f" (showing {limit})" if len(rows) > limit else "")]
                for j in rows[:limit]:
                    lines.append(f"  {j.get('name')} [{j.get('state', 'unknown')}] — {j.get('jid')}, "
                                 f"{_duration(j.get('duration'))}")
                return "\n".join(lines)

            jid, err = await _job_id(client, base, ref)
            if err:
                return err
            resp = await client.get(f"{base}/jobs/{jid}")
            if err := _failed(resp):
                return err
            job = resp.json()
            state = job.get("state", "unknown")
            vertices = job.get("vertices", [])
            lines = [f"[Flink Job] {job.get('name', ref)} [{state}]",
                     f"  Id       : {jid}",
                     f"  Started  : {_when(job.get('start-time'))} ({_duration(job.get('duration'))})"]
            if vertices:
                lines.append(f"  Vertices : {len(vertices)}")
            for v in vertices[:MAX_VERTICES]:
                pressure = ""
                if v.get("status") == "RUNNING":
                    bp = await _optional(client, f"{base}/jobs/{jid}/vertices/{v.get('id')}/backpressure")
                    level = (bp or {}).get("backpressure-level")
                    if level in ("low", "high"):
                        pressure = f", backpressure {level}"
                lines.append(f"    {_line(v.get('name'), 70)} [{v.get('status')}] — parallelism {v.get('parallelism')}{pressure}")
            if len(vertices) > MAX_VERTICES:
                lines.append(f"    … {len(vertices) - MAX_VERTICES} more")

            cp = await _optional(client, f"{base}/jobs/{jid}/checkpoints")
            if cp and cp.get("counts"):
                c = cp["counts"]
                lines.append(f"  Checkpoints : {c.get('completed', 0)} completed, {c.get('failed', 0)} failed, "
                             f"{c.get('in_progress', 0)} in progress")
                latest = cp.get("latest") or {}
                done, bad = latest.get("completed"), latest.get("failed")
                if done:
                    lines.append(f"    Last completed: #{done.get('id')} at {_when(done.get('trigger_timestamp'))}, "
                                 f"{_duration(done.get('end_to_end_duration'))}, {_size(done.get('state_size'))}")
                if bad:
                    lines.append(f"    Last failed: #{bad.get('id')} at {_when(bad.get('failure_timestamp'))} — "
                                 f"{_line(bad.get('failure_message'))}")

            if state in UNHEALTHY or state == "RUNNING":
                ex = await _optional(client, f"{base}/jobs/{jid}/exceptions")
                entries = ((ex or {}).get("exceptionHistory") or {}).get("entries") or []
                root = _line((ex or {}).get("root-exception")) or (
                    _line(entries[0].get("stacktrace") or entries[0].get("exceptionName")) if entries else "")
                if root:
                    lines.append(f"  Latest exception: {root}")
            return "\n".join(lines)
    except httpx.HTTPError as e:
        return f"[{LABEL}] Error: {e}"
