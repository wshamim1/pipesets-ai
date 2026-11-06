"""Stock quote (Yahoo Finance, unofficial) — built-in tool `stock_quote`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

TOOL = ToolSpec(
    id="stock_quote",
    name="Stock Quotes",
    icon="💹",
    category="APIs & Integrations",
    description="Latest price and change for stock tickers from Yahoo Finance (unofficial, may be delayed). Input like 'AAPL, MSFT'.",
    default_config={"range": "5d"},
    order=50,
    selects={
        "range": Select("Compare against", (("1d", "Today"), ("5d", "5 days"), ("1mo", "1 month"), ("1y", "1 year"))),
    },
    parameters=params(
        {"tickers": {"type": "string", "description": "Tickers, comma-separated, e.g. AAPL, MSFT"}},
        {"range": enum(["1d", "5d", "1mo", "1y"], "Change over")},
    ),
    input_param="tickers",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    symbols = [s.strip().upper() for s in inp.replace(" and ", ",").replace(" ", ",").split(",") if s.strip()][:10]
    if not symbols:
        return "[Stocks] Provide ticker symbols, e.g. 'AAPL, MSFT'."
    lines = ["[Stock quotes — Yahoo Finance, may be delayed]"]
    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "Mozilla/5.0 (compatible; PipesetsAI/1.0)"}) as client:
            for sym in symbols:
                resp = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                                        params={"range": cfg.get("range", "5d"), "interval": "1d"})
                if resp.status_code == 404:
                    lines.append(f"  {sym}: unknown symbol")
                    continue
                resp.raise_for_status()
                res = (resp.json().get("chart", {}).get("result") or [{}])[0]
                meta = res.get("meta", {})
                price, prev = meta.get("regularMarketPrice"), meta.get("chartPreviousClose") or meta.get("previousClose")
                change = f" ({(price - prev) / prev * 100:+.2f}% vs prev close {prev:,.2f})" if price and prev else ""
                lines.append(f"  {sym} ({meta.get('fullExchangeName', meta.get('exchangeName', ''))}): "
                             f"{price:,.2f} {meta.get('currency', '')}{change}" if price else f"  {sym}: no price available")
        return "\n".join(lines)
    except Exception as e:
        return f"[Stocks] Error: {e}"
