"""
bedrock.py — our backend for AWS Bedrock's Converse API, on boto3.

The gateway speaks OpenAI chat messages and tool schemas; this backend converts to Bedrock's
``converse`` / ``converse_stream`` shape at the edge, then maps streamed deltas back to Chunk.
"""

import asyncio
import json
import os
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from llm.base import Chunk, LLMError, LLMRequest, LLMResponse, ToolCallDelta, Usage

DEFAULT_REGION = "us-east-1"
CONNECT_TIMEOUT_S = 10
DEFAULT_TIMEOUT_S = 600

STOP_REASONS = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "guardrail_intervened": "content_filter",
    "content_filtered": "content_filter",
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


def _user_blocks(content: Any) -> List[Dict[str, Any]]:
    text = _text_of(content)
    return [{"text": text}] if text else []


def convert_messages(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []

    def user_turn() -> List[Dict[str, Any]]:
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
                user_turn().append({"text": text})
            else:
                system_parts.append(text)
        elif role == "user":
            blocks = _user_blocks(m.get("content"))
            if blocks:
                user_turn().extend(blocks)
        elif role == "assistant":
            blocks: List[Dict[str, Any]] = []
            text = _text_of(m.get("content"))
            if text:
                blocks.append({"text": text})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                blocks.append({
                    "toolUse": {
                        "toolUseId": tc.get("id") or "",
                        "name": fn.get("name") or "",
                        "input": _tool_input(fn.get("arguments")),
                    }
                })
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            result = _text_of(m.get("content"))
            block: Dict[str, Any] = {"toolUseId": m.get("tool_call_id") or "", "content": []}
            if result:
                block["content"].append({"text": result})
            user_turn().append({"toolResult": block})
    system = [{"text": text} for text in system_parts] if system_parts else []
    return system, out


def convert_tools(tools: Optional[List[Dict[str, Any]]], tool_choice: Optional[str]) -> Optional[Dict[str, Any]]:
    specs = []
    for t in tools or []:
        fn = t.get("function") if t.get("type") == "function" else t
        if not fn or not fn.get("name"):
            continue
        spec: Dict[str, Any] = {
            "name": fn["name"],
            "inputSchema": {"json": fn.get("parameters") or {"type": "object", "properties": {}}},
        }
        if fn.get("description"):
            spec["description"] = fn["description"]
        specs.append({"toolSpec": spec})
    if not specs:
        return None

    cfg: Dict[str, Any] = {"tools": specs}
    choice = (tool_choice or "").strip().lower()
    if choice in ("auto", "required"):
        cfg["toolChoice"] = {"auto": {}}
    elif choice and choice != "none":
        cfg["toolChoice"] = {"tool": {"name": choice}}
    return cfg


def request_params(req: LLMRequest) -> Dict[str, Any]:
    system, messages = convert_messages(req.messages)
    params: Dict[str, Any] = {"modelId": req.model, "messages": messages}
    if system:
        params["system"] = system
    inference: Dict[str, Any] = {}
    if req.max_tokens is not None:
        inference["maxTokens"] = req.max_tokens
    if req.temperature is not None:
        inference["temperature"] = req.temperature
    if req.top_p is not None:
        inference["topP"] = req.top_p
    if inference:
        params["inferenceConfig"] = inference
    tools = convert_tools(req.tools, req.tool_choice)
    if tools:
        params["toolConfig"] = tools
    return params


def _usage(u: Optional[Dict[str, Any]]) -> Optional[Usage]:
    if not u:
        return None
    prompt = u.get("inputTokens") or 0
    completion = u.get("outputTokens") or 0
    total = u.get("totalTokens")
    return Usage(prompt_tokens=prompt, completion_tokens=completion,
                 total_tokens=(total if total is not None else prompt + completion))


_RETRYABLE_CODES = {"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"}


def _error(e: Exception) -> LLMError:
    if isinstance(e, ClientError):
        err = e.response.get("Error", {})
        meta = e.response.get("ResponseMetadata", {})
        code = (err.get("Code") or "").strip()
        message = (err.get("Message") or str(e)).strip()[:500]
        status = meta.get("HTTPStatusCode")
        status = status if isinstance(status, int) else None
        retryable = code in _RETRYABLE_CODES or status in (408, 409, 429) or (status or 0) >= 500
        where = f"returned HTTP {status}" if status else "call failed"
        return LLMError(f"bedrock {where}: {message}", provider="bedrock", status=status, retryable=retryable)
    if isinstance(e, BotoCoreError):
        return LLMError(f"Can't reach bedrock ({e})", provider="bedrock", retryable=True)
    return LLMError(f"bedrock call failed ({type(e).__name__}: {e})", provider="bedrock")


class BedrockStream:
    def __init__(self, raw_stream: Any):
        self._raw_stream = iter(raw_stream)
        self.usage: Optional[Usage] = None

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        tool_index: Dict[int, int] = {}
        while True:
            has_event, event = await asyncio.to_thread(self._next)
            if not has_event:
                return
            if "contentBlockStart" in event:
                block = event["contentBlockStart"]
                idx = int(block.get("contentBlockIndex", 0))
                start = block.get("start") or {}
                tool = start.get("toolUse") or {}
                if tool.get("toolUseId") or tool.get("name"):
                    tool_index[idx] = len(tool_index)
                    yield Chunk(tool_calls=[ToolCallDelta(index=tool_index[idx],
                                                          id=tool.get("toolUseId") or "",
                                                          name=tool.get("name") or "")])
                elif start.get("text"):
                    yield Chunk(text=start.get("text") or "")
            elif "contentBlockDelta" in event:
                block = event["contentBlockDelta"]
                idx = int(block.get("contentBlockIndex", 0))
                delta = block.get("delta") or {}
                if delta.get("text"):
                    yield Chunk(text=delta.get("text") or "")
                tool = delta.get("toolUse") or {}
                if idx in tool_index and "input" in tool:
                    value = tool.get("input")
                    if isinstance(value, str):
                        arguments = value
                    elif value is None:
                        arguments = ""
                    else:
                        arguments = json.dumps(value, separators=(",", ":"))
                    if arguments:
                        yield Chunk(tool_calls=[ToolCallDelta(index=tool_index[idx], arguments=arguments)])
            elif "messageStop" in event:
                reason = (event["messageStop"] or {}).get("stopReason")
                yield Chunk(finish_reason=STOP_REASONS.get(reason, "stop") if reason else None, usage=self.usage)
            elif "metadata" in event:
                self.usage = _usage((event["metadata"] or {}).get("usage"))
            else:
                key = next((k for k in event.keys() if k.endswith("Exception")), "")
                if key:
                    payload = event.get(key) or {}
                    message = (payload.get("message") or str(payload) or key).strip()[:500]
                    retryable = key in ("throttlingException", "serviceUnavailableException")
                    raise LLMError(f"bedrock stream failed: {message}",
                                   provider="bedrock", retryable=retryable)

    def _next(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        try:
            return True, next(self._raw_stream)
        except StopIteration:
            return False, None


class BedrockBackend:
    id = "bedrock"

    def __init__(self, client_factory: Optional[Any] = None):
        self.client_factory = client_factory

    def supports(self, provider: str) -> bool:
        return (provider or "").lower() == "bedrock"

    def _client(self, req: LLMRequest):
        if self.client_factory:
            return self.client_factory(req)
        timeout = req.timeout_s if req.timeout_s is not None else DEFAULT_TIMEOUT_S
        config = Config(connect_timeout=CONNECT_TIMEOUT_S, read_timeout=timeout, retries={"max_attempts": 1})
        kwargs: Dict[str, Any] = {
            "service_name": "bedrock-runtime",
            "region_name": os.getenv("AWS_DEFAULT_REGION", DEFAULT_REGION),
            "config": config,
        }
        if req.base_url:
            kwargs["endpoint_url"] = req.base_url
        if req.api_key:
            kwargs["aws_access_key_id"] = req.api_key
            if os.getenv("AWS_SECRET_ACCESS_KEY"):
                kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY")
            if os.getenv("AWS_SESSION_TOKEN"):
                kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN")
        return boto3.client(**kwargs)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        client = self._client(req)
        try:
            raw = await asyncio.to_thread(client.converse, **request_params(req))
        except Exception as e:
            raise _error(e) from e
        output = ((raw.get("output") or {}).get("message") or {}).get("content") or []
        text = "".join((part.get("text") or "") for part in output if isinstance(part, dict))
        reason = (raw.get("stopReason") or "").strip()
        return LLMResponse(text=text, finish_reason=STOP_REASONS.get(reason, "stop"), usage=_usage(raw.get("usage")))

    async def stream(self, req: LLMRequest) -> BedrockStream:
        client = self._client(req)
        try:
            raw = await asyncio.to_thread(client.converse_stream, **request_params(req))
        except Exception as e:
            raise _error(e) from e
        return BedrockStream(raw.get("stream") or [])
