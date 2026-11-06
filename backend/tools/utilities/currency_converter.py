"""Currency converter — built-in tool `currency_converter`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="currency_converter",
    name="Currency Converter",
    icon="💱",
    category="Everyday Utilities",
    description="Converts between currencies using daily ECB rates (free, no key). Input like '100 USD to EUR'.",
    default_config={"api_base": "https://api.frankfurter.dev/v1"},
    order=30,
    parameters=params({"amount": {"type": "number"}, "from_currency": {"type": "string", "description": "ISO code, e.g. USD"},
                       "to_currency": {"type": "string", "description": "ISO code, e.g. EUR"}}),
    to_input=lambda a: f"{a['amount']} {a['from_currency']} to {a['to_currency']}",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import re
    m = re.search(r"([\d.,]+)?\s*([A-Za-z]{3})\s*(?:to|in|->|=)\s*([A-Za-z]{3})", inp)
    if not m:
        return "[Currency] Input must look like '100 USD to EUR'."
    amount = float((m.group(1) or "1").replace(",", ""))
    src, dst = m.group(2).upper(), m.group(3).upper()
    api_base = cfg.get("api_base", "https://api.frankfurter.dev/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{api_base}/latest", params={"amount": amount, "from": src, "to": dst})
            if resp.status_code == 404:
                return f"[Currency] Unsupported currency pair: {src} → {dst}"
            resp.raise_for_status()
            d = resp.json()
        converted = d.get("rates", {}).get(dst)
        if converted is None:
            return f"[Currency] No rate available for {src} → {dst}"
        return f"[Currency] {amount:,.2f} {src} = {converted:,.2f} {dst} (ECB rate, {d.get('date', 'latest')})"
    except Exception as e:
        return f"[Currency] Error: {e}"
