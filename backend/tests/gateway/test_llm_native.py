"""Native adapters for providers openai_compat also serves: mistral, cohere (v2), ollama (/api/chat).
Hand-written responses from the API references — none of these is live-checked yet."""

import asyncio
import json

import httpx
import pytest

import llm
from llm.backends import cohere, mistral, ollama
from llm.backends.cohere import CohereBackend
from llm.backends.mistral import MistralBackend
from llm.backends.ollama import OllamaBackend

TOOL = {"type": "function", "function": {"name": "calculator", "description": "Math",
                                         "parameters": {"type": "object", "properties": {"input": {"type": "string"}}}}}
HISTORY = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "2+3?"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "toolu_01ABCdef", "type": "function", "function": {"name": "calculator", "arguments": '{"input":"2+3"}'}}]},
    {"role": "tool", "tool_call_id": "toolu_01ABCdef", "content": "5"},
]


def req(provider, **fields):
    fields.setdefault("model", "m")
    fields.setdefault("messages", [{"role": "user", "content": "hi"}])
    fields.setdefault("api_key", "k-test")
    return llm.LLMRequest(provider=provider, **fields)


class Server:
    def __init__(self):
        self.requests, self.replies = [], []

    def handler(self, request):
        self.requests.append(request)
        status, content, ctype = self.replies.pop(0)
        return httpx.Response(status, content=content, headers={"content-type": ctype})

    def reply(self, payload, status=200):
        self.replies.append((status, json.dumps(payload).encode(), "application/json"))

    def reply_lines(self, lines, ctype):
        self.replies.append((200, ("\n".join(lines) + "\n").encode(), ctype))

    @property
    def last_json(self):
        return json.loads(self.requests[-1].content)


def sse(*events):
    return [line for e in events for line in ("data: " + json.dumps(e), "")]


def read(stream):
    async def go():
        return [c async for c in stream]
    return asyncio.run(go())


@pytest.fixture
def server():
    return Server()


# ── Mistral ─────────────────────────────────────────────────────────────────

def test_mistral_body_maps_ids_and_tool_choice():
    b = mistral.body(req("mistral", messages=HISTORY, tools=[TOOL], tool_choice="required", top_p=1.0), stream=True)
    call_id = b["messages"][2]["tool_calls"][0]["id"]
    assert len(call_id) == 9 and call_id.isalnum()
    assert b["messages"][3]["tool_call_id"] == call_id, "a call and its result keep the same id"
    assert b["messages"][2]["content"] == ""
    assert b["tool_choice"] == "any"
    assert "stream_options" not in b
    assert mistral.tool_call_id("abcDEF123") == "abcDEF123", "valid ids pass through"


def test_mistral_stream_text_tools_usage_and_magistral_chunks(server):
    server.reply_lines(sse(
        {"choices": [{"index": 0, "delta": {"content": [{"type": "thinking", "thinking": [{"type": "text", "text": "hmm"}]},
                                                       {"type": "text", "text": "Hel"}]}}]},
        {"choices": [{"index": 0, "delta": {"content": "lo"}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"id": "abcDEF123", "function": {"name": "calculator", "arguments": '{"input":"1"}'}}]},
                      "finish_reason": "tool_calls"}],
         "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}},
    ) + ["data: [DONE]", ""], "text/event-stream")
    backend = MistralBackend(transport=httpx.MockTransport(server.handler))
    s = asyncio.run(backend.stream(req("mistral", tools=[TOOL])))
    chunks = read(s)
    assert "".join(c.text for c in chunks) == "Hello", "thinking chunks are not text"
    assert chunks[2].tool_calls[0].name == "calculator" and chunks[2].finish_reason == "tool_calls"
    assert s.usage.prompt_tokens == 10 and s.usage.completion_tokens == 4
    assert str(server.requests[0].url) == "https://api.mistral.ai/v1/chat/completions"
    assert server.requests[0].headers["authorization"] == "Bearer k-test"


def test_mistral_error(server):
    server.reply({"object": "error", "message": "Invalid model: m", "type": "invalid_model"}, status=400)
    backend = MistralBackend(transport=httpx.MockTransport(server.handler))
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.complete(req("mistral")))
    assert e.value.status == 400 and "Invalid model" in str(e.value) and not e.value.retryable


# ── Cohere v2 ───────────────────────────────────────────────────────────────

def test_cohere_body():
    b = cohere.body(req("cohere", messages=HISTORY[:2] + [
        {"role": "assistant", "content": "Let me compute.", "tool_calls": HISTORY[2]["tool_calls"]}, HISTORY[3]],
        tools=[TOOL], tool_choice="required", top_p=1.0, max_tokens=50), stream=False)
    assert [m["role"] for m in b["messages"]] == ["system", "user", "assistant", "tool"]
    assert b["messages"][2]["tool_plan"] == "Let me compute." and "content" not in b["messages"][2]
    assert b["messages"][3] == {"role": "tool", "tool_call_id": "toolu_01ABCdef", "content": "5"}
    assert b["p"] == 0.99 and b["max_tokens"] == 50 and b["tool_choice"] == "REQUIRED"
    assert "top_p" not in b


def test_cohere_endpoint():
    assert cohere.endpoint(None) == "https://api.cohere.com/v2/chat"
    assert cohere.endpoint("https://api.cohere.ai/compatibility/v1") == "https://api.cohere.ai/v2/chat"
    assert cohere.endpoint("https://proxy.local/v2") == "https://proxy.local/v2/chat"


