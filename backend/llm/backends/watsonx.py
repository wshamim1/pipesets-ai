"""
watsonx.py — our backend for IBM watsonx.ai's text chat API (``/ml/v1/text/chat``, and
``/ml/v1/text/chat_stream`` for streaming), on httpx.

watsonx doesn't take the API key itself as a bearer token: it takes a short-lived IBM Cloud
IAM access token, exchanged for the key once and reused until shortly before it expires. The
region URL comes from the node / Settings → Model backends / ``WATSONX_URL``; the project from
``WATSONX_PROJECT_ID``.

The gateway uses OpenAI-style messages and tool schemas; watsonx's chat API accepts the same
message objects, so only sampling fields are renamed (they stay top-level here).
"""

import asyncio
import json
import os
import time
import weakref
from typing import Any, AsyncIterator, Dict, Optional, Tuple

import httpx

from llm.base import Chunk, LLMError, LLMRequest, LLMResponse, ToolCallDelta, Usage

DEFAULT_BASE = os.getenv("WATSONX_URL") or "https://us-south.ml.cloud.ibm.com"
IAM_URL = os.getenv("WATSONX_IAM_URL") or "https://iam.cloud.ibm.com/identity/token"
API_VERSION = os.getenv("WATSONX_API_VERSION") or "2024-03-13"
CONNECT_TIMEOUT_S = 10.0
DEFAULT_TIMEOUT_S = 600.0     # callers enforce the node's timeout with asyncio.wait_for
TOKEN_MARGIN_S = 60.0         # refresh this long before IAM says the token expires

STOP_REASONS = {
    "stop": "stop",
    "eos_token": "stop",
    "length": "length",
    "max_tokens": "length",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "content_filter": "content_filter",
}


def _key(req: LLMRequest) -> str:
    key = req.api_key or os.getenv("WATSONX_APIKEY") or os.getenv("WATSONX_API_KEY") or ""
    if not key:
        raise LLMError("No watsonx.ai API key: set one on the node, in Settings → Secrets, "
                       "or WATSONX_APIKEY on the server", provider="watsonx")
    return key


def _project() -> str:
    project = os.getenv("WATSONX_PROJECT_ID", "").strip()
    if not project:
        raise LLMError("watsonx.ai needs WATSONX_PROJECT_ID (the project every call runs in)",
                       provider="watsonx")
    return project


def endpoint(base_url: Optional[str], stream: bool = False) -> str:
    """The chat path, or the dedicated streaming path (watsonx has a separate one)."""
    base = (base_url or DEFAULT_BASE).rstrip("/")
    leaf = "chat_stream" if stream else "chat"
    path = f"{base}/text/{leaf}" if base.endswith("/ml/v1") else f"{base}/ml/v1/text/{leaf}"
    return f"{path}?version={API_VERSION}"


def body(req: LLMRequest) -> Dict[str, Any]:
    # thinking_blocks are Anthropic's; watsonx rejects unknown message keys
    messages = [{k: v for k, v in m.items() if k != "thinking_blocks"} if "thinking_blocks" in m else m
                for m in req.messages]
    b: Dict[str, Any] = {"model_id": req.model, "messages": messages, "project_id": _project()}
    for name in ("temperature", "max_tokens", "top_p", "tools", "tool_choice"):
        value = getattr(req, name)
        if value is not None:
            b[name] = value
    return b


def _usage(u: Optional[Dict[str, Any]]) -> Optional[Usage]:
    if not u:
        return None
    prompt = u.get("prompt_tokens") or u.get("input_tokens") or 0
    completion = u.get("completion_tokens") or u.get("output_tokens") or 0
    total = u.get("total_tokens")
    return Usage(prompt_tokens=prompt, completion_tokens=completion,
                 total_tokens=(total if total is not None else prompt + completion))


def _chunk(data: Dict[str, Any]) -> Chunk:
    choices = data.get("choices") or []
    if not choices:
        return Chunk(usage=_usage(data.get("usage")))
    choice = choices[0]
    delta = choice.get("delta") or choice.get("message") or {}
    calls = []
    for tc in delta.get("tool_calls") or []:
        fn = tc.get("function") or {}
        calls.append(ToolCallDelta(index=tc.get("index", 0), id=tc.get("id") or "",
                                   name=fn.get("name") or "", arguments=fn.get("arguments") or ""))
    reason = choice.get("finish_reason")
    return Chunk(text=delta.get("content") or "", tool_calls=calls,
                 finish_reason=STOP_REASONS.get(reason, reason) if reason else None,
                 usage=_usage(data.get("usage")))


