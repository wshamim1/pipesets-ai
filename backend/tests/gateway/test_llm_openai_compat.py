"""Our OpenAI-compatible backend (llm/backends/openai_compat.py) against stand-in servers: URLs,
auth, request bodies (incl. reasoning-model rules), responses, SSE streams with fragmented tool
calls and usage, errors, backend selection — and a full tool-calling run through
services/llm_runner.run_stream on this backend.

httpx.MockTransport stands in for the network. The payloads follow OpenAI's documented Chat
Completions format; they are written by hand, not recorded from the live API.
"""
import asyncio
import json

import httpx
import pytest

import llm
from llm import pricing
from llm.backends.openai_compat import OpenAICompatBackend, body, endpoint, headers
from models import JAN_DEFAULT_BASE, LLMConfig, PromptRunRequest
from services.llm_runner import run_stream


def req(**fields):
    fields.setdefault("messages", [{"role": "user", "content": "hi"}])
    return llm.LLMRequest(**fields)


def sse(*events):
    """An SSE body: each event a dict (sent as JSON) or a raw line."""
    lines = []
    for e in events:
        lines.append(e if isinstance(e, str) else "data: " + json.dumps(e))
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


def delta_chunk(delta, finish_reason=None):
    return {"id": "chatcmpl-1", "object": "chat.completion.chunk", "model": "gpt-4o-2024-08-06",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}], "usage": None}


def usage_chunk(prompt, completion, cached=0):
    return {"id": "chatcmpl-1", "object": "chat.completion.chunk", "choices": [],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion,
                      "prompt_tokens_details": {"cached_tokens": cached}}}


