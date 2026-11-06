"""
anthropic.py — our backend for Anthropic's Messages API, on the official ``anthropic`` SDK.

The gateway speaks the OpenAI chat format; this module converts at its edge:

- Leading system messages become the top-level ``system``. A system message later in the
  conversation (the runtime's grounding / format reminders after tool results) is appended
  as a text block to the user turn it follows, which every Claude model accepts.
- ``role: "tool"`` results become ``tool_result`` blocks; consecutive results share one user
  message, as the API expects for parallel calls.
- Assistant ``tool_calls`` become ``tool_use`` blocks, preceded by the turn's
  ``thinking_blocks``. Current models think by default and reasoning must be sent back
  unchanged with the tool results, so the stream hands finished thinking blocks to the caller
  (``Chunk.thinking_blocks``) and the tool loop returns them on the assistant message.

Requests never carry ``temperature`` / ``top_p``: the SDK sends API version 2026-10-21, which
rejects sampling parameters on every model. ``tool_choice="required"`` is sent as ``auto`` —
forced tool use returns a 400 on current models.

Streamed events map to ``Chunk``s: text deltas, tool calls (index = the call's position among
tool calls, not the content-block index), and usage. Anthropic reports cache reads / writes
apart from ``input_tokens``; ``Usage.prompt_tokens`` adds them back in, as the gateway
expects. The SDK's own retries are off: callers own retries and fallback.
"""

import asyncio
import json
import os
import weakref
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import anthropic

from llm.base import Chunk, LLMError, LLMRequest, LLMResponse, ToolCallDelta, Usage

DEFAULT_MAX_TOKENS = 16000
DEFAULT_TIMEOUT_S = 600.0     # callers enforce the node's timeout with asyncio.wait_for

STOP_REASONS = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "pause_turn": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "refusal": "content_filter",
}


# ── Request conversion ────────────────────────────────────────────────────────

def _text_of(content: Any) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return "" if content is None else str(content)


def _image(url: str) -> Dict[str, Any]:
    if url.startswith("data:") and ";base64," in url:
        media_type, data = url[len("data:"):].split(";base64,", 1)
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
    return {"type": "image", "source": {"type": "url", "url": url}}


def _user_blocks(content: Any) -> List[Dict[str, Any]]:
    if not isinstance(content, list):
        text = _text_of(content)
        return [{"type": "text", "text": text}] if text else []
    blocks = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and part.get("text"):
            blocks.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "image_url":
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            if url:
                blocks.append(_image(url))
    return blocks


def _tool_input(arguments: Any) -> Dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(arguments or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def convert_messages(messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """OpenAI-format messages → (system, Anthropic messages)."""
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []

    def user_turn() -> List[Dict[str, Any]]:
        """The content list of the open user message, starting one if the last isn't a user turn."""
        if not out or out[-1]["role"] != "user":
            out.append({"role": "user", "content": []})
        return out[-1]["content"]

    for m in messages:
        role = m.get("role")
        if role == "system":
            text = _text_of(m.get("content"))
            if not text:
                continue
            if out:
                user_turn().append({"type": "text", "text": text})
            else:
                system_parts.append(text)
        elif role == "user":
            blocks = _user_blocks(m.get("content"))
            if blocks:
                user_turn().extend(blocks)
        elif role == "tool":
            result = _text_of(m.get("content"))
            user_turn().append({"type": "tool_result", "tool_use_id": m.get("tool_call_id") or "",
                                **({"content": result} if result else {})})
        elif role == "assistant":
            blocks = list(m.get("thinking_blocks") or [])
            text = _text_of(m.get("content"))
            if text:
                blocks.append({"type": "text", "text": text})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                blocks.append({"type": "tool_use", "id": tc.get("id") or "", "name": fn.get("name") or "",
                               "input": _tool_input(fn.get("arguments"))})
            if blocks:
                out.append({"role": "assistant", "content": blocks})
    return "\n\n".join(system_parts), out


def convert_tools(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    converted = []
    for t in tools or []:
        fn = t.get("function") if t.get("type") == "function" else t
        if not fn or not fn.get("name"):
            continue
        tool = {"name": fn["name"],
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}}}
        if fn.get("description"):
            tool["description"] = fn["description"]
        converted.append(tool)
    return converted


def params(req: LLMRequest) -> Dict[str, Any]:
    """Keyword arguments for ``messages.create`` (sampling settings deliberately left out)."""
    system, messages = convert_messages(req.messages)
    p: Dict[str, Any] = {"model": req.model, "messages": messages,
                         "max_tokens": req.max_tokens or DEFAULT_MAX_TOKENS}
    if system:
        p["system"] = system
    tools = convert_tools(req.tools)
    if tools:
        p["tools"] = tools
        if req.tool_choice:
            p["tool_choice"] = {"type": "none" if req.tool_choice == "none" else "auto"}
    return p


# ── Responses and errors ──────────────────────────────────────────────────────

def _usage(u: Any, output_tokens: Optional[int] = None) -> Usage:
    cache_read = getattr(u, "cache_read_input_tokens", None) or 0
    cache_write = getattr(u, "cache_creation_input_tokens", None) or 0
    prompt = (getattr(u, "input_tokens", None) or 0) + cache_read + cache_write
    completion = output_tokens if output_tokens is not None else (getattr(u, "output_tokens", None) or 0)
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion,
                 cache_read_tokens=cache_read, cache_write_tokens=cache_write)


