"""Crypto price (CoinGecko) — built-in tool `crypto_price`."""

from typing import Any, Dict, Optional

import httpx

from tools._choices import CURRENCIES
from tools.base import Select, ToolSpec, enum, params

TOOL = ToolSpec(
    id="crypto_price",
    name="Crypto Prices",
    icon="🪙",
    category="APIs & Integrations",
    description="Live cryptocurrency prices and 24h change from CoinGecko (free, no key). Input like 'BTC, ethereum'.",
    default_config={"vs_currency": "usd"},
    order=40,
    selects={
        "vs_currency": Select("Quote currency", CURRENCIES),
    },
    parameters=params(
        {"coins": {"type": "string", "description": "Coins, comma-separated, e.g. BTC, ethereum"}},
        {
            "vs_currency": enum(["usd", "eur", "gbp", "jpy", "inr", "cad", "aud", "chf", "cny", "btc", "eth"], "Price currency"),
        },
    ),
    input_param="coins",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    vs = cfg.get("vs_currency", "usd").lower()
    names = [n.strip() for n in inp.replace(" and ", ",").split(",") if n.strip()] or ["bitcoin"]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            ids = []
            for name in names[:10]:
                # Resolve "BTC" / "ethereum" / "Solana" to a CoinGecko coin id
                sr = await client.get("https://api.coingecko.com/api/v3/search", params={"query": name})
                sr.raise_for_status()
                coins = sr.json().get("coins", [])
                if coins:
                    ids.append((coins[0]["id"], f"{coins[0]['name']} ({coins[0]['symbol']})"))
            if not ids:
                return f"[Crypto] No coins found for: {inp}"
            pr = await client.get("https://api.coingecko.com/api/v3/simple/price", params={
                "ids": ",".join(i for i, _ in ids), "vs_currencies": vs, "include_24hr_change": "true",
            })
            pr.raise_for_status()
            prices = pr.json()
        lines = [f"[Crypto prices in {vs.upper()}]"]
        for coin_id, label in ids:
            p = prices.get(coin_id, {})
            change = p.get(f"{vs}_24h_change")
            lines.append(f"  {label}: {p.get(vs, '?'):,} {vs.upper()}" + (f" ({change:+.2f}% 24h)" if change is not None else ""))
        return "\n".join(lines)
    except Exception as e:
        return f"[Crypto] Error: {e}"
