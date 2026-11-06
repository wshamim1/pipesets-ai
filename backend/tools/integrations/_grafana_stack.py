"""Shared auth for the Grafana-stack tools (grafana.py, loki_query.py, tempo_traces.py,
alertmanager.py). Not a tool itself.

Self-hosted servers take a bearer token (a Grafana service-account token, or whatever the proxy in
front of Loki / Tempo / Alertmanager expects) or no auth. Grafana Cloud's Loki and Tempo use HTTP
basic auth: the stack's numeric user id as ``username`` and an access-policy token as ``token``.
"""

from typing import Any, Dict, Optional, Tuple

import httpx


def base_url(cfg: Dict[str, Any]) -> str:
    return (cfg.get("base_url") or "").strip().rstrip("/")


def client(cfg: Dict[str, Any], timeout: float = 20.0) -> httpx.AsyncClient:
    """Basic auth when ``username`` is set, else a bearer ``token``; ``org_id`` → X-Scope-OrgID (multi-tenant Loki / Tempo)."""
    token = (cfg.get("token") or "").strip()
    user = (cfg.get("username") or "").strip()
    headers: Dict[str, str] = {}
    auth: Optional[Tuple[str, str]] = None
    if user:
        auth = (user, token)
    elif token:
        headers["Authorization"] = f"Bearer {token}"
    if (cfg.get("org_id") or "").strip():
        headers["X-Scope-OrgID"] = cfg["org_id"].strip()
    verify = cfg.get("verify_tls") not in (False, "false", "off", "no", 0)
    return httpx.AsyncClient(timeout=timeout, headers=headers, auth=auth, verify=verify)


def failed(label: str, resp: httpx.Response, what: str = "") -> Optional[str]:
    if resp.status_code in (401, 403):
        return f"{label} HTTP {resp.status_code} — check token (and username for Grafana Cloud) and its permissions."
    if resp.status_code == 404:
        return f"{label} Not found{': ' + what if what else ''} — check base_url."
    if resp.status_code >= 400:
        return f"{label} HTTP {resp.status_code}: {resp.text[:300]}"
    return None


def lookback_seconds(value: Any, default: int = 3600) -> int:
    """'15m' / '2h' / '1d' / seconds → seconds."""
    text = str(value or "").strip().lower()
    if not text:
        return default
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        return int(float(text[:-1]) * units[text[-1]]) if text[-1] in units else int(float(text))
    except (ValueError, KeyError):
        return default
