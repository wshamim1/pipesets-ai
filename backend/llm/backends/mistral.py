"""
mistral.py — backend for Mistral's native Chat API (``POST {base}/chat/completions``), on httpx.

The wire shape is close to OpenAI's, so ``openai_compat`` can also serve Mistral; this backend
follows Mistral's own rules instead:
- tool-call ids must be 9 alphanumeric characters — ids from another provider (a fallback model,
  a stored history) are mapped to valid ones, consistently between the call and its result
- reasoning models (Magistral) return ``content`` as a list of chunks — ``thinking`` chunks are
  dropped, ``text`` chunks kept
- streamed usage arrives on the last chunk without ``stream_options`` (not sent)
- ``tool_choice`` takes ``any`` where OpenAI says ``required``
"""

import asyncio
import hashlib
import json
import os
import re
import weakref
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from llm.base import Chunk, LLMError, LLMRequest, LLMResponse, ToolCallDelta, Usage

DEFAULT_BASE = os.getenv("MISTRAL_API_BASE") or "https://api.mistral.ai/v1"
CONNECT_TIMEOUT_S = 10.0
DEFAULT_TIMEOUT_S = 600.0

_VALID_ID = re.compile(r"^[A-Za-z0-9]{9}$")


def tool_call_id(raw: str) -> str:
    """A Mistral-valid id for ``raw``; the same raw id always maps to the same result."""
    if _VALID_ID.match(raw or ""):
        return raw
    return hashlib.sha1((raw or "").encode()).hexdigest()[:9]


def text_of(content: Any) -> str:
    """Text of a message content: a string, or chunks where only ``text`` ones count."""
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return "" if content is None else str(content)


def convert_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in messages:
        m = {k: v for k, v in m.items() if k != "thinking_blocks"}
        if m.get("role") == "assistant" and m.get("tool_calls"):
            m["tool_calls"] = [{**tc, "id": tool_call_id(tc.get("id") or "")} for tc in m["tool_calls"]]
            if m.get("content") is None:
                m["content"] = ""
        elif m.get("role") == "tool":
            m["tool_call_id"] = tool_call_id(m.get("tool_call_id") or "")
        out.append(m)
    return out


def body(req: LLMRequest, stream: bool) -> Dict[str, Any]:
    b: Dict[str, Any] = {"model": req.model, "messages": convert_messages(req.messages)}
    if req.temperature is not None:
        b["temperature"] = req.temperature
    if req.top_p is not None:
        b["top_p"] = req.top_p
    if req.max_tokens is not None:
        b["max_tokens"] = req.max_tokens
    if req.tools:
        b["tools"] = req.tools
    if req.tool_choice:
        choice = req.tool_choice.strip().lower()
        b["tool_choice"] = "any" if choice == "required" else choice
    if stream:
        b["stream"] = True
    return b


def endpoint(base_url: Optional[str]) -> str:
    return f"{(base_url or DEFAULT_BASE).rstrip('/')}/chat/completions"


def _usage(u: Optional[Dict[str, Any]]) -> Optional[Usage]:
    if not u:
        return None
    details = u.get("prompt_tokens_details") or {}
    return Usage(prompt_tokens=u.get("prompt_tokens") or 0, completion_tokens=u.get("completion_tokens") or 0,
                 total_tokens=u.get("total_tokens") or 0, cache_read_tokens=details.get("cached_tokens") or 0)


def _chunk(data: Dict[str, Any]) -> Chunk:
    choices = data.get("choices") or []
    if not choices:
        return Chunk(usage=_usage(data.get("usage")))
    choice = choices[0]
    delta = choice.get("delta") or {}
    tool_calls = []
    for i, tc in enumerate(delta.get("tool_calls") or []):
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        tool_calls.append(ToolCallDelta(index=tc.get("index", i), id=tc.get("id") or "", name=fn.get("name") or "",
                                        arguments=args if isinstance(args, str) else json.dumps(args or {})))
    return Chunk(text=text_of(delta.get("content")), tool_calls=tool_calls,
                 finish_reason=choice.get("finish_reason"), usage=_usage(data.get("usage")))


def _error(status: int, raw: bytes) -> LLMError:
    try:
        data = json.loads(raw)
        err = data.get("error") if isinstance(data.get("error"), dict) else data
        message = err.get("message") or err.get("detail") or raw.decode(errors="replace")
    except (ValueError, AttributeError):
        message = raw.decode(errors="replace")
    if not isinstance(message, str):
        message = json.dumps(message)
    return LLMError(f"mistral returned HTTP {status}: {message.strip()[:500]}",
                    provider="mistral", status=status, retryable=status in (408, 409, 429) or status >= 500)


def _unreachable(url: str, e: Exception) -> LLMError:
    return LLMError(f"Can't reach mistral at {url} ({type(e).__name__}: {e})", provider="mistral", retryable=True)


class MistralStream:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.usage: Optional[Usage] = None

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        try:
            async for line in self._response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                if data.get("error") or data.get("object") == "error":
                    raise _error(self._response.status_code, payload.encode())
                chunk = _chunk(data)
                if chunk.usage:
                    self.usage = chunk.usage
                yield chunk
        except httpx.HTTPError as e:
            raise LLMError(f"mistral stream broke off ({type(e).__name__}: {e})",
                           provider="mistral", retryable=True) from e
        finally:
            await self._response.aclose()


class MistralBackend:
    id = "mistral"

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.transport = transport
        self._clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = \
            weakref.WeakKeyDictionary()

    def supports(self, provider: str) -> bool:
        return (provider or "").lower() == "mistral"

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=httpx.Timeout(DEFAULT_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
                                       transport=self.transport)
            self._clients[loop] = client
        return client

    def _request(self, req: LLMRequest, stream: bool) -> httpx.Request:
        key = req.api_key or os.getenv("MISTRAL_API_KEY", "")
        if not key:
            raise LLMError("No Mistral API key: set one on the node, in Settings → Secrets, "
                           "or MISTRAL_API_KEY on the server", provider="mistral")
        timeout = (httpx.Timeout(req.timeout_s, connect=min(req.timeout_s, CONNECT_TIMEOUT_S))
                   if req.timeout_s else None)
        return self._client().build_request(
            "POST", endpoint(req.base_url),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            json=body(req, stream), **({"timeout": timeout} if timeout else {}),
        )

    async def complete(self, req: LLMRequest) -> LLMResponse:
        request = self._request(req, stream=False)
        try:
            resp = await self._client().send(request)
        except httpx.HTTPError as e:
            raise _unreachable(str(request.url), e) from e
        if resp.status_code != 200:
            raise _error(resp.status_code, resp.content)
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        return LLMResponse(text=text_of((choice.get("message") or {}).get("content")),
                           finish_reason=choice.get("finish_reason") or "stop", usage=_usage(data.get("usage")))

    async def stream(self, req: LLMRequest) -> MistralStream:
        request = self._request(req, stream=True)
        try:
            resp = await self._client().send(request, stream=True)
        except httpx.HTTPError as e:
            raise _unreachable(str(request.url), e) from e
        if resp.status_code != 200:
            raw = await resp.aread()
            await resp.aclose()
            raise _error(resp.status_code, raw)
        return MistralStream(resp)