class Server:
    """Stand-in provider: records requests, replies from a queue of (status, body, content-type)."""

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
def _no_backend_env(monkeypatch):
    for var in ("OPENAI_API_KEY", "GROQ_API_KEY", "JAN_API_KEY", "LLM_BACKEND", "LLM_BACKEND_OPENAI"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def server():
    return Server()


@pytest.fixture
def backend(server):
    return OpenAICompatBackend(transport=httpx.MockTransport(server.handler))


async def _read(stream):
    return [c async for c in stream]


def read(stream):
    return asyncio.run(_read(stream))


async def _collect(r):
    return [json.loads(line[6:]) async for part in run_stream(r)
            for line in part.splitlines() if line.startswith("data: ")]


def collect(r):
    return asyncio.run(_collect(r))


def test_urls():
    assert endpoint("openai", None) == "https://api.openai.com/v1/chat/completions"
    assert endpoint("groq", None) == "https://api.groq.com/openai/v1/chat/completions"
    assert endpoint("mistral", None) == "https://api.mistral.ai/v1/chat/completions"
    assert endpoint("together", None) == "https://api.together.xyz/v1/chat/completions"
    assert endpoint("fireworks", None) == "https://api.fireworks.ai/inference/v1/chat/completions"
    assert endpoint("huggingface", None) == "https://router.huggingface.co/v1/chat/completions"
    assert endpoint("deepseek", None) == "https://api.deepseek.com/v1/chat/completions"
    assert endpoint("xai", None) == "https://api.x.ai/v1/chat/completions"
    assert endpoint("cerebras", None) == "https://api.cerebras.ai/v1/chat/completions"
    assert endpoint("cohere", None) == "https://api.cohere.ai/compatibility/v1/chat/completions"
    assert endpoint("perplexity", None) == "https://api.perplexity.ai/chat/completions", "no /v1"
    assert endpoint("openai", "https://proxy.example/v1/") == "https://proxy.example/v1/chat/completions"
    assert endpoint("ollama", "http://localhost:11434") == "http://localhost:11434/v1/chat/completions"
    assert endpoint("ollama", "http://gpu-box:11434/v1") == "http://gpu-box:11434/v1/chat/completions"
    assert endpoint("llamacpp", None) == "http://127.0.0.1:8080/v1/chat/completions"
    assert endpoint("jan", None) == JAN_DEFAULT_BASE.rstrip("/") + "/chat/completions"


def test_azure_urls():
    base = "https://my-resource.openai.azure.com"
    assert endpoint("azure", base, "gpt-4o") == (
        base + "/openai/deployments/gpt-4o/chat/completions?api-version=2024-10-21")
    assert endpoint("azure", base + "/openai/deployments/gpt-4o", "gpt-4o") == (
        base + "/openai/deployments/gpt-4o/chat/completions?api-version=2024-10-21")
    assert endpoint("azure", base + "/openai/v1", "gpt-4o") == base + "/openai/v1/chat/completions"
    with pytest.raises(llm.LLMError, match="base URL"):
        endpoint("azure", None, "gpt-4o")


def test_auth(monkeypatch):
    assert headers("openai", "sk-1")["Authorization"] == "Bearer sk-1"
    assert headers("azure", "az-1")["api-key"] == "az-1", "Azure uses api-key, not a bearer token"
    assert "Authorization" not in headers("azure", "az-1")
    assert "Authorization" not in headers("openai", "")
    assert "Authorization" not in headers("groq", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert headers("openai", "")["Authorization"] == "Bearer sk-env", "no node key → server env key"
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("GROQ_API_KEY", "sk-env")
    assert headers("groq", "")["Authorization"] == "Bearer sk-env", "no node key -> server env key"
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.setenv("HF_TOKEN", "hf-env")
    assert headers("huggingface", "")["Authorization"] == "Bearer hf-env"
    monkeypatch.delenv("HF_TOKEN")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-env")
    assert headers("azure", "")["api-key"] == "az-env"
    monkeypatch.delenv("AZURE_OPENAI_API_KEY")
    assert "Authorization" not in headers("ollama", "")
    assert headers("jan", "")["Authorization"] == "Bearer jan-local"


def test_request_bodies():
    b = body(req(provider="openai", model="gpt-4o", temperature=0.7, top_p=1.0, max_tokens=100), stream=False)
    assert b["temperature"] == 0.7 and b["top_p"] == 1.0 and b["max_tokens"] == 100 and "stream" not in b
    b = body(req(provider="openai", model="o3-mini", temperature=0.7, top_p=1.0, max_tokens=100), stream=False)
    assert b.get("max_completion_tokens") == 100 and "max_tokens" not in b and "top_p" not in b \
        and "temperature" not in b, "reasoning model rules"
    assert body(req(provider="openai", model="gpt-5", temperature=1), stream=False).get("temperature") == 1
    assert body(req(provider="openai", model="gpt-5-chat-latest", top_p=0.9), stream=False).get("top_p") == 0.9, \
        "gpt-5 chat variant is not a reasoning model"
    assert body(req(provider="ollama", model="o3", top_p=0.9, max_tokens=5), stream=False).get("max_tokens") == 5, \
        "reasoning rules apply only to OpenAI and Azure"
    azure_reasoning = body(req(provider="azure", model="o3-mini", top_p=0.9, max_tokens=5), stream=False)
    assert azure_reasoning.get("max_completion_tokens") == 5 and "top_p" not in azure_reasoning, \
        "Azure serves OpenAI reasoning models too"
    b = body(req(provider="openai", model="gpt-4o", tools=[{"type": "function"}], tool_choice="auto"), stream=True)
    assert b["tools"] and b["tool_choice"] == "auto" and b["stream"] is True
    assert b["stream_options"] == {"include_usage": True}
    assert set(body(req(provider="openai", model="m"), stream=False)) == {"model", "messages"}
    assert "stream_options" not in body(req(provider="jan", model="m"), stream=True)


def test_complete(server, backend):
    server.reply_json({"id": "chatcmpl-9", "object": "chat.completion", "model": "gpt-4o-2024-08-06",
                       "choices": [{"index": 0, "message": {"role": "assistant", "content": "Pong"}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1200, "completion_tokens": 5, "total_tokens": 1205,
                                 "prompt_tokens_details": {"cached_tokens": 1024}}})
    r = asyncio.run(backend.complete(req(provider="openai", model="gpt-4o", api_key="sk-1", max_tokens=8)))
    sent = server.requests[-1]
    assert str(sent.url) == "https://api.openai.com/v1/chat/completions"
    assert sent.headers["authorization"] == "Bearer sk-1"
    assert server.last_json == {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8}
    assert r.text == "Pong" and r.finish_reason == "stop"
    assert (r.usage.prompt_tokens, r.usage.completion_tokens, r.usage.cache_read_tokens) == (1200, 5, 1024)


def test_deepseek_usage_and_azure_request(server, backend):
    server.reply_json({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105,
                                 "prompt_cache_hit_tokens": 64, "prompt_cache_miss_tokens": 36}})
    r = asyncio.run(backend.complete(req(provider="deepseek", model="deepseek-chat", api_key="sk-1")))
    assert r.usage.cache_read_tokens == 64, "DeepSeek reports cache hits at the top level"

    server.reply_json({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})
    asyncio.run(backend.complete(req(provider="azure", model="gpt-4o", api_key="az-1",
                                     base_url="https://my-resource.openai.azure.com")))
    sent = server.requests[-1]
    assert str(sent.url) == ("https://my-resource.openai.azure.com/openai/deployments/gpt-4o/"
                             "chat/completions?api-version=2024-10-21")
    assert sent.headers["api-key"] == "az-1" and "authorization" not in sent.headers
    assert server.last_json["model"] == "gpt-4o"


def test_stream_text_tool_call_and_usage(server, backend):
    server.reply_sse(
        ": keep-alive",
        delta_chunk({"role": "assistant", "content": ""}),
        delta_chunk({"content": "Let me "}),
        delta_chunk({"content": "check."}),
        delta_chunk({"tool_calls": [{"index": 0, "id": "call_abc", "type": "function",
                                     "function": {"name": "calcu", "arguments": ""}}]}),
        delta_chunk({"tool_calls": [{"index": 0, "function": {"name": "lator", "arguments": '{"inp'}}]}),
        delta_chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'ut": "2+3"}'}}]}),
        delta_chunk({}, finish_reason="tool_calls"),
        usage_chunk(50, 20),
        "data: [DONE]",
    )
    s = asyncio.run(backend.stream(req(provider="openai", model="gpt-4o")))
    chunks = read(s)
    assert server.last_json["stream"] is True
    assert "".join(c.text for c in chunks) == "Let me check."
    frags = [t for c in chunks for t in c.tool_calls]
    assert [f.name for f in frags] == ["calcu", "lator", ""] and frags[0].id == "call_abc"
    assert "".join(f.arguments for f in frags) == '{"input": "2+3"}'
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["tool_calls"]
    assert s.usage and (s.usage.prompt_tokens, s.usage.total_tokens) == (50, 70)