def test_cohere_complete_uses_billed_units(server):
    server.reply({"id": "x", "finish_reason": "MAX_TOKENS",
                  "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi there"}]},
                  "usage": {"billed_units": {"input_tokens": 3, "output_tokens": 2},
                            "tokens": {"input_tokens": 70, "output_tokens": 2}}})
    backend = CohereBackend(transport=httpx.MockTransport(server.handler))
    resp = asyncio.run(backend.complete(req("cohere")))
    assert resp.text == "Hi there" and resp.finish_reason == "length"
    assert resp.usage.prompt_tokens == 3 and resp.usage.completion_tokens == 2


def test_cohere_stream_text_and_tool_call(server):
    server.reply_lines(sse(
        {"type": "message-start", "id": "x", "delta": {"message": {"role": "assistant"}}},
        {"type": "tool-plan-delta", "delta": {"message": {"tool_plan": "I will"}}},
        {"type": "tool-call-start", "index": 0, "delta": {"message": {"tool_calls": {
            "id": "calc_1", "type": "function", "function": {"name": "calculator", "arguments": ""}}}}},
        {"type": "tool-call-delta", "index": 0, "delta": {"message": {"tool_calls": {"function": {"arguments": '{"input":'}}}}},
        {"type": "tool-call-delta", "index": 0, "delta": {"message": {"tool_calls": {"function": {"arguments": '"2+3"}'}}}}},
        {"type": "tool-call-end", "index": 0},
        {"type": "message-end", "delta": {"finish_reason": "TOOL_CALL",
                                          "usage": {"billed_units": {"input_tokens": 12, "output_tokens": 9}}}},
    ), "text/event-stream")
    backend = CohereBackend(transport=httpx.MockTransport(server.handler))
    s = asyncio.run(backend.stream(req("cohere", tools=[TOOL])))
    chunks = read(s)
    calls = [tc for c in chunks for tc in c.tool_calls]
    assert calls[0].id == "calc_1" and calls[0].name == "calculator"
    assert "".join(tc.arguments for tc in calls) == '{"input":"2+3"}'
    assert chunks[-1].finish_reason == "tool_calls"
    assert s.usage.prompt_tokens == 12 and s.usage.completion_tokens == 9
    assert server.last_json["stream"] is True


def test_cohere_needs_a_key(monkeypatch):
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.delenv("CO_API_KEY", raising=False)
    with pytest.raises(llm.LLMError, match="No Cohere API key"):
        asyncio.run(CohereBackend().complete(req("cohere", api_key="")))


# ── Ollama /api/chat ────────────────────────────────────────────────────────

def test_ollama_body():
    b = ollama.body(req("ollama", messages=HISTORY + [{"role": "user", "content": [
        {"type": "text", "text": "and this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}]}],
        tools=[TOOL], temperature=0.2, max_tokens=64, top_p=1.0), stream=True)
    assert b["options"] == {"temperature": 0.2, "top_p": 1.0, "num_predict": 64}
    assert b["messages"][2]["tool_calls"] == [{"function": {"name": "calculator", "arguments": {"input": "2+3"}}}]
    assert b["messages"][3]["tool_name"] == "calculator"
    assert b["messages"][4] == {"role": "user", "content": "and this?", "images": ["iVBORw0KGgo="]}
    assert "tools" not in ollama.body(req("ollama", tools=[TOOL], tool_choice="none"), stream=False)


def test_ollama_endpoint():
    assert ollama.endpoint("http://localhost:11434/v1") == "http://localhost:11434/api/chat"
    assert ollama.endpoint("http://gpu-box:11434/") == "http://gpu-box:11434/api/chat"


def test_ollama_stream_ndjson(server):
    lines = [json.dumps(x) for x in (
        {"model": "qwen3", "message": {"role": "assistant", "content": "", "thinking": "let me see"}, "done": False},
        {"model": "qwen3", "message": {"role": "assistant", "content": "Hi"}, "done": False},
        {"model": "qwen3", "message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "calculator", "arguments": {"input": "2+3"}}}]}, "done": False},
        {"model": "qwen3", "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
         "prompt_eval_count": 20, "eval_count": 7},
    )]
    server.reply_lines(lines, "application/x-ndjson")
    backend = OllamaBackend(transport=httpx.MockTransport(server.handler))
    s = asyncio.run(backend.stream(req("ollama", model="qwen3", api_key="", tools=[TOOL])))
    chunks = read(s)
    assert "".join(c.text for c in chunks) == "Hi", "thinking is not text"
    call = chunks[2].tool_calls[0]
    assert (call.index, call.id, call.name, json.loads(call.arguments)) == (0, "call_0", "calculator", {"input": "2+3"})
    assert chunks[-1].finish_reason == "tool_calls"
    assert s.usage.prompt_tokens == 20 and s.usage.completion_tokens == 7
    assert "authorization" not in server.requests[0].headers


def test_ollama_complete_length_and_error(server):
    server.reply({"message": {"role": "assistant", "content": "abc"}, "done": True, "done_reason": "length",
                  "prompt_eval_count": 5, "eval_count": 3})
    server.reply({"error": "model 'nope' not found"}, status=404)
    backend = OllamaBackend(transport=httpx.MockTransport(server.handler))
    resp = asyncio.run(backend.complete(req("ollama", api_key="")))
    assert resp.text == "abc" and resp.finish_reason == "length" and resp.usage.total_tokens == 8
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.complete(req("ollama", model="nope", api_key="")))
    assert e.value.status == 404 and "not found" in str(e.value)


# ── Registration ────────────────────────────────────────────────────────────

def test_auto_keeps_openai_compat_native_is_opt_in():
    for provider, native in (("mistral", "mistral"), ("cohere", "cohere"), ("ollama", "ollama")):
        order = llm.backends_for(provider)
        assert order[0] == "openai_compat", "auto stays on the live-checked path"
        assert native in order
        assert llm.backend_for(provider, native).id == native
