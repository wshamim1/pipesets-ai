"""
pricing.py — what a model call costs, from our own price table.

Prices live in ``llm/prices/<provider>.json``, one file per provider (USD per 1M tokens, keyed
by model name), seeded from LiteLLM by ``scripts/seed_prices.py`` and maintained by hand after
that. Files of the same shape in ``<data dir>/prices/`` (paths.DATA_DIR) are merged over them
model by model, so a deployment can add or correct a model, or a whole provider, without a
release.

Cost is computed from the token usage the backend reports, so a run costs the same
whichever backend served it. ``prompt_tokens`` includes cached tokens (OpenAI's convention,
which every backend normalises to): cache reads and writes are billed at their own rates
and the rest at the input rate. A long-context tier applies once the prompt exceeds its
threshold. Local providers cost nothing; an unknown paid model costs 0 and logs a warning
once, so a missing price shows up in the log instead of silently.
"""

import json
import logging
import os
from typing import Any, Dict, Optional, Set, Tuple

from llm.base import Usage
from paths import data_path

logger = logging.getLogger("pipesets-ai-backend")

FREE_PROVIDERS = {"ollama", "llamacpp", "jan", "local", "mock"}
BUNDLED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices")

# "<provider>/<model>" → price, across every provider file
_table: Optional[Dict[str, Dict[str, Any]]] = None
_warned: Set[Tuple[str, str]] = set()


def _read_dir(directory: str, strict: bool) -> Dict[str, Dict[str, Any]]:
    """Every ``<provider>.json`` in ``directory``. A broken bundled file is a bug and raises;
    a broken override is logged and skipped."""
    prices: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(directory):
        return prices
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        provider = name[:-len(".json")].lower()
        try:
            with open(path) as f:
                doc = json.load(f)
            if doc.get("provider", provider).lower() != provider:
                raise ValueError(f"says provider {doc['provider']!r} but is named {name}")
            models = doc.get("models", {})
        except (OSError, ValueError) as e:
            if strict:
                raise
            logger.error("Ignoring %s: %s", path, e)
            continue
        prices.update({f"{provider}/{model}": price for model, price in models.items()})
    return prices


def table() -> Dict[str, Dict[str, Any]]:
    global _table
    if _table is None:
        merged = _read_dir(BUNDLED_DIR, strict=True)
        merged.update(_read_dir(data_path("prices"), strict=False))
        _table = merged
    return _table


def reload() -> None:
    global _table
    _table = None
    _warned.clear()


def price_for(provider: str, model: str) -> Optional[Dict[str, Any]]:
    models = table()
    key = f"{(provider or '').lower()}/{model}"
    return models.get(key) or models.get(key.lower())


def cost_usd(provider: str, model: str, usage: Optional[Usage]) -> float:
    if not usage or (provider or "").lower() in FREE_PROVIDERS:
        return 0.0
    price = price_for(provider, model)
    if price is None:
        if (provider, model) not in _warned:
            _warned.add((provider, model))
            logger.warning("No price for %s/%s — its cost is recorded as $0. Add it to "
                           "llm/prices/%s.json or %s.", provider, model, (provider or "").lower(),
                           data_path("prices", f"{(provider or '').lower()}.json"))
        return 0.0

    rates = dict(price)
    for tier in price.get("tiers", []):
        if usage.prompt_tokens > tier["above"]:
            rates.update({k: v for k, v in tier.items() if k != "above"})

    cache_read = usage.cache_read_tokens
    cache_write = usage.cache_write_tokens
    uncached = max(0, usage.prompt_tokens - cache_read - cache_write)
    total = (uncached * rates["in"]
             + cache_read * rates.get("cache_read", rates["in"])
             + cache_write * rates.get("cache_write", rates["in"])
             + usage.completion_tokens * rates["out"])
    return total / 1_000_000