def test_errors(server, backend):
    server.reply_json({"error": {"message": "Incorrect API key provided: sk-bad", "type": "invalid_request_error"}},
                      status=401)
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.complete(req(provider="openai", model="gpt-4o", api_key="sk-bad")))
    assert "openai returned HTTP 401: Incorrect API key" in str(e.value) and e.value.status == 401
    assert not e.value.retryable

    server.reply_json({"error": {"message": "Rate limit reached"}}, status=429)
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.stream(req(provider="openai", model="gpt-4o")))
    assert e.value.status == 429 and e.value.retryable, "raises before streaming"

    server.replies.append((502, b"<html>Bad gateway</html>", "text/html"))
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.complete(req(provider="openai", model="gpt-4o")))
    assert "HTTP 502" in str(e.value) and "Bad gateway" in str(e.value) and e.value.retryable

    server.reply_sse(delta_chunk({"content": "Hal"}), {"error": {"message": "model overloaded"}})
    with pytest.raises(llm.LLMError, match="model overloaded"):
        read(asyncio.run(backend.stream(req(provider="openai", model="gpt-4o"))))

    server.raise_error = httpx.ConnectError("Connection refused")
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(backend.complete(req(provider="ollama", model="llama3.2")))
    assert "Can't reach ollama at http://localhost:11434/v1/chat/completions" in str(e.value)
    assert "local server running" in str(e.value) and e.value.retryable


def test_one_pooled_client_per_event_loop(server, backend):
    async def two_calls():
        server.reply_json({"choices": [{"message": {"content": "a"}}]})
        server.reply_json({"choices": [{"message": {"content": "b"}}]})
        await backend.complete(req(provider="ollama", model="m"))
        c1 = backend._client()
        await backend.complete(req(provider="ollama", model="m"))
        return c1 is backend._client()
    assert asyncio.run(two_calls())


