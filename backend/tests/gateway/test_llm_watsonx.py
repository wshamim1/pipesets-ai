"""Our watsonx.ai backend (llm/backends/watsonx.py): IAM token exchange and caching, the chat
request shape, responses, SSE streams with tool calls and usage, and errors. httpx.MockTransport
stands in for the network; the payloads follow IBM's documented text-chat format and are written
by hand, not recorded from the live API."""

import asyncio
import json

import httpx
import pytest

import llm
from llm.backends.watsonx import IAM_URL, WatsonXBackend, body, endpoint


def req(**fields):
    fields.setdefault("provider", "watsonx")
    fields.setdefault("model", "ibm/granite-4-h-small")
    fields.setdefault("messages", [{"role": "user", "content": "hi"}])
    fields.setdefault("api_key", "wx-key")
    return llm.LLMRequest(**fields)


def sse(*events):
    lines = []
    for e in events:
        lines.append(e if isinstance(e, str) else "data: " + json.dumps(e))
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


def token_reply(token="iam-token", expires_in=3600):
    return {"access_token": token, "expires_in": expires_in, "token_type": "Bearer"}


def chat_reply(content="Pong", finish="stop", usage=None, tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"id": "chat-1", "model_id": "ibm/granite-4-h-small",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            **({"usage": usage} if usage else {})}


class Server:
    """Stand-in IAM + watsonx: records requests, replies from a queue of (status, body, content-type)."""

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


@pytest.fixture(autouse=True)
def _project(monkeypatch):
    monkeypatch.setenv("WATSONX_PROJECT_ID", "proj-123")
    monkeypatch.delenv("LLM_BACKEND", raising=False)


@pytest.fixture
def server():
    return Server()


@pytest.fixture
def backend(server):
    return WatsonXBackend(transport=httpx.MockTransport(server.handler))


async def _read(stream):
    return [c async for c in stream]


def read(stream):
    return asyncio.run(_read(stream))


def test_endpoint():
    assert endpoint(None) == "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat?version=2024-03-13"
    assert endpoint("https://eu-de.ml.cloud.ibm.com/") == \
        "https://eu-de.ml.cloud.ibm.com/ml/v1/text/chat?version=2024-03-13"
    assert endpoint("https://h/ml/v1") == "https://h/ml/v1/text/chat?version=2024-03-13"
    # Streaming has its own path; it is not the chat path with a stream flag.
    assert endpoint(None, stream=True) == \
        "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat_stream?version=2024-03-13"
    assert endpoint("https://h/ml/v1", stream=True) == \
        "https://h/ml/v1/text/chat_stream?version=2024-03-13"


def test_request_body():
    b = body(req(temperature=0.2, top_p=0.9, max_tokens=64,
                 tools=[{"type": "function", "function": {"name": "f"}}], tool_choice="auto"))
    assert b["model_id"] == "ibm/granite-4-h-small" and b["project_id"] == "proj-123"
    assert (b["temperature"], b["top_p"], b["max_tokens"]) == (0.2, 0.9, 64)
    assert b["tools"] and b["tool_choice"] == "auto"
    assert "stream" not in b
    assert set(body(req())) == {"model_id", "messages", "project_id"}


def test_complete_exchanges_and_caches_iam_token(server, backend):
    server.reply_json(token_reply())
    server.reply_json(chat_reply("Pong", usage={"prompt_tokens": 12, "completion_tokens": 2,
                                                "total_tokens": 14}))
    r = asyncio.run(backend.complete(req()))
    assert str(server.requests[0].url) == IAM_URL
    form = server.requests[0].content.decode()
    assert "apikey=wx-key" in form and "grant_type=urn" in form
    assert str(server.requests[1].url) == \
        "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat?version=2024-03-13"
    assert server.requests[1].headers["authorization"] == "Bearer iam-token"
    assert server.last_json == {"model_id": "ibm/granite-4-h-small", "project_id": "proj-123",
                                "messages": [{"role": "user", "content": "hi"}]}
    assert r.text == "Pong" and r.finish_reason == "stop"
    assert (r.usage.prompt_tokens, r.usage.total_tokens) == (12, 14)

    server.reply_json(chat_reply("Again"))
    asyncio.run(backend.complete(req()))
    assert len(server.requests) == 3, "the IAM token is reused, not exchanged again"
    assert str(server.requests[2].url).endswith("/text/chat?version=2024-03-13")


def test_stream_text_tool_call_and_usage(server, backend):
    server.reply_json(token_reply())
    server.reply_sse(
        ": keep-alive",
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": "Let me "}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": "calc", "arguments": ""}}]},
            "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"input": "2+3"}'}}]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
         "usage": {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49}},
        "data: [DONE]",
    )
    s = asyncio.run(backend.stream(req()))
    assert str(server.requests[1].url) == \
        "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat_stream?version=2024-03-13"
    assert "stream" not in server.last_json, "the streaming path implies streaming; no flag is sent"
    chunks = read(s)
    assert "".join(c.text for c in chunks) == "Let me "
    frags = [t for c in chunks for t in c.tool_calls]
    assert frags[0].id == "call_1" and frags[0].name == "calc"
    assert "".join(f.arguments for f in frags) == '{"input": "2+3"}'
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["tool_calls"]
    assert s.usage and (s.usage.prompt_tokens, s.usage.total_tokens) == (40, 49)


def test_errors(server, backend, monkeypatch):
    server.reply_json({"errorCode": "BXNIM0415E", "errorMessage": "Provided API key could not be found."},
                      status=401)
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.complete(req(api_key="bad")))
    assert "IBM Cloud IAM returned HTTP 401" in str(e.value) and "API key could not be found" in str(e.value)
    assert e.value.status == 401 and not e.value.retryable

    server.reply_json(token_reply())
    server.reply_json({"errors": [{"code": "model_not_found", "message": "No such model"}]}, status=404)
    with pytest.raises(llm.LLMError, match="watsonx returned HTTP 404: No such model"):
        asyncio.run(backend.complete(req()))

    server.reply_json({"error": {"message": "Rate limit reached"}}, status=429)
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.stream(req()))
    assert e.value.status == 429 and e.value.retryable

    server.reply_sse({"choices": [{"delta": {"content": "Hal"}, "finish_reason": None}]},
                     {"error": {"message": "model overloaded"}})
    with pytest.raises(llm.LLMError, match="model overloaded"):
        read(asyncio.run(backend.stream(req())))

    server.raise_error = httpx.ConnectError("Connection refused")
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.complete(req()))
    assert "Can't reach" in str(e.value) and e.value.retryable


def test_requires_key_and_project(server, backend, monkeypatch):
    monkeypatch.delenv("WATSONX_PROJECT_ID")
    with pytest.raises(llm.LLMError, match="No watsonx.ai API key"):
        asyncio.run(backend.complete(req(api_key="")))
    with pytest.raises(llm.LLMError, match="WATSONX_PROJECT_ID"):
        asyncio.run(backend.complete(req()))


def test_backend_selection():
    assert llm.backend_for("watsonx").id == "watsonx"
    assert llm.backends_for("watsonx")[0] == "watsonx"
