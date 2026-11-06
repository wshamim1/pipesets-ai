import asyncio
import json

import pytest
from botocore.exceptions import ClientError

import llm
from llm.backends.bedrock import BedrockBackend, convert_messages, request_params
from models import LLMConfig, PromptRunRequest
from services.llm_runner import run_stream


def req(**fields):
    fields.setdefault("provider", "bedrock")
    fields.setdefault("model", "anthropic.claude-3-5-sonnet-20241022-v2:0")
    fields.setdefault("messages", [{"role": "user", "content": "hi"}])
    return llm.LLMRequest(**fields)


class FakeBedrockClient:
    def __init__(self):
        self.stream_replies = []
        self.complete_replies = []
        self.stream_errors = []
        self.complete_errors = []
        self.stream_calls = []
        self.complete_calls = []

    def converse(self, **kwargs):
        self.complete_calls.append(kwargs)
        if self.complete_errors:
            raise self.complete_errors.pop(0)
        return self.complete_replies.pop(0)

    def converse_stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        if self.stream_errors:
            raise self.stream_errors.pop(0)
        return {"stream": iter(self.stream_replies.pop(0))}


@pytest.fixture
def fake_client():
    return FakeBedrockClient()


@pytest.fixture
def backend(fake_client):
    return BedrockBackend(lambda _req: fake_client)


async def _read(stream):
    return [c async for c in stream]


def read(stream):
    return asyncio.run(_read(stream))


def test_message_conversion():
    system, messages = convert_messages([
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "What's 2+3?"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call_1", "type": "function",
                         "function": {"name": "calculator", "arguments": '{"input":"2+3"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "5"},
        {"role": "system", "content": "Return JSON."},
    ])
    assert system == [{"text": "Be brief."}]
    assert messages == [
        {"role": "user", "content": [{"text": "What's 2+3?"}]},
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "call_1", "name": "calculator", "input": {"input": "2+3"}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "call_1", "content": [{"text": "5"}]}}, {"text": "Return JSON."}]},
    ]


def test_request_params():
    tools = [{"type": "function", "function": {"name": "calculator", "description": "Math",
                                               "parameters": {"type": "object", "properties": {"input": {"type": "string"}}}}}]
    p = request_params(req(max_tokens=300, temperature=0.4, top_p=0.8, tools=tools, tool_choice="required"))
    assert p["inferenceConfig"] == {"maxTokens": 300, "temperature": 0.4, "topP": 0.8}
    assert p["toolConfig"]["toolChoice"] == {"auto": {}}
    assert p["toolConfig"]["tools"][0]["toolSpec"]["name"] == "calculator"


def test_complete(backend, fake_client):
    fake_client.complete_replies.append({
        "output": {"message": {"content": [{"text": "Pong"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 12, "outputTokens": 3, "totalTokens": 15},
    })
    out = asyncio.run(backend.complete(req()))
    assert out.text == "Pong"
    assert out.finish_reason == "stop"
    assert (out.usage.prompt_tokens, out.usage.completion_tokens, out.usage.total_tokens) == (12, 3, 15)
    assert fake_client.complete_calls[-1]["modelId"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"


def test_stream_text_tool_call_and_usage(backend, fake_client):
    fake_client.stream_replies.append([
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"toolUseId": "toolu_1", "name": "calculator"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": '{"inp'}}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": 'ut":"2+3"}'}}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"contentBlockStart": {"contentBlockIndex": 1, "start": {"text": ""}}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"text": "It is "}}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"text": "5."}}},
        {"metadata": {"usage": {"inputTokens": 80, "outputTokens": 12, "totalTokens": 92}}},
        {"messageStop": {"stopReason": "tool_use"}},
    ])
    stream = asyncio.run(backend.stream(req()))
    chunks = read(stream)
    calls = [t for c in chunks for t in c.tool_calls]
    assert calls[0].id == "toolu_1" and calls[0].name == "calculator"
    assert "".join(t.arguments for t in calls) == '{"input":"2+3"}'
    assert "".join(c.text for c in chunks) == "It is 5."
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["tool_calls"]
    assert (stream.usage.prompt_tokens, stream.usage.completion_tokens, stream.usage.total_tokens) == (80, 12, 92)


def test_errors(backend, fake_client):
    err = ClientError(
        error_response={"Error": {"Code": "ValidationException", "Message": "bad request"},
                        "ResponseMetadata": {"HTTPStatusCode": 400}},
        operation_name="Converse",
    )
    fake_client.complete_errors.append(err)
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.complete(req()))
    assert "bedrock returned HTTP 400: bad request" in str(e.value)
    assert e.value.status == 400 and not e.value.retryable

    throttled = ClientError(
        error_response={"Error": {"Code": "ThrottlingException", "Message": "slow down"},
                        "ResponseMetadata": {"HTTPStatusCode": 429}},
        operation_name="ConverseStream",
    )
    fake_client.stream_errors.append(throttled)
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.stream(req()))
    assert e.value.retryable and e.value.status == 429


@pytest.fixture
def on_bedrock(monkeypatch, fake_client):
    monkeypatch.setenv("LLM_BACKEND_BEDROCK", "bedrock")
    backend = llm.backend_for("bedrock")
    monkeypatch.setattr(backend, "client_factory", lambda _req: fake_client)


async def _collect(r):
    return [json.loads(line[6:]) async for part in run_stream(r)
            for line in part.splitlines() if line.startswith("data: ")]


def test_tool_calling_run_through_agent_loop(fake_client, on_bedrock):
    fake_client.stream_replies.append([
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"toolUseId": "toolu_1", "name": "calculator"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": '{"input":"2+3"}'}}}},
        {"metadata": {"usage": {"inputTokens": 50, "outputTokens": 10, "totalTokens": 60}}},
        {"messageStop": {"stopReason": "tool_use"}},
    ])
    fake_client.stream_replies.append([
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {"text": ""}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "It is 5."}}},
        {"metadata": {"usage": {"inputTokens": 40, "outputTokens": 4, "totalTokens": 44}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ])
    events = asyncio.run(_collect(PromptRunRequest(
        prompt="What is 2+3?",
        config=LLMConfig(provider="bedrock", model="anthropic.claude-3-5-sonnet-20241022-v2:0", api_key="AKIA_TEST"),
        attached_tools=[{"toolId": "calculator", "label": "calculator", "config": {}}],
    )))
    by_type = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)
    assert "2+3" in by_type["tool_call"][0]["input"]
    assert "5" in by_type["tool"][0]["output"]
    assert "".join(e["text"] for e in by_type["token"]) == "It is 5."
    assert by_type["meta"][0]["llm_backend"] == "bedrock"
    second = fake_client.stream_calls[1]
    assert any(m.get("role") == "assistant" and any("toolUse" in p for p in m.get("content", []))
               for m in second["messages"])
    assert any(m.get("role") == "user" and any("toolResult" in p for p in m.get("content", []))
               for m in second["messages"])
