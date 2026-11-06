"""
Contract tests for the LLM gateway (plan.md A5 step 5).

Every cassette in tests/gateway/llm_contract/ is replayed under every backend that speaks its wire
format for the provider — our own adapter and LiteLLM — through the public gateway
(``llm.complete`` / ``llm.stream``), and each must produce the same result: text, assembled
tool calls, finish reason, usage, cost and typed ``LLMError``s. The fake transport sits under
httpx and httpx2 (the Anthropic SDK's client), so the backends' real request and parsing code
runs; real sockets are blocked.
"""

import asyncio
import json
import socket
from pathlib import Path

import httpx
import httpx2
import litellm
import pytest

import llm
from llm import pricing

CASSETTES = Path(__file__).parent / "llm_contract"
API_KEY = "sk-contract-test-0000000000"

# (wire format, provider) -> backends that send that format. LiteLLM talks to Ollama through
# its native /api/generate route, so only our adapter is checked on Ollama's OpenAI endpoint.
BACKENDS = {
    ("openai_chat", "openai"): ["openai_compat", "litellm"],
    ("openai_chat", "jan"): ["openai_compat", "litellm"],
    ("openai_chat", "llamacpp"): ["openai_compat", "litellm"],
    ("openai_chat", "ollama"): ["openai_compat"],
    ("anthropic_messages", "anthropic"): ["anthropic", "litellm"],
}
PATHS = {"openai_chat": "/chat/completions", "anthropic_messages": "/v1/messages"}

# Where LiteLLM can't meet the contract, and what it gives instead: (provider, cassette or "*",
# mode or "*") -> expectation overrides. Each is a reason to prefer our adapter, not a target.
LITELLM_GAPS = {
    # LiteLLM replaces Anthropic's 529 (overloaded) with a synthetic 500; still retryable
    ("anthropic", "error_529", "*"): {"status": 500},
    # Jan isn't asked for stream usage (its server may not know stream_options) and LiteLLM
    # drops usage it didn't ask for; the runtime estimates tokens, and a local model costs $0
    ("jan", "*", "stream"): {"usage": None},
}


def _gap(backend, provider_id, name, mode):
    if backend != "litellm":
        return {}
    out = {}
    for (p, n, m), override in LITELLM_GAPS.items():
        if p == provider_id and n in ("*", name) and m in ("*", mode):
            out.update(override)
    return out


