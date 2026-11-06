"""Our Anthropic backend (llm/backends/anthropic.py) against a stand-in Messages API: request
conversion from the OpenAI chat format, streamed text / thinking / tool calls / usage, errors,
backend selection — and a full tool-calling run through services/llm_runner.run_stream that
sends the thinking block back with the tool result.

httpx2.MockTransport stands in for the network (the SDK is built on httpx2). The payloads
follow Anthropic's documented streaming format; they are written by hand, not recorded.
"""
import asyncio
import json

import httpx2
import pytest

import llm
from llm import pricing
from llm.backends.anthropic import AnthropicBackend, convert_messages, params
from models import LLMConfig, PromptRunRequest
from services.llm_runner import run_stream


def req(**fields):
    fields.setdefault("provider", "anthropic")
    fields.setdefault("model", "claude-haiku-5-5")
    fields.setdefault("messages", [{"role": "user", "content": "hi"}])
    fields.setdefault("api_key", "sk-ant-test")
    return llm.LLMRequest(**fields)


def sse(*events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def message_start(input_tokens=10, cache_read=0, cache_write=0):
    return {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": 1, "cache_read_input_tokens": cache_read,
                  "cache_creation_input_tokens": cache_write}}}


def block_start(index, block):
    return {"type": "content_block_start", "index": index, "content_block": block}


def block_delta(index, delta):
    return {"type": "content_block_delta", "index": index, "delta": delta}


def block_stop(index):
    return {"type": "content_block_stop", "index": index}


def message_delta(stop_reason, output_tokens):
    return {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens}}


def text_reply(text, stop="end_turn", input_tokens=10, output_tokens=3, cache_read=0):
    return [message_start(input_tokens, cache_read), block_start(0, {"type": "text", "text": ""}),
            block_delta(0, {"type": "text_delta", "text": text}), block_stop(0),
            message_delta(stop, output_tokens), {"type": "message_stop"}]


class Server:
    """Stand-in Messages API: records requests, replies from a queue."""

    def __init__(self):
        self.requests = []
        self.replies = []
        self.raise_error = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.raise_error:
            raise self.raise_error
        status, content, ctype = self.replies.pop(0)
        return httpx2.Response(status, content=content, headers={"content-type": ctype})

    def reply_sse(self, *events):
        self.replies.append((200, sse(*events), "text/event-stream"))

    def reply_error(self, status, err_type, message):
        body = {"type": "error", "error": {"type": err_type, "message": message}}
        self.replies.append((status, json.dumps(body).encode(), "application/json"))

    @property
    def last_json(self):
        return json.loads(self.requests[-1].content)


@pytest.fixture(autouse=True)
def _no_backend_env(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "LLM_BACKEND", "LLM_BACKEND_ANTHROPIC"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def server():
    return Server()


@pytest.fixture
def backend(server):
    return AnthropicBackend(lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(server.handler)))


async def _read(stream):
    return [c async for c in stream]


def read(stream):
    return asyncio.run(_read(stream))


