"""Kubernetes — built-in tool `kubernetes` (the Kubernetes API server, read-only).

Actions: ``pods`` (status, restarts and the reason a pod isn't ready), ``events`` (warnings first),
``logs`` (the last lines of a pod's container; input is the pod name, ``container`` optional,
``previous`` for the crashed instance) and ``deployments`` (desired vs ready replicas). Auth is a
bearer token — a read-only service account's, e.g. ``kubectl create token`` — against ``api_url``.
Unlike the MCP Kubernetes server it needs no kubeconfig or CLI on the backend machine.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Kubernetes]"
ACTIONS = ("pods", "events", "logs", "deployments")
LOG_LINES = 200

TOOL = ToolSpec(
    id="kubernetes",
    name="Kubernetes",
    icon="☸️",
    category="APIs & Integrations",
    description="Reads a Kubernetes cluster (read-only): pod status and restarts, warning events, a pod's recent logs, deployment readiness. Input: a pod name (logs) or a name filter.",
    default_config={"api_url": "", "token": "", "namespace": "default", "action": "pods", "container": "",
                    "previous": False, "verify_tls": True},
    order=102,
    required=("api_url", "token"),
    selects={"action": Select("Action", (("pods", "Pods"), ("events", "Events"), ("logs", "Pod logs"),
                                         ("deployments", "Deployments")))},
    parameters=params({"name": {"type": "string", "description": "Pod name (logs), or text a pod / deployment / event object name contains"}},
                      {"action": enum(list(ACTIONS), "What to read"),
                       "namespace": {"type": "string", "description": "Namespace; default from the node settings"},
                       "container": {"type": "string", "description": "Container name for logs (multi-container pods)"},
                       "previous": {"type": "boolean", "description": "Logs of the previous, crashed container instance"}}),
    input_param="name",
    is_new=True,
)


def _pod_line(p: Dict[str, Any]) -> str:
    st = p.get("status") or {}
    statuses: List[Dict[str, Any]] = st.get("containerStatuses") or []
    ready = sum(1 for c in statuses if c.get("ready"))
    restarts = sum(c.get("restartCount", 0) for c in statuses)
    reason = next((((c.get("state") or {}).get("waiting") or {}).get("reason")
                   or ((c.get("state") or {}).get("terminated") or {}).get("reason")
                   for c in statuses if not c.get("ready")), None)
    return (f"- {p['metadata']['name']} · {st.get('phase')} · {ready}/{len(statuses)} ready · {restarts} restarts"
            + (f" · {reason}" if reason else ""))


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = (cfg.get("api_url") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    if not api or not token:
        return f"{LABEL} api_url (the API server, e.g. https://k8s.example.com:6443) and token are required in config."
    action = cfg.get("action") or "pods"
    if action not in ACTIONS:
        return f"{LABEL} Action is one of {', '.join(ACTIONS)} — got '{action}'."
    ns = quote((cfg.get("namespace") or "default").strip(), safe="")
    name = inp.strip().strip("'\"")
    if action == "logs" and not name:
        return f"{LABEL} Provide the pod name."
    verify = cfg.get("verify_tls") not in (False, "false", "off", "no", 0)
    paths = {"pods": f"/api/v1/namespaces/{ns}/pods", "events": f"/api/v1/namespaces/{ns}/events",
             "deployments": f"/apis/apps/v1/namespaces/{ns}/deployments",
             "logs": f"/api/v1/namespaces/{ns}/pods/{quote(name, safe='')}/log"}
    q: Dict[str, Any] = {}
    if action == "logs":
        q = {"tailLines": LOG_LINES}
        if (cfg.get("container") or "").strip():
            q["container"] = cfg["container"].strip()
        if cfg.get("previous") in (True, "true", "on", "yes", 1):
            q["previous"] = "true"
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=verify, headers={"Authorization": f"Bearer {token}"}) as client:
            resp = await client.get(api + paths[action], params=q)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {api}: {e}"
    if resp.status_code == 401:
        return f"{LABEL} HTTP 401 — the token is invalid or expired."
    if resp.status_code == 403:
        return f"{LABEL} HTTP 403 — the token's service account may not {'read logs of' if action == 'logs' else 'list'} {action} in namespace {ns}."
    if resp.status_code == 404:
        return f"{LABEL} Not found: {'pod ' + name if action == 'logs' else 'namespace ' + ns}."
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:300]}"

    if action == "logs":
        text = resp.text.strip()
        return f"{LABEL} Last {LOG_LINES} log lines of {name}" + (" (previous instance)" if "previous" in q else "") + ":\n" + (text or "(empty)")
    items = [i for i in resp.json().get("items") or []
             if not name or name.lower() in ((i.get("involvedObject") or {}).get("name") or i["metadata"]["name"]).lower()]
    if not items:
        return f"{LABEL} No {action} in namespace {ns}" + (f" matching '{name}'." if name else ".")
    if action == "pods":
        items.sort(key=lambda p: all(c.get("ready") for c in (p.get("status") or {}).get("containerStatuses") or []))
        return f"{LABEL} {len(items)} pod(s) in {ns}, unready first\n" + "\n".join(map(_pod_line, items))
    if action == "deployments":
        return f"{LABEL} {len(items)} deployment(s) in {ns}\n" + "\n".join(
            f"- {d['metadata']['name']} · {(d.get('status') or {}).get('readyReplicas', 0)}/{(d.get('spec') or {}).get('replicas', 0)} ready"
            f" · {(d.get('status') or {}).get('updatedReplicas', 0)} updated" for d in items)
    items.sort(key=lambda e: e.get("lastTimestamp") or e.get("eventTime") or "", reverse=True)   # newest first,
    items.sort(key=lambda e: e.get("type") != "Warning")                                         # then warnings first
    return f"{LABEL} {len(items)} event(s) in {ns}, warnings first\n" + "\n".join(
        f"- {e.get('type')} · {(e.get('lastTimestamp') or e.get('eventTime') or '')[:16].replace('T', ' ')} · "
        f"{(e.get('involvedObject') or {}).get('kind')}/{(e.get('involvedObject') or {}).get('name')} · "
        f"{e.get('reason')}: {e.get('message')}" + (f" (×{e['count']})" if (e.get("count") or 1) > 1 else "")
        for e in items[:50])
