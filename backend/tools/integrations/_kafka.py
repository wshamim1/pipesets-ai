"""Shared HTTP handling for the Kafka / Confluent tools (kafka_*.py). Not a tool itself.

The tools talk to the Kafka REST API (v3) — Confluent Cloud, Confluent Server's embedded REST API
(``/kafka/v3``) or a standalone REST Proxy (``/v3``) — to Schema Registry and to Kafka Connect, all over
HTTP with an optional API key / secret (HTTP basic auth).
"""

from typing import Any, Dict, Optional, Tuple

import httpx

from tools.base import Select

CONNECTION_CONFIG: Dict[str, Any] = {"base_url": "http://localhost:8082", "rest_path": "/kafka/v3", "cluster_id": "",
                                     "api_key": "", "api_secret": ""}
REST_PATH_SELECT = Select("Kafka REST API path", (("/kafka/v3", "Confluent Cloud / Confluent Server"),
                                                  ("/v3", "Standalone REST Proxy")))
NO_BASE_URL = "[Kafka] base_url (the REST endpoint, e.g. http://localhost:8082) is required in config."


def base_url(cfg: Dict[str, Any]) -> str:
    return (cfg.get("base_url") or "").strip().rstrip("/")


def client(cfg: Dict[str, Any]) -> httpx.AsyncClient:
    """An HTTP client with the node's API key / secret as basic auth, when set."""
    key = (cfg.get("api_key") or "").strip()
    return httpx.AsyncClient(timeout=15.0, auth=(key, cfg.get("api_secret") or "") if key else None)


def failed(resp: httpx.Response, label: str = "Kafka") -> Optional[str]:
    """The message for an error response, or None when the request worked."""
    if resp.status_code in (401, 403):
        return f"[{label}] Authentication failed — check api_key and api_secret."
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("message") or ""
        except ValueError:
            detail = ""
        if resp.status_code == 404:
            return f"[{label}] Not found: {detail or resp.request.url.path}"
        return f"[{label}] HTTP {resp.status_code}: {detail or resp.text[:300]}"
    return None


async def cluster_url(c: httpx.AsyncClient, cfg: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """(``<rest>/clusters/<id>``, error). The id is the node's cluster_id, else the only cluster the endpoint serves."""
    root = base_url(cfg) + ("/v3" if cfg.get("rest_path") == "/v3" else "/kafka/v3")
    cluster_id = (cfg.get("cluster_id") or "").strip()
    if not cluster_id:
        resp = await c.get(f"{root}/clusters")
        if err := failed(resp):
            return None, err
        ids = [x.get("cluster_id") for x in resp.json().get("data", []) if x.get("cluster_id")]
        if len(ids) != 1:
            return None, ("[Kafka] No cluster found at this endpoint." if not ids
                          else f"[Kafka] This endpoint serves {len(ids)} clusters; set cluster_id ({', '.join(ids[:5])}).")
        cluster_id = ids[0]
    return f"{root}/clusters/{cluster_id}", None