def _cassettes():
    for path in sorted(CASSETTES.glob("*/*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        wire = path.parent.name
        for provider, model in case["providers"].items():
            for backend in BACKENDS[(wire, provider)]:
                for mode in case.get("modes", ["stream", "complete"]):
                    yield pytest.param(wire, {**case, "name": path.stem}, provider, model, backend, mode,
                                       id=f"{wire}/{path.stem}-{provider}-{backend}-{mode}")


def _sse(wire: str, events) -> bytes:
    out = []
    for ev in events:
        if ev == "[DONE]":
            out.append("data: [DONE]\n\n")
        elif wire == "anthropic_messages":
            out.append(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n")
        else:
            out.append(f"data: {json.dumps(ev)}\n\n")
    return "".join(out).encode()


class FakeProvider:
    """Answers every HTTP request from the current cassette and keeps the requests."""

    def __init__(self):
        self.wire = ""
        self.responses = {}
        self.requests = []

    def load(self, wire, case):
        self.wire, self.responses, self.requests = wire, case["responses"], []

    def respond(self, module, request):
        body = json.loads(request.content or b"{}")
        self.requests.append((str(request.url), body))
        assert str(request.url.path).endswith(PATHS[self.wire]), f"unexpected request to {request.url}"
        streamed = bool(body.get("stream"))
        r = self.responses["stream" if streamed else "complete"]
        if r["status"] != 200 or not streamed:
            return module.Response(r["status"], json=r["body"])
        content = r["raw"].encode() if "raw" in r else _sse(self.wire, r["events"])
        return module.Response(200, content=content, headers={"content-type": "text/event-stream"})


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()

    def handler(module):
        async def handle_async_request(self, request):
            return fake.respond(module, request)
        return handle_async_request

    def blocked(*args, **kwargs):
        raise OSError("contract tests never reach the network")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handler(httpx))
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", handler(httpx2))
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)   # so LiteLLM uses httpx too
    for var in ("LLM_BACKEND", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JAN_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return fake


def _request(case, provider, model):
    r = case["request"]
    return llm.LLMRequest(provider=provider, model=model, messages=r["messages"], api_key=API_KEY,
                          max_tokens=r.get("max_tokens"), temperature=r.get("temperature"),
                          tools=r.get("tools"), tool_choice=r.get("tool_choice"))


async def _run(req, backend, mode):
    """Normalized result: what a caller of the gateway sees."""
    if mode == "complete":
        resp = await llm.complete(req, backend_id=backend)
        return {"text": resp.text, "finish_reason": resp.finish_reason, "tool_calls": [],
                "usage": resp.usage, "cost_usd": resp.cost_usd}
    stream = await llm.stream(req, backend_id=backend)
    text, finish, calls = [], None, {}
    async for chunk in stream:
        text.append(chunk.text)
        finish = chunk.finish_reason or finish
        for tc in chunk.tool_calls:
            call = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            call["id"] = call["id"] or tc.id
            call["name"] = call["name"] or tc.name
            call["arguments"] += tc.arguments
    tool_calls = [{**c, "arguments": json.loads(c["arguments"] or "{}")} for _, c in sorted(calls.items())]
    return {"text": "".join(text), "finish_reason": finish, "tool_calls": tool_calls,
            "usage": stream.usage, "cost_usd": stream.cost_usd}


@pytest.mark.parametrize("wire,case,provider_id,model,backend,mode", _cassettes())
def test_contract(provider, wire, case, provider_id, model, backend, mode):
    provider.load(wire, case)
    req = _request(case, provider_id, model)
    expect = case["expect"]
    gap = _gap(backend, provider_id, case["name"], mode)

    if "error" in expect:
        want = {**expect["error"], **gap}
        with pytest.raises(llm.LLMError) as caught:
            asyncio.run(_run(req, backend, mode))
        e = caught.value
        if "status" in want:
            assert e.status == want["status"]
        if "retryable" in want:
            assert e.retryable is want["retryable"]
        assert want["message_contains"] in str(e)
        return

    got = asyncio.run(_run(req, backend, mode))
    assert got["text"] == expect["text"]
    assert got["finish_reason"] == expect["finish_reason"]
    assert got["tool_calls"] == expect.get("tool_calls", [])

    usage = got["usage"]
    if "usage" in gap and gap["usage"] is None:
        assert usage is None and got["cost_usd"] == 0
        return
    assert usage is not None, "no usage reported — the run would be recorded as free"
    want = {"cache_read_tokens": 0, "cache_write_tokens": 0, **expect["usage"]}
    assert {k: getattr(usage, k) for k in want} == want

    # The same run costs the same whichever backend served it
    assert got["cost_usd"] == pytest.approx(pricing.cost_usd(provider_id, model, llm.Usage(**want)))
    if provider_id in ("openai", "anthropic"):
        assert got["cost_usd"] > 0


@pytest.mark.parametrize("backend", ["openai_compat", "litellm"])
def test_streamed_openai_request_asks_for_usage(provider, backend):
    """Without stream_options.include_usage OpenAI sends no usage, and the run costs $0."""
    case = json.loads((CASSETTES / "openai_chat" / "text.json").read_text())
    provider.load("openai_chat", case)
    asyncio.run(_run(_request(case, "openai", "gpt-4o-mini"), backend, "stream"))
    _, body = provider.requests[-1]
    assert body.get("stream_options", {}).get("include_usage") is True


def test_every_cassette_runs_on_an_adapter_of_ours():
    for path in CASSETTES.glob("*/*.json"):
        case = json.loads(path.read_text())
        for provider_id in case["providers"]:
            assert any(b != "litellm" for b in BACKENDS[(path.parent.name, provider_id)]), (path, provider_id)