def test_message_conversion():
    system, messages = convert_messages([
        {"role": "system", "content": "Be brief."},
        {"role": "system", "content": "Use tools."},
        {"role": "user", "content": [{"type": "text", "text": "What is this?"},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
        {"role": "assistant", "content": None,
         "thinking_blocks": [{"type": "thinking", "thinking": "", "signature": "sig"}],
         "tool_calls": [{"id": "toolu_1", "type": "function", "function": {"name": "a", "arguments": '{"input": "x"}'}},
                        {"id": "toolu_2", "type": "function", "function": {"name": "b", "arguments": "not json"}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "result A"},
        {"role": "tool", "tool_call_id": "toolu_2", "content": ""},
        {"role": "system", "content": "Answer in JSON."},
    ])
    assert system == "Be brief.\n\nUse tools."
    assert messages == [
        {"role": "user", "content": [
            {"type": "text", "text": "What is this?"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}]},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "tool_use", "id": "toolu_1", "name": "a", "input": {"input": "x"}},
            {"type": "tool_use", "id": "toolu_2", "name": "b", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "result A"},
            {"type": "tool_result", "tool_use_id": "toolu_2"},
            {"type": "text", "text": "Answer in JSON."}]},
    ], "parallel results share one user turn; a later system message joins it as text"


def test_request_params():
    tools = [{"type": "function", "function": {"name": "calculator", "description": "Math",
                                               "parameters": {"type": "object", "properties": {"input": {"type": "string"}}}}}]
    p = params(req(temperature=0.2, top_p=0.9, max_tokens=500, tools=tools, tool_choice="required"))
    assert "temperature" not in p and "top_p" not in p, "API version 2026-10-21 rejects sampling params"
    assert p["max_tokens"] == 500
    assert p["tools"] == [{"name": "calculator", "description": "Math",
                           "input_schema": {"type": "object", "properties": {"input": {"type": "string"}}}}]
    assert p["tool_choice"] == {"type": "auto"}, "forced tool use 400s on current models"
    assert params(req(tools=tools, tool_choice="none"))["tool_choice"] == {"type": "none"}
    assert set(params(req())) == {"model", "messages", "max_tokens"}
    assert params(req())["max_tokens"] == 16000


def test_stream_thinking_text_tool_call_and_usage(server, backend):
    server.reply_sse(
        message_start(input_tokens=40, cache_read=1000, cache_write=200),
        block_start(0, {"type": "thinking", "thinking": "", "signature": ""}),
        block_delta(0, {"type": "thinking_delta", "thinking": "Need the calculator."}),
        block_delta(0, {"type": "signature_delta", "signature": "EqQBCgIYAhIM"}),
        block_stop(0),
        block_start(1, {"type": "text", "text": ""}),
        block_delta(1, {"type": "text_delta", "text": "Let me "}),
        block_delta(1, {"type": "text_delta", "text": "check."}),
        block_stop(1),
        block_start(2, {"type": "tool_use", "id": "toolu_abc", "name": "calculator", "input": {}}),
        block_delta(2, {"type": "input_json_delta", "partial_json": '{"inp'}),
        block_delta(2, {"type": "input_json_delta", "partial_json": 'ut": "2+3"}'}),
        block_stop(2),
        message_delta("tool_use", 25),
        {"type": "message_stop"},
    )
    s = asyncio.run(backend.stream(req()))
    chunks = read(s)
    sent = server.last_json
    assert str(server.requests[-1].url) == "https://api.anthropic.com/v1/messages" and sent["stream"] is True
    assert "sk-ant-test" in (server.requests[-1].headers.get("x-api-key", "")
                             + server.requests[-1].headers.get("authorization", ""))
    assert "".join(c.text for c in chunks) == "Let me check."
    assert [b for c in chunks for b in c.thinking_blocks] == [
        {"type": "thinking", "thinking": "Need the calculator.", "signature": "EqQBCgIYAhIM"}]
    frags = [t for c in chunks for t in c.tool_calls]
    assert {f.index for f in frags} == {0}, "tool-call index, not content-block index"
    assert frags[0].id == "toolu_abc" and frags[0].name == "calculator"
    assert "".join(f.arguments for f in frags) == '{"input": "2+3"}'
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["tool_calls"]
    u = s.usage
    assert (u.prompt_tokens, u.completion_tokens, u.total_tokens) == (1240, 25, 1265), "cache tokens counted in prompt"
    assert (u.cache_read_tokens, u.cache_write_tokens) == (1000, 200)


def test_complete_and_base_url(server, backend):
    server.reply_sse(*text_reply("Pong", input_tokens=12, output_tokens=2))
    r = asyncio.run(backend.complete(req(base_url="https://proxy.example")))
    assert str(server.requests[-1].url) == "https://proxy.example/v1/messages"
    assert r.text == "Pong" and r.finish_reason == "stop"
    assert (r.usage.prompt_tokens, r.usage.completion_tokens) == (12, 2)

    server.reply_sse(*text_reply("", stop="refusal"))
    assert asyncio.run(backend.complete(req())).finish_reason == "content_filter"
    server.reply_sse(*text_reply("cut", stop="max_tokens"))
    assert asyncio.run(backend.complete(req())).finish_reason == "length"


def test_api_key_from_env_or_refused(server, backend, monkeypatch):
    with pytest.raises(llm.LLMError, match="No Anthropic API key") as e:
        asyncio.run(backend.complete(req(api_key="")))
    assert not e.value.retryable and not server.requests
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    server.reply_sse(*text_reply("ok"))
    asyncio.run(backend.complete(req(api_key="")))
    assert "sk-ant-env" in (server.requests[-1].headers.get("x-api-key", "")
                            + server.requests[-1].headers.get("authorization", ""))


def test_errors(server, backend):
    server.reply_error(401, "authentication_error", "invalid x-api-key")
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.complete(req()))
    assert "anthropic returned HTTP 401" in str(e.value) and "invalid x-api-key" in str(e.value)
    assert e.value.status == 401 and not e.value.retryable

    server.reply_error(529, "overloaded_error", "Overloaded")
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.stream(req()))
    assert e.value.status == 529 and e.value.retryable, "raises before streaming"

    server.reply_sse(message_start(), block_start(0, {"type": "text", "text": ""}),
                     block_delta(0, {"type": "text_delta", "text": "Hal"}),
                     {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
    with pytest.raises(llm.LLMError, match="Overloaded") as e:
        read(asyncio.run(backend.stream(req())))
    assert e.value.retryable, "a mid-stream overload can be retried"

    server.raise_error = httpx2.ConnectError("Connection refused")
    with pytest.raises(llm.LLMError, match="Can't reach anthropic") as e:
        asyncio.run(backend.complete(req()))
    assert e.value.retryable


def test_backend_selection(monkeypatch):
    assert llm.backend_for("anthropic").id == "anthropic", "auto now picks our Anthropic adapter"
    monkeypatch.setenv("LLM_BACKEND_ANTHROPIC", "anthropic")
    assert llm.backend_for("anthropic").id == "anthropic"
    monkeypatch.setenv("LLM_BACKEND", "anthropic")
    assert llm.backend_for("openai").id == "openai_compat", "can't serve openai → auto"


@pytest.fixture
def on_anthropic(monkeypatch, server):
    """The gateway's own Anthropic backend, talking to the stand-in server."""
    monkeypatch.setenv("LLM_BACKEND_ANTHROPIC", "anthropic")
    backend = llm.backend_for("anthropic")
    monkeypatch.setattr(backend, "http_client_factory",
                        lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(server.handler)))
    backend._clients.clear()
    yield
    backend._clients.clear()


async def _collect(r):
    return [json.loads(line[6:]) async for part in run_stream(r)
            for line in part.splitlines() if line.startswith("data: ")]


def test_tool_calling_run_sends_thinking_back(server, on_anthropic):
    thinking = {"type": "thinking", "thinking": "", "signature": "sig-1"}
    server.reply_sse(
        message_start(input_tokens=80),
        block_start(0, {"type": "thinking", "thinking": "", "signature": ""}),
        block_delta(0, {"type": "signature_delta", "signature": "sig-1"}),
        block_stop(0),
        block_start(1, {"type": "tool_use", "id": "toolu_1", "name": "calculator", "input": {}}),
        block_delta(1, {"type": "input_json_delta", "partial_json": '{"input": "2+3"}'}),
        block_stop(1),
        message_delta("tool_use", 12),
        {"type": "message_stop"},
    )
    server.reply_sse(*text_reply("It is 5.", input_tokens=56, output_tokens=4, cache_read=64))
    events = asyncio.run(_collect(PromptRunRequest(
        prompt="What is 2+3?", config=LLMConfig(provider="anthropic", model="claude-haiku-5-5", api_key="sk-ant-test"),
        attached_tools=[{"toolId": "calculator", "label": "calculator", "config": {}}],
    )))
    by_type = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)
    assert "error" not in by_type, by_type.get("error")
    first, second = (json.loads(r.content) for r in server.requests)
    assert "temperature" not in first and "top_p" not in first
    assert first["tools"][0]["name"] == "calculator" and first["tool_choice"] == {"type": "auto"}
    assert second["messages"][-2] == {"role": "assistant", "content": [
        thinking, {"type": "tool_use", "id": "toolu_1", "name": "calculator", "input": {"input": "2+3"}}]}
    result = second["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1" and "5" in result["content"]
    assert "".join(e["text"] for e in by_type["token"]) == "It is 5."
    meta = by_type["meta"][0]
    price = pricing.price_for("anthropic", "claude-haiku-5-5")
    expected = ((80 * price["in"] + 12 * price["out"])
                + (56 * price["in"] + 64 * price["cache_read"] + 4 * price["out"])) / 1e6
    assert meta["llm_backend"] == "anthropic"
    assert abs(meta["cost_usd"] - round(expected, 6)) < 1e-9, "cost summed over both steps"
