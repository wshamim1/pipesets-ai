import asyncio
import json

import httpx
import pytest

import llm
from llm.backends.gemini import GeminiBackend, body, convert_messages, endpoint


def req(**fields):
    fields.setdefault("provider", "gemini")
    fields.setdefault("model", "gemini-2.5-flash")
    fields.setdefault("messages", [{"role": "user", "content": "hi"}])
    fields.setdefault("api_key", "gm-test")
    return llm.LLMRequest(**fields)


def sse(*events):
    lines = []
    for e in events:
        lines.append(e if isinstance(e, str) else "data: " + json.dumps(e))
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


class Server:
    def __init__(self):
        self.requests = []
        self.replies = []
        self.raise_error = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_error:
            raise self.raise_error
        status, content, ctype = self.replies.pop(0)
        return httpx.Response(status, content=content, headers={"content-type": ctype})

    def reply_json(self, payload, status=200):
        self.replies.append((status, json.dumps(payload).encode(), "application/json"))

    def reply_sse(self, *events, status=200):
        self.replies.append((status, sse(*events), "text/event-stream"))

    @property
    def last_json(self):
        return json.loads(self.requests[-1].content)


@pytest.fixture
def server():
    return Server()


@pytest.fixture
def backend(server):
    return GeminiBackend(transport=httpx.MockTransport(server.handler))


async def _read(stream):
    return [c async for c in stream]


def read(stream):
    return asyncio.run(_read(stream))


def test_conversion():
    system, messages = convert_messages([
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "2+3?"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": '{"input":"2+3"}'}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "5"},
        {"role": "system", "content": "Return JSON."},
    ])
    assert system == {"parts": [{"text": "Be brief."}]}
    assert messages[-1]["parts"][0]["functionResponse"]["name"] == "calculator"
    assert messages[-1]["parts"][1]["text"] == "Return JSON."


def test_body_and_endpoint():
    b = body(req(max_tokens=50, temperature=0.2, top_p=0.9, tools=[{
        "type": "function", "function": {"name": "calculator", "parameters": {"type": "object"}}
    }], tool_choice="auto"))
    assert b["generationConfig"] == {"temperature": 0.2, "topP": 0.9, "maxOutputTokens": 50}
    assert b["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"
    assert endpoint(None, "gemini-2.5-flash", False, "k").endswith(
        "/models/gemini-2.5-flash:generateContent?key=k"
    )
    assert "alt=sse" in endpoint(None, "models/gemini-2.5-flash", True, "k")


def test_complete(server, backend):
    server.reply_json({
        "candidates": [{"content": {"parts": [{"text": "Pong"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3, "totalTokenCount": 15},
    })
    out = asyncio.run(backend.complete(req()))
    assert out.text == "Pong"
    assert out.finish_reason == "stop"
    assert (out.usage.prompt_tokens, out.usage.completion_tokens, out.usage.total_tokens) == (12, 3, 15)


def test_stream(server, backend):
    server.reply_sse(
        {"candidates": [{"content": {"parts": [{"functionCall": {"name": "calculator", "args": {"input": "2+3"}}}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "It is "}, {"text": "5."}]}}]},
        {"candidates": [{"finishReason": "STOP"}],
         "usageMetadata": {"promptTokenCount": 40, "candidatesTokenCount": 8, "totalTokenCount": 48}},
    )
    stream = asyncio.run(backend.stream(req()))
    chunks = read(stream)
    calls = [t for c in chunks for t in c.tool_calls]
    assert calls and calls[0].name == "calculator" and "2+3" in calls[0].arguments
    assert "".join(c.text for c in chunks) == "It is 5."
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["stop"]
    assert (stream.usage.prompt_tokens, stream.usage.completion_tokens, stream.usage.total_tokens) == (40, 8, 48)


def test_errors(server, backend):
    server.reply_json({"error": {"message": "bad key"}}, status=401)
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.complete(req()))
    assert "gemini returned HTTP 401: bad key" in str(e.value)
    assert e.value.status == 401 and not e.value.retryable

    server.raise_error = httpx.ConnectError("Connection refused")
    with pytest.raises(llm.LLMError, match="Can't reach gemini"):
        asyncio.run(backend.complete(req()))


def test_backend_selection(monkeypatch):
    assert llm.backend_for("gemini").id == "gemini", "auto uses our adapter"
    monkeypatch.setenv("LLM_BACKEND_GEMINI", "litellm")
    assert llm.backend_for("gemini").id == "litellm", "a setting can still pick LiteLLM"
    monkeypatch.setenv("LLM_BACKEND_GEMINI", "gemini")
    assert llm.backend_for("gemini").id == "gemini"
