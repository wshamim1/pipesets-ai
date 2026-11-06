"""
external_agent.py — call a remote agent as a child of a Master Agent.

Supported protocols
-------------------
openai — OpenAI-compatible ``/v1/chat/completions`` (vLLM, Ollama, LiteLLM proxy, ...)
rest   — generic HTTP endpoint with a JSON body template and a response path
a2a    — Agent2Agent JSON-RPC (``message/send``, polling ``tasks/get`` when needed)

Security
--------
Endpoints that resolve to private / loopback / link-local addresses are blocked
(SSRF guard) unless ``EXTERNAL_AGENT_ALLOW_PRIVATE=1`` or the host is listed in
``EXTERNAL_AGENT_ALLOWED_HOSTS`` (comma separated).  Redirects are not followed.
"""

import asyncio
import ipaddress
import json
import os
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

from services import secret_store

ERROR_PREFIX = "[Error from external agent"

A2A_FINAL_STATES = {"completed", "failed", "canceled", "rejected"}


@dataclass
class ExternalAgentSpec:
    endpoint_url: str
    protocol: str = "openai"          # openai | rest | a2a
    api_key: str = ""
    auth_type: str = "bearer"         # none | bearer | header
    auth_header: str = "X-API-Key"    # header name when auth_type == "header"
    model: str = ""                   # openai protocol only
    system_prompt: str = ""           # openai protocol only
    request_template: str = ""        # rest protocol only, supports {{task}} / {{context}}
    response_path: str = ""           # rest protocol only, e.g. "data.0.text"
    timeout_ms: int = 45000
    max_retries: int = 1
    retry_backoff_ms: int = 500


# ── SSRF guard ────────────────────────────────────────────────────────────────

