"""The LLM gateway (llm/): backend choice, the LiteLLM backend's request mapping, and conversion
of LiteLLM responses and streams — including streamed tool calls through the real agent loop in
services/llm_runner.run_stream. litellm.acompletion is stubbed with LiteLLM's own response /
stream types, so no network call is made."""
import asyncio
import json

import litellm
import pytest
from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices, Usage

import llm
from llm.backends import litellm as litellm_backend
from models import LLMConfig, PromptRunRequest
from services.llm_runner import run_stream

calls = []
stream_script = []   # one list of chunks per streamed call, consumed in order


def _chunk(content=None, tool_calls=None, finish_reason=None, usage=None):
    return ModelResponseStream(
        choices=[StreamingChoices(index=0, delta=Delta(content=content, tool_calls=tool_calls),
                                  finish_reason=finish_reason)],
        **({"usage": usage} if usage else {}),
    )


@pytest.fixture(scope="module", autouse=True)
def _fake_litellm(env):
    real_acompletion = litellm_backend.litellm.acompletion

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if kwargs.get("stream"):
            chunks = stream_script.pop(0)

            async def gen():
                for c in chunks:
                    yield c
            return gen()
        # Non-streaming: LiteLLM's own mock gives a real ModelResponse (with usage + a price)
        return await real_acompletion(model="gpt-4o", messages=kwargs["messages"], mock_response="Pong")

    env.setattr(litellm_backend.litellm, "acompletion", fake_acompletion)
    # These tests drive the LiteLLM backend, so `auto` must pick it for openai
    env.setattr(llm.backends, "ADAPTER_FIRST", llm.backends.ADAPTER_FIRST - {"openai"})


async def _collect(req):
    return [json.loads(line[6:]) async for part in run_stream(req)
            for line in part.splitlines() if line.startswith("data: ")]


def collect(req):
    calls.clear()
    return asyncio.run(_collect(req))


def kwargs_for(**fields):
    return litellm_backend._kwargs(llm.LLMRequest(messages=[], **fields))


def test_model_strings():
    ms = litellm_backend.model_string
    assert ms("openai", "gpt-4o") == "gpt-4o"
    assert ms("jan", "m") == "openai/m"
    assert ms("llamacpp", "m") == "llamafile/m"
    assert all(ms(p, "m") == f"{p}/m" for p in ("deepseek", "xai", "cerebras", "perplexity", "huggingface"))
    assert ms("something", "m") == "m", "unknown provider passes the model through"
    assert ms("together", "m") == "together_ai/m"
    assert ms("nvidia", "nvidia/m") == "nvidia_nim/nvidia/m"
    assert ms("watsonx", "ibm/m") == "watsonx/ibm/m"
    assert ms("fireworks", "accounts/fireworks/models/m") == "fireworks_ai/accounts/fireworks/models/m"

    unroutable = []
    for p in ("openai", "anthropic", "groq", "gemini", "mistral", "together", "huggingface", "fireworks", "deepseek",
              "xai", "cerebras", "perplexity", "ollama", "llamacpp", "jan", "azure", "bedrock", "cohere", "nvidia", "watsonx"):
        try:
            litellm.get_llm_provider(ms(p, "some-model") if p != "openai" else "gpt-4o")
        except Exception:
            unroutable.append(p)
    assert not unroutable, "LiteLLM can route every provider we ship"


def test_auth_and_request_kwargs():
    assert kwargs_for(provider="openai", model="x", api_key="sk-1")["api_key"] == "sk-1"
    assert "api_key" not in kwargs_for(provider="openai", model="x"), "no key → server env"
    assert kwargs_for(provider="jan", model="x")["api_key"] == "jan-local"
    assert kwargs_for(provider="bedrock", model="x", api_key="AK")["aws_access_key_id"] == "AK"
    assert kwargs_for(provider="ollama", model="x")["api_base"] == "http://localhost:11434"
    assert kwargs_for(provider="openai", model="x", base_url="http://h/v1")["api_base"] == "http://h/v1"
    assert not {"temperature", "max_tokens", "top_p", "tools", "tool_choice", "timeout"} & set(
        kwargs_for(provider="openai", model="x")), "unset sampling fields are not sent"
    assert kwargs_for(provider="openai", model="x", timeout_s=3.0)["timeout"] == 3.0