def _message_of(raw: bytes) -> str:
    """watsonx errors are ``{"errors": [{"message": ...}]}``; IAM uses ``errorMessage``."""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.decode(errors="replace")
    if not isinstance(data, dict):
        return str(data)[:500]
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0] if isinstance(errors[0], dict) else {"message": errors[0]}
        return str(first.get("message") or first.get("code") or first)
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    if error:
        return str(error)
    for key in ("errorMessage", "message", "errorCode"):
        if data.get(key):
            return str(data[key])
    return json.dumps(data)[:500] if data else raw.decode(errors="replace")


def _error(status: int, raw: bytes, what: str = "watsonx") -> LLMError:
    return LLMError(f"{what} returned HTTP {status}: {_message_of(raw).strip()[:500]}",
                    provider="watsonx", status=status,
                    retryable=status in (408, 409, 429) or status >= 500)


def _unreachable(url: str, e: Exception) -> LLMError:
    return LLMError(f"Can't reach {url} ({type(e).__name__}: {e})", provider="watsonx", retryable=True)


class WatsonXStream:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.usage: Optional[Usage] = None

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        try:
            async for line in self._response.aiter_lines():
                if not line.startswith("data:"):
                    continue            # SSE comments / keep-alives / event: lines
                payload = line[len("data:"):].strip()
                if not payload or payload == "[DONE]":
                    if payload == "[DONE]":
                        break
                    continue
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                if data.get("error") or data.get("errors"):
                    raise LLMError(f"watsonx stream failed: {_message_of(payload.encode()).strip()[:500]}",
                                   provider="watsonx", retryable=True)
                chunk = _chunk(data)
                if chunk.usage:
                    self.usage = chunk.usage
                if chunk.text or chunk.tool_calls or chunk.finish_reason or chunk.usage:
                    yield chunk
        except httpx.HTTPError as e:
            raise LLMError(f"watsonx stream broke off ({type(e).__name__}: {e})",
                           provider="watsonx", retryable=True) from e
        finally:
            await self._response.aclose()


class WatsonXBackend:
    id = "watsonx"

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.transport = transport
        # One pooled client per event loop (a client can't be shared across loops).
        self._clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = \
            weakref.WeakKeyDictionary()
        # key -> (access token, monotonic expiry). Shared by every request for the same key.
        self._tokens: Dict[str, Tuple[str, float]] = {}

    def supports(self, provider: str) -> bool:
        return (provider or "").lower() == "watsonx"

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=httpx.Timeout(DEFAULT_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
                                       transport=self.transport)
            self._clients[loop] = client
        return client

    async def _token(self, req: LLMRequest) -> str:
        key = _key(req)
        cached = self._tokens.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]

        request = self._client().build_request(
            "POST", IAM_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": key},
        )
        try:
            resp = await self._client().send(request)
        except httpx.HTTPError as e:
            raise _unreachable(IAM_URL, e) from e
        if resp.status_code != 200:
            raise _error(resp.status_code, resp.content, what="IBM Cloud IAM")
        data = resp.json()
        token = data.get("access_token") or ""
        if not token:
            raise LLMError("IBM Cloud IAM returned no access token", provider="watsonx")
        ttl = float(data.get("expires_in") or 3600)
        self._tokens[key] = (token, time.monotonic() + max(0.0, ttl - TOKEN_MARGIN_S))
        return token

    async def _post(self, req: LLMRequest, stream: bool) -> httpx.Response:
        _key(req)                        # a missing key fails before anything is sent
        payload = body(req)              # validates the project before exchanging a token
        token = await self._token(req)
        timeout = (httpx.Timeout(req.timeout_s, connect=min(req.timeout_s, CONNECT_TIMEOUT_S))
                   if req.timeout_s else None)
        url = endpoint(req.base_url, stream)
        request = self._client().build_request(
            "POST", url,
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "Authorization": f"Bearer {token}"},
            json=payload, **({"timeout": timeout} if timeout else {}),
        )
        try:
            resp = await self._client().send(request, stream=stream)
        except httpx.HTTPError as e:
            raise _unreachable(url, e) from e
        if resp.status_code != 200:
            raw = await resp.aread()
            await resp.aclose()
            raise _error(resp.status_code, raw)
        return resp

    async def complete(self, req: LLMRequest) -> LLMResponse:
        resp = await self._post(req, stream=False)
        chunk = _chunk(resp.json())
        return LLMResponse(text=chunk.text, finish_reason=chunk.finish_reason or "stop", usage=chunk.usage)

    async def stream(self, req: LLMRequest) -> WatsonXStream:
        return WatsonXStream(await self._post(req, stream=True))
