"""Shared connection handling for the Apache Airflow tools (airflow*.py). Not a tool itself."""

from typing import Any, Dict, Optional, Tuple

import httpx

from tools.base import Select

CONNECTION_CONFIG: Dict[str, Any] = {"base_url": "http://localhost:8080", "api_version": "v1", "username": "",
                                     "password": "", "api_token": ""}
VERSION_SELECT = Select("REST API version", (("v1", "v1 (Airflow 2.x)"), ("v2", "v2 (Airflow 3.x)")))
NO_BASE_URL = "[Airflow] base_url (e.g. http://localhost:8080) is required in config."


def api_url(cfg: Dict[str, Any]) -> Optional[str]:
    """The REST API root for this node config, or None without a base_url."""
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    return f"{base}/api/{'v2' if cfg.get('api_version') == 'v2' else 'v1'}" if base else None


def client(cfg: Dict[str, Any]) -> httpx.AsyncClient:
    """An HTTP client with the node's credentials: a bearer token wins over basic auth."""
    token = (cfg.get("api_token") or "").strip()
    username = (cfg.get("username") or "").strip()
    return httpx.AsyncClient(timeout=15.0,
                             headers={"Authorization": f"Bearer {token}"} if token else {},
                             auth=(username, cfg.get("password") or "") if username and not token else None)


def failed(resp: httpx.Response) -> Optional[str]:
    """The message for an error response, or None when the request worked."""
    if resp.status_code in (401, 403):
        return "[Airflow] Authentication failed — check username/password or api_token."
    if resp.status_code == 404:
        return f"[Airflow] Not found: {resp.request.url.path}"
    if resp.status_code >= 400:
        return f"[Airflow] HTTP {resp.status_code}: {resp.text[:300]}"
    return None


async def latest_run_id(c: httpx.AsyncClient, api: str, dag_id: str) -> Tuple[Optional[str], Optional[str]]:
    """(run id of the DAG's most recent run, error message)."""
    resp = await c.get(f"{api}/dags/{dag_id}/dagRuns", params={"limit": 1, "order_by": "-start_date"})
    if err := failed(resp):
        return None, err
    runs = resp.json().get("dag_runs", [])
    return (runs[0]["dag_run_id"], None) if runs else (None, f"[Airflow] No runs for {dag_id}.")


def short(ts: Optional[str]) -> str:
    return (ts or "")[:19].replace("T", " ")
