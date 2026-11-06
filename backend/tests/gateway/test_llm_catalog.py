"""The model catalog (llm/catalog.py): every listed paid model has a price, so no run records
$0 by accident; the defaults are listed; and the frontend's copies agree with it."""
import os
import re

import pytest

from llm import pricing
from llm.catalog import DEFAULT_MODELS, PROVIDERS

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "src")
BY_ID = {p["id"]: p for p in PROVIDERS}


def paid(p):
    return not p.get("local") and p["id"] not in pricing.FREE_PROVIDERS and "unpriced" not in p


def ts_rows(path):
    """``{ id: '…', …, models: ['…', …] }`` rows of a frontend provider list."""
    with open(path) as f:
        text = f.read()
    return {m.group(1): re.findall(r"'([^']*)'", m.group(2))
            for m in re.finditer(r"\{ id: '([^']+)',[^\n]*?models: \[([^\]]*)\]", text)}


def test_ids_unique_and_models_listed():
    assert len(BY_ID) == len(PROVIDERS)
    for p in PROVIDERS:
        assert p.get("local") or p["models"], p["id"]
        assert len(set(p["models"])) == len(p["models"]), p["id"]


@pytest.mark.parametrize("provider", [p["id"] for p in PROVIDERS if paid(p)])
def test_every_paid_model_has_a_price(provider):
    missing = [m for m in BY_ID[provider]["models"] if pricing.price_for(provider, m) is None]
    assert not missing, (f"{provider}: {missing} have no price in llm/prices/{provider}.json — "
                         "add one, or drop the model if the provider retired it")


def test_unpriced_providers_really_have_no_price_table():
    for p in PROVIDERS:
        if "unpriced" in p:
            assert not os.path.exists(os.path.join(pricing.BUNDLED_DIR, f"{p['id']}.json")), \
                f"{p['id']} has a price table now — drop its 'unpriced' flag"


def test_defaults_are_listed():
    for provider, model in DEFAULT_MODELS.items():
        p = BY_ID[provider]
        assert p.get("local") or model in p["models"], (provider, model)


def test_frontend_fallback_matches():
    rows = ts_rows(os.path.join(FRONTEND, "hooks", "useCatalogData.ts"))
    assert rows == {p["id"]: p["models"] for p in PROVIDERS}, \
        "frontend/src/hooks/useCatalogData.ts DEFAULT_PROVIDERS is out of step with llm/catalog.py"


@pytest.mark.parametrize("panel", ["MasterAgentConfigPanel.tsx", "ChildAgentConfigPanel.tsx"])
def test_agent_panels_offer_catalog_models(panel):
    for provider, models in ts_rows(os.path.join(FRONTEND, "components", "config", panel)).items():
        p = BY_ID[provider]
        if not p.get("local"):
            assert set(models) <= set(p["models"]), (panel, provider, set(models) - set(p["models"]))


def test_api_models_serves_the_catalog(client, monkeypatch):
    from routers import run

    async def local_models(*_a, **_k):
        return ["m"]
    for f in ("_fetch_ollama_models", "_fetch_llamacpp_models", "_fetch_jan_models"):
        monkeypatch.setattr(run, f, local_models)
    served = {p["id"]: p for p in client.get("/api/models").json()["providers"]}
    assert served["anthropic"]["models"] == BY_ID["anthropic"]["models"]
    assert served["ollama"]["models"] == ["m"]
