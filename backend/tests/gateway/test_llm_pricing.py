"""The gateway's price table (llm/pricing.py): cost math (cache reads / writes, long-context
tiers), free and unknown models, the data-folder override, that the gateway prices complete()
and stream() from usage — and, while LiteLLM is installed, that every catalog model costs
exactly what LiteLLM would charge."""
import asyncio
import json
import logging
import math
import os

import pytest

import llm
from llm import pricing
from llm.base import Usage
from paths import data_path

OVERRIDE_DIR = data_path("prices")


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-15)


def write_override(provider, models, says=None):
    with open(os.path.join(OVERRIDE_DIR, f"{provider}.json"), "w") as f:
        json.dump({"provider": says or provider, "models": models}, f)


@pytest.fixture(scope="module")
def docs():
    """The bundled tables: one file per provider."""
    out = {}
    for name in sorted(n for n in os.listdir(pricing.BUNDLED_DIR) if n.endswith(".json")):
        with open(os.path.join(pricing.BUNDLED_DIR, name)) as f:
            out[name[:-5]] = json.load(f)
    return out


@pytest.fixture
def overrides():
    """An empty <data dir>/prices for the test, removed afterwards."""
    os.makedirs(OVERRIDE_DIR, exist_ok=True)
    yield
    for name in os.listdir(OVERRIDE_DIR):
        os.remove(os.path.join(OVERRIDE_DIR, name))
    pricing.reload()


@pytest.fixture
def log_lines():
    class Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record.getMessage())

    cap = Capture()
    logging.getLogger("pipesets-ai-backend").addHandler(cap)
    yield cap.records
    logging.getLogger("pipesets-ai-backend").removeHandler(cap)


def test_bundled_tables(docs):
    assert {"openai", "anthropic", "gemini", "groq", "mistral", "bedrock", "azure"} <= set(docs)
    assert all(d.get("provider") == p for p, d in docs.items()), "each file names its own provider"
    assert all(d.get("unit") == "USD per 1M tokens" for d in docs.values())
    assert not set(docs) & pricing.FREE_PROVIDERS, "no file prices a local provider"
    # Keys are the model name as set on the node — which may itself contain "/" — never LiteLLM's route prefix
    assert not any(m.startswith(("together_ai/", "fireworks_ai/", "bedrock_converse/", "cohere_chat/"))
                   for d in docs.values() for m in d["models"])
    assert all(isinstance(v.get("in"), (int, float)) and isinstance(v.get("out"), (int, float))
               for d in docs.values() for v in d["models"].values())
    assert len(pricing.table()) == sum(len(d["models"]) for d in docs.values()) > 1000


def test_cost_math_and_overrides(docs, overrides, log_lines):
    write_override("acme", {
        "basic": {"in": 2.0, "out": 10.0},
        "cached": {"in": 3.0, "out": 15.0, "cache_read": 0.3, "cache_write": 3.75},
        "long": {"in": 1.0, "out": 4.0, "tiers": [{"above": 200000, "in": 2.0, "out": 6.0}]},
    })
    write_override("openai", {"gpt-4o": {"in": 100.0, "out": 100.0}})
    pricing.reload()

    assert close(pricing.cost_usd("acme", "basic", Usage(1000, 500, 1500)), (1000 * 2.0 + 500 * 10.0) / 1e6)
    assert close(pricing.cost_usd("acme", "cached", Usage(5000, 300, 5300, cache_read_tokens=1000, cache_write_tokens=2000)),
                 (2000 * 3.0 + 1000 * 0.3 + 2000 * 3.75 + 300 * 15.0) / 1e6), "cache reads / writes at their own rates"
    assert close(pricing.cost_usd("acme", "basic", Usage(1000, 0, 1000, cache_read_tokens=600)), 1000 * 2.0 / 1e6), \
        "no cache rate → cached tokens billed as input"
    assert close(pricing.cost_usd("acme", "long", Usage(200000, 100, 200100)), (200000 * 1.0 + 100 * 4.0) / 1e6)
    assert close(pricing.cost_usd("acme", "long", Usage(200001, 100, 200101)), (200001 * 2.0 + 100 * 6.0) / 1e6), \
        "above a tier threshold: tier rates for the whole call"
    assert close(pricing.cost_usd("openai", "gpt-4o", Usage(1, 0, 1)), 100.0 / 1e6), "override wins"
    assert pricing.price_for("openai", "gpt-4o-mini") == docs["openai"]["models"]["gpt-4o-mini"], \
        "an override replaces only the models it lists"
    assert pricing.price_for("anthropic", "claude-sonnet-4-5") is not None
    assert pricing.price_for("ACME", "basic") is not None, "provider is case-insensitive"
    assert pricing.cost_usd("acme", "basic", None) == 0.0
    assert all(pricing.cost_usd(p, "anything", Usage(1000, 1000, 2000)) == 0.0
               for p in ("ollama", "llamacpp", "jan", "local", "mock")), "local providers are free"

    assert pricing.cost_usd("acme", "mystery", Usage(1000, 1000, 2000)) == 0.0
    pricing.cost_usd("acme", "mystery", Usage(1000, 1000, 2000))
    warnings = [m for m in log_lines if "acme/mystery" in m]
    assert len(warnings) == 1 and "llm/prices/acme.json" in warnings[0], "unknown model warns once, naming the file"

    bundled_gpt4o = docs["openai"]["models"]["gpt-4o"]
    with open(os.path.join(OVERRIDE_DIR, "openai.json"), "w") as f:
        f.write("{not json")
    pricing.reload()
    assert pricing.price_for("openai", "gpt-4o") == bundled_gpt4o and any("Ignoring" in m for m in log_lines), \
        "a broken override file is ignored"
    assert pricing.price_for("acme", "basic") is not None, "other override files still apply"
    write_override("openai", {"gpt-4o": {"in": 1.0, "out": 1.0}}, says="anthropic")
    pricing.reload()
    assert pricing.price_for("openai", "gpt-4o") == bundled_gpt4o and pricing.price_for("anthropic", "gpt-4o") is None, \
        "an override file naming another provider is ignored"


