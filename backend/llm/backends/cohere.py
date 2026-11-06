"""
cohere.py — backend for Cohere's native Chat API v2 (``POST {base}/v2/chat``, SSE streaming), on httpx.

Cohere also serves an OpenAI-compatible endpoint (``openai_compat`` uses it); this backend talks
the native API instead: typed stream events (content-delta, tool-call-start / -delta, message-end),
``p`` for top_p, upper-case finish reasons and ``billed_units`` usage — the tokens Cohere charges,
which is what we price. Messages and tools stay in OpenAI format until the edge.
"""

import asyncio
import json
import os
import weakref
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from llm.base import Chunk, LLMError, LLMRequest, LLMResponse, ToolCallDelta, Usage

DEFAULT_BASE = os.getenv("COHERE_NATIVE_API_BASE") or "https://api.cohere.com"
CONNECT_TIMEOUT_S = 10.0
DEFAULT_TIMEOUT_S = 600.0

STOP_REASONS = {
    "COMPLETE": "stop",
    "STOP_SEQUENCE": "stop",
    "MAX_TOKENS": "length",
    "TOOL_CALL": "tool_calls",
    "ERROR": "error",
    "TIMEOUT": "error",
}


def _text_of(content: Any) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return "" if content is None else str(content)


def convert_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role in ("system", "user"):
            text = _text_of(m.get("content"))
            if text.strip():
                out.append({"role": role, "content": text})
        elif role == "assistant":
            msg: Dict[str, Any] = {"role": "assistant"}
            text = _text_of(m.get("content"))
            calls = [{"id": tc.get("id") or f"call_{i}", "type": "function",
                      "function": {"name": (tc.get("function") or {}).get("name") or "",
                                   "arguments": (tc.get("function") or {}).get("arguments") or "{}"}}
                     for i, tc in enumerate(m.get("tool_calls") or [])]
            if calls:
                msg["tool_calls"] = calls
                # v2 rejects text content next to tool calls; the reasoning goes in tool_plan
                if text.strip():
                    msg["tool_plan"] = text
            elif text.strip():
                msg["content"] = text
            else:
                continue
            out.append(msg)
        elif role == "tool":
            content = m.get("content")
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id") or "",
                        "content": content if isinstance(content, str) else json.dumps(content)})
    return out


def body(req: LLMRequest, stream: bool) -> Dict[str, Any]:
    b: Dict[str, Any] = {"model": req.model, "messages": convert_messages(req.messages)}
    if req.temperature is not None:
        b["temperature"] = req.temperature
    if req.top_p is not None:
        # Cohere's range is 0.01–0.99; nodes default to 1.0
        b["p"] = min(max(req.top_p, 0.01), 0.99)
    if req.max_tokens is not None:
        b["max_tokens"] = req.max_tokens
    if req.tools:
        b["tools"] = [t for t in req.tools if t.get("type") == "function"]
        choice = (req.tool_choice or "").strip().lower()
        if choice == "none":
            b["tool_choice"] = "NONE"
        elif choice in ("required", "any"):
            b["tool_choice"] = "REQUIRED"
    if stream:
        b["stream"] = True
    return b


def endpoint(base_url: Optional[str]) -> str:
    base = (base_url or DEFAULT_BASE).rstrip("/")
    # A base URL saved for the OpenAI-compatible route points at /compatibility/v1
    if base.endswith("/compatibility/v1"):
        base = base[: -len("/compatibility/v1")]
    if base.endswith("/v2"):
        return f"{base}/chat"
    return f"{base}/v2/chat"


def _usage(u: Optional[Dict[str, Any]]) -> Optional[Usage]:
    if not u:
        return None
    counts = u.get("billed_units") or u.get("tokens") or {}
    prompt = int(counts.get("input_tokens") or 0)
    completion = int(counts.get("output_tokens") or 0)
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)


