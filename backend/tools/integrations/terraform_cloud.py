"""HCP Terraform — built-in tool `terraform_cloud` (HCP Terraform / Terraform Enterprise API v2 with
a user or team token; read-only).

Input: empty lists the organization's workspaces with their latest run, errored first; a workspace
name lists its recent runs; a run id (``run-…``) reads that run: its status, the plan's resource
changes and, when the plan or apply errored, the end of its log. ``hostname`` points it at a
Terraform Enterprise install.
"""

import re
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Terraform]"
LOG_TAIL = 3000
_RUN = re.compile(r"^run-[A-Za-z0-9]+$")
_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_BAD = ("errored", "canceled", "force_canceled", "discarded", "policy_soft_failed")

TOOL = ToolSpec(
    id="terraform_cloud",
    name="HCP Terraform",
    icon="🏗️",
    category="APIs & Integrations",
    description="HCP Terraform / Terraform Enterprise (read-only): workspaces with their latest run (errored first), a workspace's runs, or one run's plan changes and error log. Input: empty, a workspace name, or a run id (run-…).",
    default_config={"token": "", "organization": "", "hostname": "app.terraform.io", "max_results": 20},
    order=111,
    required=("token", "organization"),
    parameters=params({}, {"target": {"type": "string", "description": "A workspace name, a run id (run-…), or empty for all workspaces"}}),
    input_param="target",
    is_new=True,
)


def _run_line(r: Dict[str, Any]) -> str:
    a = r.get("attributes") or {}
    return (f"- {r.get('id')} · {a.get('status')} · {(a.get('created-at') or '')[:16].replace('T', ' ')}"
            f"{' · ' + a['message'][:80] if a.get('message') else ''}{' · no changes' if a.get('has-changes') is False else ''}")


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = str(cfg.get("token") or "").strip()
    org = str(cfg.get("organization") or "").strip()
    if not token or not org:
        return f"{LABEL} token and organization are required in config."
    if not _NAME.match(org):
        return f"{LABEL} organization is a name like 'acme' — got '{org}'."
    host = re.sub(r"^https?://", "", str(cfg.get("hostname") or "app.terraform.io").strip()).strip("/")
    api = f"https://{host}/api/v2"
    target = inp.strip().strip("'\"")
    limit = max(1, min(int(cfg.get("max_results") or 20), 100))
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/vnd.api+json"}
    log = ""
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            if not target:
                resp = await client.get(f"{api}/organizations/{org}/workspaces",
                                        params={"page[size]": limit, "include": "current_run"})
            elif _RUN.match(target):
                resp = await client.get(f"{api}/runs/{target}", params={"include": "plan,apply"})
                if resp.status_code == 200:
                    for inc in resp.json().get("included") or []:
                        a = inc.get("attributes") or {}
                        if a.get("status") == "errored" and a.get("log-read-url"):
                            # archivist URLs are pre-signed; the token must not go to them
                            async with httpx.AsyncClient(timeout=20.0) as plain:
                                lr = await plain.get(a["log-read-url"])
                            log = f"{inc.get('type', '')[:-1]} log (end):\n" + (lr.text[-LOG_TAIL:] if lr.status_code < 400 else f"(not available: HTTP {lr.status_code})")
            elif _NAME.match(target):
                ws = await client.get(f"{api}/organizations/{org}/workspaces/{target}")
                if ws.status_code >= 400:
                    resp = ws
                else:
                    resp = await client.get(f"{api}/workspaces/{ws.json()['data']['id']}/runs", params={"page[size]": limit})
            else:
                return f"{LABEL} Input is a workspace name, a run id (run-…), or empty."
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {host}: {e}"
    if resp.status_code == 401:
        return f"{LABEL} HTTP 401 — check the token."
    if resp.status_code == 404:
        return f"{LABEL} Not found: {target or org} (or the token can't see it)."
    if resp.status_code >= 400:
        try:
            detail = "; ".join(e.get("detail") or e.get("title", "") for e in resp.json().get("errors") or [])
        except (ValueError, AttributeError):
            detail = ""
        return f"{LABEL} HTTP {resp.status_code}: {detail or resp.text[:200]}"
    body = resp.json()
    data = body.get("data")

    if not target:
        runs = {r["id"]: (r.get("attributes") or {}) for r in body.get("included") or [] if r.get("type") == "runs"}
        rows = []
        for w in data or []:
            cur = ((w.get("relationships") or {}).get("current-run") or {}).get("data") or {}
            rows.append((w.get("attributes") or {}, runs.get(cur.get("id"), {}), cur.get("id")))
        if not rows:
            return f"{LABEL} No workspaces in {org}."
        rows.sort(key=lambda x: (x[1].get("status") not in _BAD, x[0].get("name", "")))
        return f"{LABEL} {len(rows)} workspace(s) in {org}, problems first\n" + "\n".join(
            f"- {a.get('name')} · latest run: {r.get('status', 'none')}{' (' + rid + ')' if rid else ''}"
            f" · {a.get('resource-count', '?')} resources · TF {a.get('terraform-version')}"
            f"{' · locked' if a.get('locked') else ''}" for a, r, rid in rows)
    if _RUN.match(target):
        a = data.get("attributes") or {}
        lines = [f"{LABEL} Run {target} · {a.get('status')}",
                 f"  Message: {a.get('message') or '—'} · Source: {a.get('source')} · Created {(a.get('created-at') or '')[:16].replace('T', ' ')}"]
        for inc in body.get("included") or []:
            ia = inc.get("attributes") or {}
            if inc.get("type") == "plans":
                lines.append(f"  Plan: {ia.get('status')} · +{ia.get('resource-additions', 0)} ~{ia.get('resource-changes', 0)}"
                             f" -{ia.get('resource-destructions', 0)}{' · ' + str(ia['resource-imports']) + ' import(s)' if ia.get('resource-imports') else ''}")
            elif inc.get("type") == "applies":
                lines.append(f"  Apply: {ia.get('status')}")
        if log:
            lines.append("  " + log.replace("\n", "\n    "))
        return "\n".join(lines)
    if not data:
        return f"{LABEL} No runs in {target} yet."
    return f"{LABEL} {len(data)} recent run(s) in {target}\n" + "\n".join(_run_line(r) for r in data)