def test_gateway_prices_backend_usage(docs, monkeypatch):
    gpt4o = docs["openai"]["models"]["gpt-4o"]
    monkeypatch.setattr(llm.backends, "ADAPTER_FIRST", set())   # one backend (LiteLLM) serves both calls below
    backend = llm.backend_for("openai")

    async def fake_complete(req):
        return llm.LLMResponse(text="ok", usage=Usage(1000, 100, 1100, cache_read_tokens=400))

    class FakeStream:
        usage = None

        async def __aiter__(self):
            yield llm.Chunk(text="ok")
            self.usage = Usage(1000, 100, 1100)

    async def fake_stream(req):
        return FakeStream()

    monkeypatch.setattr(backend, "complete", fake_complete)
    monkeypatch.setattr(backend, "stream", fake_stream)
    req = llm.LLMRequest(provider="openai", model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    resp = asyncio.run(llm.complete(req))
    assert close(resp.cost_usd, (600 * gpt4o["in"] + 400 * gpt4o["cache_read"] + 100 * gpt4o["out"]) / 1e6)

    async def read_stream():
        s = await llm.stream(req)
        before = s.cost_usd
        async for _ in s:
            pass
        return before, s.cost_usd

    before, after = asyncio.run(read_stream())
    assert before == 0.0, "no cost before the usage arrives"
    assert close(after, (1000 * gpt4o["in"] + 100 * gpt4o["out"]) / 1e6)
    free = asyncio.run(llm.complete(llm.LLMRequest(provider="ollama", model="llama3.2", messages=[]),
                                    backend_id="litellm"))
    assert free.cost_usd == 0.0, "fallback models are priced as themselves"


def test_parity_with_litellm():
    litellm = pytest.importorskip("litellm")
    from litellm.types.utils import PromptTokensDetailsWrapper, Usage as LiteUsage

    from llm.backends.litellm import model_string
    from routers.run import get_supported_models

    compared, mismatched = 0, []
    for p in asyncio.run(get_supported_models())["providers"]:
        for m in p["models"]:
            if pricing.price_for(p["id"], m) is None:
                continue
            for prompt, out, read in ((1000, 200, 0), (5000, 300, 3000), (300_000, 1000, 0)):
                lu = LiteUsage(prompt_tokens=prompt, completion_tokens=out, total_tokens=prompt + out,
                               prompt_tokens_details=PromptTokensDetailsWrapper(cached_tokens=read or None))
                try:
                    theirs = sum(litellm.cost_per_token(model=model_string(p["id"], m), usage_object=lu))
                except Exception:
                    continue
                ours = pricing.cost_usd(p["id"], m, Usage(prompt, out, prompt + out, cache_read_tokens=read))
                compared += 1
                if not math.isclose(ours, theirs, rel_tol=1e-6, abs_tol=1e-12):
                    mismatched.append(f"{p['id']}/{m} ({prompt}/{out}/{read}): {ours} vs {theirs}")
    assert compared > 20 and not mismatched, mismatched[:3]
