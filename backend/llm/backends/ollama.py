"""
ollama.py — backend for Ollama's native chat API (``POST {base}/api/chat``, NDJSON streaming), on httpx.

``openai_compat`` serves Ollama through its OpenAI-compatible ``/v1`` routes; this backend uses
the native API instead, where sampling settings go in ``options`` (``num_predict`` for
max_tokens), tool calls arrive whole (arguments as an object, no id — we number them),
a tool result names its tool (``tool_name``) rather than a call id, images are base64 strings
on the message, and the last line carries ``done_reason`` and the token counts. A thinking
model's ``message.thinking`` is not returned as text.
"""

import asyncio
import json
import os
import weakref
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from llm.base import Chunk, LLMError, LLMRequest, LLMResponse, ToolCallDelta, Usage

DEFAULT_BASE = os.getenv("OLLAMA_API_BASE") or "http://localhost:11434"
CONNECT_TIMEOUT_S = 10.0
DEFAULT_TIMEOUT_S = 600.0


def _text_and_images(content: Any) -> tuple:
    if not isinstance(content, list):
        return ("" if content is None else str(content)), []
    text, images = "", []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text += part.get("text", "")
        elif part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if url.startswith("data:") and "," in url:
                images.append(url.split(",", 1)[1])     # Ollama wants bare base64, no URLs
    return text, images


def _arguments(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def convert_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    tool_name_by_id: Dict[str, str] = {}
    for m in messages:
        role = m.get("role")
        text, images = _text_and_images(m.get("content"))
        msg: Dict[str, Any] = {"role": role, "content": text}
        if images:
            msg["images"] = images
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                if tc.get("id"):
                    tool_name_by_id[tc["id"]] = fn.get("name") or ""
                calls.append({"function": {"name": fn.get("name") or "", "arguments": _arguments(fn.get("arguments"))}})
            msg["tool_calls"] = calls
        elif role == "tool":
            name = m.get("name") or tool_name_by_id.get(m.get("tool_call_id") or "")
            if name:
                msg["tool_name"] = name
        out.append(msg)
    return out


def body(req: LLMRequest, stream: bool) -> Dict[str, Any]:
    b: Dict[str, Any] = {"model": req.model, "messages": convert_messages(req.messages), "stream": stream}
    options: Dict[str, Any] = {}
    if req.temperature is not None:
        options["temperature"] = req.temperature
    if req.top_p is not None:
        options["top_p"] = req.top_p
    if req.max_tokens is not None:
        options["num_predict"] = req.max_tokens
    if options:
        b["options"] = options
    # Ollama has no tool_choice; "none" means don't offer the tools at all
    if req.tools and (req.tool_choice or "").strip().lower() != "none":
        b["tools"] = req.tools
    return b


def endpoint(base_url: Optional[str]) -> str:
    base = (base_url or DEFAULT_BASE).rstrip("/")
    # A base URL saved for the OpenAI-compatible route ends in /v1
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base}/api/chat"


def _usage(data: Dict[str, Any]) -> Optional[Usage]:
    if "prompt_eval_count" not in data and "eval_count" not in data:
        return None
    prompt = int(data.get("prompt_eval_count") or 0)
    completion = int(data.get("eval_count") or 0)
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)


def _finish(data: Dict[str, Any], saw_tool_calls: bool) -> Optional[str]:
    if not data.get("done"):
        return None
    if saw_tool_calls:
        return "tool_calls"
    return "length" if data.get("done_reason") == "length" else "stop"


def _error(status: int, raw: bytes) -> LLMError:
    try:
        message = json.loads(raw).get("error") or raw.decode(errors="replace")
    except (ValueError, AttributeError):
        message = raw.decode(errors="replace")
    return LLMError(f"ollama returned HTTP {status}: {str(message).strip()[:500]}",
                    provider="ollama", status=status, retryable=status in (408, 429) or status >= 500)


def _unreachable(url: str, e: Exception) -> LLMError:
    return LLMError(f"Can't reach ollama at {url} — is the local server running? ({type(e).__name__}: {e})",
                    provider="ollama", retryable=True)


class OllamaStream:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.usage: Optional[Usage] = None
        self._calls = 0

    def chunk(self, data: Dict[str, Any]) -> Chunk:
        message = data.get("message") or {}
        calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            calls.append(ToolCallDelta(index=self._calls, id=tc.get("id") or f"call_{self._calls}",
                                       name=fn.get("name") or "",
                                       arguments=args if isinstance(args, str) else json.dumps(args or {})))
            self._calls += 1
        return Chunk(text=message.get("content") or "", tool_calls=calls,
                     finish_reason=_finish(data, self._calls > 0), usage=_usage(data) if data.get("done") else None)

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        try:
            async for line in self._response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if data.get("error"):
                    raise _error(self._response.status_code if self._response.status_code != 200 else 500,
                                 line.encode())
                chunk = self.chunk(data)
                if chunk.usage:
                    self.usage = chunk.usage
                yield chunk
        except httpx.HTTPError as e:
            raise LLMError(f"ollama stream broke off ({type(e).__name__}: {e})",
                           provider="ollama", retryable=True) from e
        finally:
            await self._response.aclose()


class OllamaBackend:
    id = "ollama"

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.transport = transport
        self._clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = \
            weakref.WeakKeyDictionary()

    def supports(self, provider: str) -> bool:
        return (provider or "").lower() == "ollama"

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=httpx.Timeout(DEFAULT_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
                                       transport=self.transport)
            self._clients[loop] = client
        return client

    def _request(self, req: LLMRequest, stream: bool) -> httpx.Request:
        timeout = (httpx.Timeout(req.timeout_s, connect=min(req.timeout_s, CONNECT_TIMEOUT_S))
                   if req.timeout_s else None)
        headers = {"Content-Type": "application/json"}
        if req.api_key:                       # Ollama behind an authenticating proxy, or ollama.com
            headers["Authorization"] = f"Bearer {req.api_key}"
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
        chunk = OllamaStream(resp).chunk(resp.json())
        return LLMResponse(text=chunk.text, finish_reason=chunk.finish_reason or "stop", usage=chunk.usage)

    async def stream(self, req: LLMRequest) -> OllamaStream:
        request = self._request(req, stream=True)
        try:
            resp = await self._client().send(request, stream=True)
        except httpx.HTTPError as e:
            raise _unreachable(str(request.url), e) from e
        if resp.status_code != 200:
            raw = await resp.aread()
            await resp.aclose()
            raise _error(resp.status_code, raw)
        return OllamaStream(resp)
