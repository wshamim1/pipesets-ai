"""Regenerate llm/prices/<provider>.json from LiteLLM's price map.

Run from the backend directory:   python scripts/seed_prices.py

One-off tool for while LiteLLM is still installed (plan.md A5 step 2). Once it is removed,
the files are maintained by hand: add or fix a model in a reviewed PR, or override locally in
<data dir>/prices/<provider>.json. Re-running this replaces every entry with LiteLLM's.
"""
import json
import os
import re
import sys
from datetime import date
from importlib.metadata import version

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import litellm  # noqa: E402

OUT_DIR = os.path.join(BACKEND_DIR, "llm", "prices")

# LiteLLM provider → our provider id. Others (vertex_ai, azure_ai, …) aren't providers we ship.
PROVIDERS = {
    "openai": "openai", "anthropic": "anthropic", "groq": "groq", "gemini": "gemini",
    "mistral": "mistral", "together_ai": "together", "fireworks_ai": "fireworks",
    "deepseek": "deepseek", "xai": "xai", "cerebras": "cerebras", "perplexity": "perplexity",
    "azure": "azure", "bedrock": "bedrock", "bedrock_converse": "bedrock", "cohere_chat": "cohere",
    "watsonx": "watsonx",
}
PER_M = 1_000_000
# Plain long-context tiers only ("…_above_200k_tokens"), not batch / priority / flex variants
TIER = re.compile(r"^(input_cost_per_token|output_cost_per_token|cache_read_input_token_cost|"
                  r"cache_creation_input_token_cost)_above_(\d+)k_tokens$")
FIELDS = {"input_cost_per_token": "in", "output_cost_per_token": "out",
          "cache_read_input_token_cost": "cache_read", "cache_creation_input_token_cost": "cache_write"}


def per_m(v):
    return round(float(v) * PER_M, 6)


def entry(e):
    price = {short: per_m(e[k]) for k, short in FIELDS.items() if e.get(k) is not None}
    if "cache_read" not in price and e.get("input_cost_per_token_cache_hit") is not None:
        price["cache_read"] = per_m(e["input_cost_per_token_cache_hit"])
    tiers = {}
    for k, v in e.items():
        m = TIER.match(k)
        if m and v is not None:
            tiers.setdefault(int(m.group(2)) * 1000, {})[FIELDS[m.group(1)]] = per_m(v)
    if tiers:
        price["tiers"] = [{"above": n, **t} for n, t in sorted(tiers.items())]
    return price


def write(provider, models, source):
    header = {
        "provider": provider,
        "_about": "Model prices for the LLM gateway (llm/pricing.py), keyed by the model name set on "
                  "the LLM node. Override or add locally in <data dir>/prices/<provider>.json.",
        "unit": "USD per 1M tokens",
        "source": source,
    }
    # One model per line so a price change is a one-line diff
    lines = [f'    "{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in sorted(models.items())]
    with open(os.path.join(OUT_DIR, f"{provider}.json"), "w") as f:
        f.write("{\n")
        for k, v in header.items():
            f.write(f"  {json.dumps(k)}: {json.dumps(v)},\n")
        f.write('  "models": {\n' + ",\n".join(lines) + "\n  }\n}\n")


def main():
    by_provider = {}
    for key, e in litellm.model_cost.items():
        if not isinstance(e, dict) or e.get("mode") not in ("chat", "responses"):
            continue
        ours = PROVIDERS.get(e.get("litellm_provider"))
        if not ours or e.get("input_cost_per_token") is None or e.get("output_cost_per_token") is None:
            continue
        model = key
        for prefix in (f"{e['litellm_provider']}/", f"{ours}/"):
            if model.startswith(prefix):
                model = model[len(prefix):]
                break
        # The same model can appear bare and prefixed ("deepseek-chat", "deepseek/deepseek-chat")
        # with different fields filled in; keep the first value of each field
        price = entry(e)
        if ours == "fireworks" and "cache_read" not in price:
            # Fireworks bills cached prompt tokens at half the input rate (LiteLLM applies
            # this in code, not in its price map)
            price["cache_read"] = round(price["in"] / 2, 6)
        models = by_provider.setdefault(ours, {})
        models[model] = {**price, **models.get(model, {})}

    os.makedirs(OUT_DIR, exist_ok=True)
    source = f"LiteLLM {version('litellm')} model_cost via scripts/seed_prices.py, {date.today().isoformat()}"
    for provider, models in sorted(by_provider.items()):
        write(provider, models, source)
        print(f"{provider:11} {len(models):5} models")
    print(f"wrote {sum(map(len, by_provider.values()))} models to {OUT_DIR}/")


if __name__ == "__main__":
    main()