def test_reasoning_model_kwargs():
    kwargs = kwargs_for(provider="openai", model="gpt-5.5", temperature=0.4, top_p=0.9, max_tokens=2048)
    assert kwargs["temperature"] == 1
    assert "top_p" not in kwargs
    assert kwargs["max_completion_tokens"] == 2048
    assert "max_tokens" not in kwargs


def test_backend_choice(monkeypatch):
    import os
    assert llm.backend_for("openai").id == "litellm"
    monkeypatch.setenv("LLM_BACKEND", "nope")
    with pytest.raises(llm.BackendUnavailable, match="available: openai_compat"):
        llm.backend_for("openai")
    monkeypatch.setenv("LLM_BACKEND", "litellm")
    assert llm.backend_for("anthropic").id == "litellm"
    assert "OLLAMA_API_BASE" not in os.environ, "no os.environ writes"


def test_complete():
    calls.clear()
    cfg = LLMConfig(provider="openai", model="gpt-4o", api_key="sk-test", top_p=0.5)
    resp = asyncio.run(llm.complete(llm.request_from_config(cfg, [{"role": "user", "content": "Ping"}], max_tokens=5)))
    assert resp.text == "Pong"
    assert resp.usage is not None and resp.usage.total_tokens > 0
    assert resp.cost_usd > 0
    assert "top_p" not in calls[-1] and calls[-1]["max_tokens"] == 5, "sampling settings aren't copied"
    assert calls[-1]["api_key"] == "sk-test"


def test_streamed_tool_call_through_agent_loop():
    stream_script[:] = [
        [   # step 1: the model calls the calculator, split across chunks the way providers stream it
            _chunk(tool_calls=[{"index": 0, "id": "call_1", "type": "function",
                                "function": {"name": "calcu", "arguments": ""}}]),
            _chunk(tool_calls=[{"index": 0, "function": {"name": "lator", "arguments": '{"input": '}}]),
            _chunk(tool_calls=[{"index": 0, "function": {"arguments": '"2+3"}'}}]),
            _chunk(finish_reason="tool_calls"),
        ],
        [   # step 2: the answer
            _chunk(content="The answer "),
            _chunk(content="is 5."),
            _chunk(finish_reason="stop", usage=Usage(prompt_tokens=11, completion_tokens=4, total_tokens=15)),
        ],
    ]
    events = collect(PromptRunRequest(
        prompt="What is 2+3?", config=LLMConfig(provider="openai", model="gpt-4o", api_key="sk-test"),
        attached_tools=[{"toolId": "calculator", "label": "calculator", "config": {}}],
    ))
    by_type = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)

    assert len(calls) == 2, "tool step + answer"
    assert calls[0]["tools"][0]["function"]["name"] == "calculator" and calls[0]["tool_choice"] == "auto"
    assert by_type["tool_call"][0]["name"] == "calculator" and by_type["tool_call"][0]["input"] == "2+3", \
        "fragmented tool call is reassembled"
    assert "5" in by_type["tool"][0]["output"]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "call_1" for m in calls[1]["messages"])
    assert "".join(e["text"] for e in by_type["token"]) == "The answer is 5."
    assert by_type["meta"][0]["usage"]["total_tokens"] == 15
    assert events[-1]["type"] == "done" and "error" not in by_type


def test_single_call_local_path(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND_OLLAMA", "litellm")   # auto picks our adapter for Ollama; this tests LiteLLM's path
    stream_script[:] = [[_chunk(content="Hi "), _chunk(content="there"), _chunk(finish_reason="stop")]]
    events = collect(PromptRunRequest(prompt="Hello", config=LLMConfig(provider="ollama", model="llama3.2")))
    assert calls[0]["model"] == "ollama/llama3.2" and calls[0]["api_base"] == "http://localhost:11434"
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Hi there"
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["cost_usd"] == 0 and meta["usage"]["total_tokens"] > 0, "free, usage estimated"