def _error(status: int, raw: bytes) -> LLMError:
    try:
        data = json.loads(raw)
        message = data.get("message") or data.get("error") or raw.decode(errors="replace")
    except (ValueError, AttributeError):
        message = raw.decode(errors="replace")
    return LLMError(f"cohere returned HTTP {status}: {str(message).strip()[:500]}",
                    provider="cohere", status=status, retryable=status in (408, 409, 429) or status >= 500)


def _unreachable(url: str, e: Exception) -> LLMError:
    return LLMError(f"Can't reach cohere at {url} ({type(e).__name__}: {e})", provider="cohere", retryable=True)


def event_chunk(data: Dict[str, Any]) -> Optional[Chunk]:
    """One v2 stream event as a Chunk, or None for events that carry nothing we use."""
    kind = data.get("type")
    message = (data.get("delta") or {}).get("message") or {}
    if kind == "content-delta":
        return Chunk(text=((message.get("content") or {}).get("text") or ""))
    if kind in ("tool-call-start", "tool-call-delta"):
        tc = message.get("tool_calls") or {}
        fn = tc.get("function") or {}
        return Chunk(tool_calls=[ToolCallDelta(index=data.get("index") or 0, id=tc.get("id") or "",
                                               name=fn.get("name") or "", arguments=fn.get("arguments") or "")])
    if kind == "message-end":
        delta = data.get("delta") or {}
        reason = delta.get("finish_reason")
        return Chunk(finish_reason=STOP_REASONS.get(reason, "stop") if reason else None,
                     usage=_usage(delta.get("usage")))
    return None


class CohereStream:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.usage: Optional[Usage] = None

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        try:
            async for line in self._response.aiter_lines():
                if not line.startswith("data:"):
                    continue          # event: lines, keep-alives
                payload = line[len("data:"):].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                if data.get("type") == "error" or (data.get("message") and not data.get("type")):
                    raise _error(self._response.status_code or 500, payload.encode())
                chunk = event_chunk(data)
                if chunk is None:
                    continue
                if chunk.usage:
                    self.usage = chunk.usage
                yield chunk
        except httpx.HTTPError as e:
            raise LLMError(f"cohere stream broke off ({type(e).__name__}: {e})",
                           provider="cohere", retryable=True) from e
        finally:
            await self._response.aclose()


class CohereBackend:
    id = "cohere"

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.transport = transport
        self._clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = \
            weakref.WeakKeyDictionary()

    def supports(self, provider: str) -> bool:
        return (provider or "").lower() == "cohere"

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=httpx.Timeout(DEFAULT_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
                                       transport=self.transport)
            self._clients[loop] = client
        return client

    def _request(self, req: LLMRequest, stream: bool) -> httpx.Request:
        key = req.api_key or os.getenv("COHERE_API_KEY", "") or os.getenv("CO_API_KEY", "")
        if not key:
            raise LLMError("No Cohere API key: set one on the node, in Settings → Secrets, "
                           "or COHERE_API_KEY on the server", provider="cohere")
        timeout = (httpx.Timeout(req.timeout_s, connect=min(req.timeout_s, CONNECT_TIMEOUT_S))
                   if req.timeout_s else None)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        if stream:
            headers["Accept"] = "text/event-stream"
        return self._client().build_request(
            "POST", endpoint(req.base_url), headers=headers, json=body(req, stream),
            **({"timeout": timeout} if timeout else {}),
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
        reason = data.get("finish_reason")
        return LLMResponse(
            text=_text_of((data.get("message") or {}).get("content")),
            finish_reason=STOP_REASONS.get(reason, "stop") if reason else "stop",
            usage=_usage(data.get("usage")),
        )

    async def stream(self, req: LLMRequest) -> CohereStream:
        request = self._request(req, stream=True)
        try:
            resp = await self._client().send(request, stream=True)
        except httpx.HTTPError as e:
            raise _unreachable(str(request.url), e) from e
        if resp.status_code != 200:
            raw = await resp.aread()
            await resp.aclose()
            raise _error(resp.status_code, raw)
        return CohereStream(resp)
