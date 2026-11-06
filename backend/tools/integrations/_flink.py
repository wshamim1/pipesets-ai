"""Shared HTTP handling for the Confluent Cloud Flink SQL tools (flink_*.py). Not a tool itself.

The tools talk to the Flink REST API (``<base_url>/sql/v1/organizations/<org>/environments/<env>/...``) with a
Flink API key and secret (HTTP basic auth). ``base_url`` is the regional endpoint, for example
``https://flink.us-east-1.aws.confluent.cloud``.
"""

from typing import Any, Dict, Optional

import httpx

CONNECTION_CONFIG: Dict[str, Any] = {"base_url": "", "organization_id": "", "environment_id": "",
                                     "api_key": "", "api_secret": ""}
REQUIRED = ("base_url", "organization_id", "environment_id", "api_key", "api_secret")
LABEL = "Flink"


def missing(cfg: Dict[str, Any]) -> Optional[str]:
    """The message for the first setting the tools can't work without, or None."""
    name = next((k for k in REQUIRED if not str(cfg.get(k) or "").strip()), None)
    return f"[{LABEL}] {name} is required in config." if name else None


def statements_url(cfg: Dict[str, Any]) -> str:
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    return (f"{base}/sql/v1/organizations/{cfg['organization_id'].strip()}"
            f"/environments/{cfg['environment_id'].strip()}/statements")


def client(cfg: Dict[str, Any]) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20.0, auth=((cfg.get("api_key") or "").strip(), cfg.get("api_secret") or ""))


def failed(resp: httpx.Response) -> Optional[str]:
    """The message for an error response, or None when the request worked."""
    if resp.status_code in (401, 403):
        return f"[{LABEL}] Authentication failed — check api_key and api_secret (a Flink API key)."
    if resp.status_code >= 400:
        try:
            errors = resp.json().get("errors") or []
            detail = "; ".join(str(e.get("detail") or e.get("title") or "") for e in errors).strip("; ")
        except (ValueError, AttributeError):
            detail = ""
        if resp.status_code == 404:
            return f"[{LABEL}] Not found: {detail or resp.request.url.path}"
        return f"[{LABEL}] HTTP {resp.status_code}: {detail or resp.text[:300]}"
    return None


def one_line(text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"
