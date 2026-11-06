"""
gemini.py — backend for Google's Gemini API (GenerateContent / streamGenerateContent), on httpx.

The gateway uses OpenAI-style messages and tool schemas; this backend converts at the edge.
"""

import asyncio
import json
import os
import weakref
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx

from llm.base import Chunk, LLMError, LLMRequest, LLMResponse, ToolCallDelta, Usage

DEFAULT_BASE = os.getenv("GEMINI_API_BASE") or "https://generativelanguage.googleapis.com/v1beta"
CONNECT_TIMEOUT_S = 10.0
DEFAULT_TIMEOUT_S = 600.0

STOP_REASONS = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
}


def _text_of(content: Any) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return "" if content is None else str(content)


def _tool_input(arguments: Any) -> Dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(arguments or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_output(content: Any) -> Dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        return {"items": content}
    text = _text_of(content).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {"text": text}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def convert_messages(messages: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []
    tool_name_by_id: Dict[str, str] = {}

    def user_turn() -> List[Dict[str, Any]]:
        if not out or out[-1]["role"] != "user":
            out.append({"role": "user", "parts": []})
        return out[-1]["parts"]

    for m in messages:
        role = m.get("role")
        if role == "system":
            text = _text_of(m.get("content")).strip()
            if not text:
                continue
            if out:
                user_turn().append({"text": text})
            else:
                system_parts.append(text)
        elif role == "user":
            text = _text_of(m.get("content")).strip()
            if text:
                user_turn().append({"text": text})
        elif role == "assistant":
            parts: List[Dict[str, Any]] = []
            text = _text_of(m.get("content")).strip()
            if text:
                parts.append({"text": text})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                call_id = tc.get("id") or ""
                name = fn.get("name") or ""
                if call_id and name:
                    tool_name_by_id[call_id] = name
                parts.append({"functionCall": {"name": name, "args": _tool_input(fn.get("arguments"))}})
            if parts:
                out.append({"role": "model", "parts": parts})
        elif role == "tool":
            call_id = m.get("tool_call_id") or ""
            user_turn().append({"functionResponse": {
                "name": tool_name_by_id.get(call_id, call_id or "tool"),
                "response": _tool_output(m.get("content")),
            }})
    system = {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None
    return system, out


def convert_tools(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    decls = []
    for t in tools or []:
        fn = t.get("function") if t.get("type") == "function" else t
        if not fn or not fn.get("name"):
            continue
        decl: Dict[str, Any] = {
            "name": fn["name"],
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        }
        if fn.get("description"):
            decl["description"] = fn["description"]
        decls.append(decl)
    return [{"functionDeclarations": decls}] if decls else []


def body(req: LLMRequest) -> Dict[str, Any]:
    system, contents = convert_messages(req.messages)
    out: Dict[str, Any] = {"contents": contents}
    if system:
        out["systemInstruction"] = system
    cfg: Dict[str, Any] = {}
    if req.temperature is not None:
        cfg["temperature"] = req.temperature
    if req.top_p is not None:
        cfg["topP"] = req.top_p
    if req.max_tokens is not None:
        cfg["maxOutputTokens"] = req.max_tokens
    if cfg:
        out["generationConfig"] = cfg
    tools = convert_tools(req.tools)
    if tools:
        out["tools"] = tools
        if req.tool_choice:
            choice = req.tool_choice.strip().lower()
            if choice in ("none",):
                out["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}
            elif choice in ("auto",):
                out["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
            else:
                out["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}
    return out


def _usage(meta: Optional[Dict[str, Any]]) -> Optional[Usage]:
    if not meta:
        return None
    prompt = meta.get("promptTokenCount") or 0
    completion = meta.get("candidatesTokenCount") or 0
    total = meta.get("totalTokenCount")
    return Usage(prompt_tokens=prompt, completion_tokens=completion,
                 total_tokens=(total if total is not None else prompt + completion))


def _model_path(model: str) -> str:
    return model if (model or "").startswith("models/") else f"models/{model}"


def endpoint(base_url: Optional[str], model: str, stream: bool, api_key: str) -> str:
    method = "streamGenerateContent" if stream else "generateContent"
    base = (base_url or DEFAULT_BASE).rstrip("/")
    path = f"{base}/{_model_path(model)}:{method}"
    q = urlencode({"alt": "sse", "key": api_key}) if stream else urlencode({"key": api_key})
    return f"{path}?{q}"


def _error(status: int, raw: bytes) -> LLMError:
    try:
        err = json.loads(raw).get("error")
        message = (err.get("message") if isinstance(err, dict) else err) or raw.decode(errors="replace")
    except (ValueError, AttributeError):
        message = raw.decode(errors="replace")
    return LLMError(f"gemini returned HTTP {status}: {str(message).strip()[:500]}",
                    provider="gemini", status=status, retryable=status in (408, 409, 429) or status >= 500)


def _unreachable(url: str, e: Exception) -> LLMError:
    return LLMError(f"Can't reach gemini at {url} ({type(e).__name__}: {e})", provider="gemini", retryable=True)


@dataclass(frozen=True)
class ToolCallKey:
    index: int
    name: str


class GeminiStream:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.usage: Optional[Usage] = None
        self._tool_index: Dict[ToolCallKey, int] = {}

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        try:
            async for line in self._response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                chunk = self._chunk(data)
                if chunk.usage:
                    self.usage = chunk.usage
                if chunk.text or chunk.tool_calls or chunk.finish_reason or chunk.usage:
                    yield chunk
        except httpx.HTTPError as e:
            raise LLMError(f"gemini stream broke off ({type(e).__name__}: {e})",
                           provider="gemini", retryable=True) from e
        finally:
            await self._response.aclose()

    def _chunk(self, data: Dict[str, Any]) -> Chunk:
        candidates = data.get("candidates") or []
        text, calls, finish = "", [], None
        for cand in candidates:
            content = cand.get("content") or {}
            parts = content.get("parts") or []
            for part_index, part in enumerate(parts):
                if part.get("text"):
                    text += part["text"]
                fn = part.get("functionCall") or {}
                if fn:
                    name = fn.get("name") or ""
                    key = ToolCallKey(index=part_index, name=name)
                    idx = self._tool_index.setdefault(key, len(self._tool_index))
                    args = fn.get("args")
                    arg_str = (args if isinstance(args, str) else json.dumps(args or {}, separators=(",", ":")))
                    calls.append(ToolCallDelta(index=idx, id=f"call_{idx}", name=name, arguments=arg_str))
            reason = cand.get("finishReason")
            if reason:
                finish = STOP_REASONS.get(reason, "stop")
        return Chunk(text=text, tool_calls=calls, finish_reason=finish, usage=_usage(data.get("usageMetadata")))


class GeminiBackend:
    id = "gemini"

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.transport = transport
        self._clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = \
            weakref.WeakKeyDictionary()

    def supports(self, provider: str) -> bool:
        return (provider or "").lower() == "gemini"

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=httpx.Timeout(DEFAULT_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
                                       transport=self.transport)
            self._clients[loop] = client
        return client

    def _key(self, req: LLMRequest) -> str:
        key = req.api_key or os.getenv("GEMINI_API_KEY", "")
        if not key:
            raise LLMError("No Gemini API key: set one on the node, in Settings → Secrets, "
                           "or GEMINI_API_KEY on the server", provider="gemini")
        return key

    async def complete(self, req: LLMRequest) -> LLMResponse:
        key = self._key(req)
        url = endpoint(req.base_url, req.model, False, key)
        timeout = (httpx.Timeout(req.timeout_s, connect=min(req.timeout_s, CONNECT_TIMEOUT_S))
                   if req.timeout_s else None)
        request = self._client().build_request(
            "POST", url, headers={"Content-Type": "application/json"}, json=body(req),
            **({"timeout": timeout} if timeout else {}),
        )
        try:
            resp = await self._client().send(request)
        except httpx.HTTPError as e:
            raise _unreachable(str(request.url), e) from e
        if resp.status_code != 200:
            raise _error(resp.status_code, resp.content)
        data = resp.json()
        chunk = GeminiStream(resp)._chunk(data)
        return LLMResponse(text=chunk.text, finish_reason=chunk.finish_reason or "stop", usage=chunk.usage)

    async def stream(self, req: LLMRequest) -> GeminiStream:
        key = self._key(req)
        url = endpoint(req.base_url, req.model, True, key)
        timeout = (httpx.Timeout(req.timeout_s, connect=min(req.timeout_s, CONNECT_TIMEOUT_S))
                   if req.timeout_s else None)
        request = self._client().build_request(
            "POST", url, headers={"Content-Type": "application/json"}, json=body(req),
            **({"timeout": timeout} if timeout else {}),
        )
        try:
            resp = await self._client().send(request, stream=True)
        except httpx.HTTPError as e:
            raise _unreachable(str(request.url), e) from e
        if resp.status_code != 200:
            raw = await resp.aread()
            await resp.aclose()
            raise _error(resp.status_code, raw)
        return GeminiStream(resp)