RETRYABLE_ERROR_TYPES = {"overloaded_error", "api_error", "rate_limit_error", "timeout_error"}


def _error(e: Exception) -> LLMError:
    if isinstance(e, anthropic.APIStatusError):
        status = e.status_code
        err = e.body.get("error") if isinstance(e.body, dict) else None
        err = err if isinstance(err, dict) else {}
        message = err.get("message") or str(e.message)
        if status == 200:
            # An error event in the middle of a stream: the HTTP status was fine, the type says what broke
            return LLMError(f"anthropic stream failed: {message.strip()[:500]}", provider="anthropic",
                            retryable=err.get("type") in RETRYABLE_ERROR_TYPES)
        return LLMError(f"anthropic returned HTTP {status}: {message.strip()[:500]}",
                        provider="anthropic", status=status,
                        retryable=status in (408, 409, 429) or status >= 500)
    if isinstance(e, anthropic.APITimeoutError):
        return LLMError("anthropic request timed out", provider="anthropic", retryable=True)
    if isinstance(e, anthropic.APIConnectionError):
        return LLMError(f"Can't reach anthropic ({e})", provider="anthropic", retryable=True)
    return LLMError(f"anthropic call failed ({type(e).__name__}: {e})", provider="anthropic")


class AnthropicStream:
    def __init__(self, raw: Any):
        self._raw = raw
        self.usage: Optional[Usage] = None

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        start_usage: Any = None
        tool_index: Dict[int, int] = {}            # content-block index → tool-call position
        thinking: Dict[int, Dict[str, Any]] = {}   # content-block index → block being built
        try:
            async for event in self._raw:
                kind = event.type
                if kind == "message_start":
                    start_usage = event.message.usage
                    self.usage = _usage(start_usage)
                elif kind == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        tool_index[event.index] = len(tool_index)
                        yield Chunk(tool_calls=[ToolCallDelta(index=tool_index[event.index],
                                                              id=block.id, name=block.name)])
                    elif block.type == "thinking":
                        thinking[event.index] = {"type": "thinking", "thinking": block.thinking or "",
                                                 "signature": getattr(block, "signature", "") or ""}
                    elif block.type == "redacted_thinking":
                        thinking[event.index] = {"type": "redacted_thinking", "data": block.data}
                    elif block.type == "text" and block.text:
                        yield Chunk(text=block.text)
                elif kind == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield Chunk(text=delta.text)
                    elif delta.type == "input_json_delta" and event.index in tool_index:
                        yield Chunk(tool_calls=[ToolCallDelta(index=tool_index[event.index],
                                                              arguments=delta.partial_json)])
                    elif delta.type == "thinking_delta" and event.index in thinking:
                        thinking[event.index]["thinking"] += delta.thinking
                    elif delta.type == "signature_delta" and event.index in thinking:
                        thinking[event.index]["signature"] += delta.signature
                elif kind == "content_block_stop":
                    if event.index in thinking:
                        yield Chunk(thinking_blocks=[thinking.pop(event.index)])
                elif kind == "message_delta":
                    # output_tokens here is the running total for the whole message
                    self.usage = _usage(start_usage, getattr(event.usage, "output_tokens", None))
                    reason = event.delta.stop_reason
                    yield Chunk(finish_reason=STOP_REASONS.get(reason, "stop") if reason else None,
                                usage=self.usage)
        except anthropic.APIError as e:
            raise _error(e) from e
        finally:
            await self._raw.close()


class AnthropicBackend:
    id = "anthropic"

    def __init__(self, http_client_factory: Optional[Any] = None):
        # One SDK client per event loop (its connection pool can't be shared across loops);
        # each request derives a copy with its own key and base URL.
        # ``http_client_factory`` returns an httpx2.AsyncClient, for tests.
        self.http_client_factory = http_client_factory
        self._clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, anthropic.AsyncAnthropic]" = \
            weakref.WeakKeyDictionary()

    def supports(self, provider: str) -> bool:
        return (provider or "").lower() == "anthropic"

    def _client(self, req: LLMRequest) -> anthropic.AsyncAnthropic:
        key = req.api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            raise LLMError("No Anthropic API key: set one on the node, in Settings → Secrets, "
                           "or ANTHROPIC_API_KEY on the server", provider="anthropic")
        loop = asyncio.get_running_loop()
        base = self._clients.get(loop)
        if base is None:
            http_client = self.http_client_factory() if self.http_client_factory else None
            base = anthropic.AsyncAnthropic(api_key=key, max_retries=0, timeout=DEFAULT_TIMEOUT_S,
                                            **({"http_client": http_client} if http_client else {}))
            self._clients[loop] = base
        options: Dict[str, Any] = {"api_key": key}
        if req.base_url:
            options["base_url"] = req.base_url
        if req.timeout_s:
            options["timeout"] = req.timeout_s
        return base.with_options(**options)

    async def stream(self, req: LLMRequest) -> AnthropicStream:
        client = self._client(req)
        try:
            raw = await client.messages.create(stream=True, **params(req))
        except anthropic.APIError as e:
            raise _error(e) from e
        return AnthropicStream(raw)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        # Streamed even here: the SDK refuses large max_tokens without streaming
        stream = await self.stream(req)
        text, finish = [], "stop"
        async for chunk in stream:
            text.append(chunk.text)
            finish = chunk.finish_reason or finish
        return LLMResponse(text="".join(text), finish_reason=finish, usage=stream.usage)