def test_backend_selection(monkeypatch):
    assert llm.backend_for("openai").id == "openai_compat", "auto picks our adapter for live-checked openai"
    assert llm.backend_for("ollama").id == "openai_compat", "…and live-checked local servers"
    assert llm.backend_for("llamacpp").id == "openai_compat"
    assert llm.backend_for("jan").id == "litellm", "jan isn't live-checked yet"
    for provider in ("groq", "mistral", "together", "fireworks", "huggingface", "deepseek", "xai",
                     "cerebras", "perplexity", "cohere", "azure", "nvidia"):
        assert llm.backend_for(provider).id == "openai_compat", provider
    assert llm.backend_for("gemini").id == "gemini"
    assert llm.backend_for("bedrock").id == "bedrock"
    assert llm.backend_for("watsonx").id == "watsonx"
    monkeypatch.setenv("LLM_BACKEND_OLLAMA", "litellm")
    assert llm.backend_for("ollama").id == "litellm", "a setting still picks LiteLLM explicitly"
    monkeypatch.delenv("LLM_BACKEND_OLLAMA")
    monkeypatch.setenv("LLM_BACKEND_JAN", "openai_compat")
    assert llm.backend_for("jan").id == "openai_compat"
    assert llm.backend_for("anthropic").id == "anthropic", "Anthropic now uses its own adapter in auto"
    monkeypatch.delenv("LLM_BACKEND_JAN")
    monkeypatch.setenv("LLM_BACKEND", "openai_compat")
    assert llm.backend_for("jan").id == "openai_compat"
    assert llm.backend_for("anthropic").id == "anthropic", "falls back to auto where it can't serve"
    monkeypatch.setenv("LLM_BACKEND_OPENAI", "litellm")
    assert llm.backend_for("openai").id == "litellm", "the per-provider setting beats LLM_BACKEND"
    monkeypatch.delenv("LLM_BACKEND_OPENAI")
    monkeypatch.setenv("LLM_BACKEND_GROQ", "openai_compat")
    assert llm.backend_for("groq").id == "openai_compat", "Groq can opt into our OpenAI-compatible backend"
    monkeypatch.delenv("LLM_BACKEND_GROQ")
    monkeypatch.setenv("LLM_BACKEND", "nope")
    with pytest.raises(llm.BackendUnavailable, match="openai_compat"):
        llm.backend_for("openai")


def test_every_offered_provider_uses_an_adapter_of_ours():
    from llm.catalog import PROVIDERS
    # TypeSafe's Jev is an evaluation API, not a chat model; it has no adapter.
    unsupported = [p["id"] for p in PROVIDERS
                   if p["id"] not in {"mock", "typesafe"} and llm.backend_for(p["id"]).id == "litellm"]
    assert not unsupported, f"no adapter for {unsupported} — auto would fall back to LiteLLM"


@pytest.fixture
def on_openai_compat(monkeypatch, server):
    """The gateway's own openai_compat backend, talking to the stand-in server."""
    monkeypatch.setenv("LLM_BACKEND", "openai_compat")
    monkeypatch.setattr(llm.backend_for("openai"), "transport", httpx.MockTransport(server.handler))


def test_tool_calling_run_through_agent_loop(server, on_openai_compat):
    server.reply_sse(
        delta_chunk({"role": "assistant", "content": None, "tool_calls": [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": ""}}]}),
        delta_chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"input": "2+3"}'}}]}),
        delta_chunk({}, finish_reason="tool_calls"),
        usage_chunk(80, 12),
        "data: [DONE]",
    )
    server.reply_sse(
        delta_chunk({"content": "It is "}),
        delta_chunk({"content": "5."}),
        delta_chunk({}, finish_reason="stop"),
        usage_chunk(120, 4, cached=64),
        "data: [DONE]",
    )
    events = collect(PromptRunRequest(
        prompt="What is 2+3?", config=LLMConfig(provider="openai", model="gpt-4o", api_key="sk-test"),
        attached_tools=[{"toolId": "calculator", "label": "calculator", "config": {}}],
    ))
    by_type = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)
    second = json.loads(server.requests[1].content)
    assert len(server.requests) == 2
    assert by_type["tool_call"][0]["input"] == "2+3" and "5" in by_type["tool"][0]["output"]
    assert any(m.get("tool_calls") for m in second["messages"])
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "call_1" for m in second["messages"])
    assert "".join(e["text"] for e in by_type["token"]) == "It is 5."
    meta = by_type["meta"][0]
    gpt4o = pricing.price_for("openai", "gpt-4o")
    expected = ((80 * gpt4o["in"] + 12 * gpt4o["out"])
                + (56 * gpt4o["in"] + 64 * gpt4o["cache_read"] + 4 * gpt4o["out"])) / 1e6
    assert meta["llm_backend"] == "openai_compat"
    assert abs(meta["cost_usd"] - round(expected, 6)) < 1e-9, "cost summed over both steps"
    assert events[-1]["type"] == "done" and "error" not in by_type


def test_local_single_call_path(server, on_openai_compat):
    server.reply_sse(delta_chunk({"content": "Hi "}), delta_chunk({"content": "there"}),
                     delta_chunk({}, finish_reason="stop"), "data: [DONE]")
    events = collect(PromptRunRequest(prompt="Hello", config=LLMConfig(provider="ollama", model="llama3.2")))
    assert str(server.requests[0].url) == "http://localhost:11434/v1/chat/completions"
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Hi there"
    assert next(e for e in events if e["type"] == "meta")["usage"]["total_tokens"] > 0, "estimated tokens"