def _allowed_hosts() -> set[str]:
    raw = os.getenv("EXTERNAL_AGENT_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


async def validate_endpoint(url: str) -> None:
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Endpoint URL must be an http(s) URL with a host")

    host = parsed.hostname.lower()
    if os.getenv("EXTERNAL_AGENT_ALLOW_PRIVATE", "0") == "1" or host in _allowed_hosts():
        return

    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except OSError as e:   # gaierror, or any other resolver failure
        raise ValueError(f"Cannot resolve host '{host}': {e}") from e

    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            raise ValueError(
                f"Host '{host}' resolves to a non-public address ({ip}). "
                "Set EXTERNAL_AGENT_ALLOW_PRIVATE=1 or add the host to "
                "EXTERNAL_AGENT_ALLOWED_HOSTS to allow it."
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers(spec: ExternalAgentSpec) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = secret_store.reveal_value(spec.api_key)  # may be a "secret://" vault ref
    if api_key:
        if spec.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {api_key}"
        elif spec.auth_type == "header":
            headers[spec.auth_header or "X-API-Key"] = api_key
    return headers


def _compose_user_content(task: str, context: str) -> str:
    if context:
        return f"Context from previous steps:\n{context}\n\nYour task:\n{task}"
    return task


def _extract_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(f"Cannot descend into '{part}'")
    return cur


def _to_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")


# ── Protocol adapters ─────────────────────────────────────────────────────────

async def _call_openai(client: httpx.AsyncClient, spec: ExternalAgentSpec, task: str, context: str) -> str:
    url = spec.endpoint_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    messages = []
    if spec.system_prompt:
        messages.append({"role": "system", "content": spec.system_prompt})
    messages.append({"role": "user", "content": _compose_user_content(task, context)})

    payload: Dict[str, Any] = {"messages": messages}
    if spec.model:
        payload["model"] = spec.model

    resp = await client.post(url, headers=_headers(spec), json=payload)
    _raise_for_status(resp)
    return resp.json()["choices"][0]["message"]["content"] or ""


async def _call_rest(client: httpx.AsyncClient, spec: ExternalAgentSpec, task: str, context: str) -> str:
    template = spec.request_template or '{"task": "{{task}}", "context": "{{context}}"}'
    # Escape for embedding inside a JSON string literal.
    body_text = (
        template
        .replace("{{task}}", json.dumps(task)[1:-1])
        .replace("{{context}}", json.dumps(context)[1:-1])
    )
    try:
        body = json.loads(body_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Request template is not valid JSON after substitution: {e}") from e

    resp = await client.post(spec.endpoint_url, headers=_headers(spec), json=body)
    _raise_for_status(resp)

    if not spec.response_path:
        return resp.text
    return _to_text(_extract_path(resp.json(), spec.response_path))


def _a2a_text(result: Dict[str, Any]) -> str:
    """Pull text out of an A2A Message or Task result."""
    def parts_text(parts: Any) -> str:
        return "\n".join(
            p.get("text", "") for p in (parts or []) if isinstance(p, dict) and p.get("text")
        )

    if result.get("kind") == "message" or "parts" in result:
        return parts_text(result.get("parts"))

    chunks = [parts_text(a.get("parts")) for a in result.get("artifacts") or []]
    text = "\n".join(c for c in chunks if c)
    if text:
        return text
    return parts_text(((result.get("status") or {}).get("message") or {}).get("parts"))


async def _call_a2a(client: httpx.AsyncClient, spec: ExternalAgentSpec, task: str, context: str) -> str:
    async def rpc(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        resp = await client.post(
            spec.endpoint_url,
            headers=_headers(spec),
            json={"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params},
        )
        _raise_for_status(resp)
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(f"A2A error: {data['error']}")
        return data.get("result") or {}

    result = await rpc("message/send", {
        "message": {
            "role": "user",
            "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": _compose_user_content(task, context)}],
        },
    })

    deadline = time.monotonic() + max(1000, spec.timeout_ms) / 1000.0
    while result.get("kind") == "task":
        state = ((result.get("status") or {}).get("state") or "").lower()
        if state in A2A_FINAL_STATES:
            if state != "completed":
                raise RuntimeError(f"A2A task ended in state '{state}': {_a2a_text(result)}")
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"A2A task still '{state}' after {spec.timeout_ms} ms")
        await asyncio.sleep(1.0)
        result = await rpc("tasks/get", {"id": result.get("id")})

    return _a2a_text(result)


_ADAPTERS = {"openai": _call_openai, "rest": _call_rest, "a2a": _call_a2a}


# ── Public entry point ────────────────────────────────────────────────────────

async def invoke_external_agent(
    spec: ExternalAgentSpec, task: str, context: str,
) -> Tuple[str, Dict[str, Any]]:
    """Run the task on the remote agent. Never raises; errors come back as text."""
    adapter = _ADAPTERS.get(spec.protocol)
    retries = max(0, int(spec.max_retries or 0))
    backoff_ms = max(0, int(spec.retry_backoff_ms or 0))
    timeout_s = max(1000, int(spec.timeout_ms or 45000)) / 1000.0
    telemetry: Dict[str, Any] = {
        "attempt_count": 1,
        "used_fallback": False,
        "effective_provider": f"external:{spec.protocol}",
        "effective_model": spec.model or (urlparse(spec.endpoint_url).hostname or ""),
    }

    try:
        if adapter is None:
            raise ValueError(f"Unsupported protocol '{spec.protocol}'")
        await validate_endpoint(spec.endpoint_url)
    except Exception as e:
        return f"{ERROR_PREFIX}]: {e}", telemetry

    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 2):
        telemetry["attempt_count"] = attempt
        try:
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
                return await adapter(client, spec, task, context), telemetry
        except Exception as e:
            last_error = e
            if attempt <= retries and backoff_ms > 0:
                await asyncio.sleep((backoff_ms * attempt) / 1000.0)

    return f"{ERROR_PREFIX}]: {type(last_error).__name__}: {last_error}", telemetry
