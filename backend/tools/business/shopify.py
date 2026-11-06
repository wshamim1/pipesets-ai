"""Shopify — built-in tool `shopify` (Admin REST API, read-only).

Actions: ``orders`` / ``products`` / ``customers`` — the recent entries of one, optionally filtered
by a name / number / email substring (matched client-side across the fetched page). Auth is an
Admin API access token for one shop domain in the node config; a read_content scope token is
enough.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Shopify]"
VERSIONS = ("2024-10",)


def _error(resp: httpx.Response) -> str:
    if resp.status_code == 401:
        return f"{LABEL} The access_token is invalid or lacks read access for this shop."
    if resp.status_code == 404:
        return f"{LABEL} Shop or API version not found — check shop_domain."
    try:
        message = str(resp.json().get("errors") or resp.json().get("error") or resp.text)[:300]
    except Exception:
        message = resp.text[:300]
    return f"{LABEL} HTTP {resp.status_code}: {message}"


def _matches(entry: Dict[str, Any], needle: str) -> bool:
    n = needle.casefold()
    return any(n in str(v).casefold() for v in entry.values() if isinstance(v, (str, int)))


TOOL = ToolSpec(
    id="shopify",
    name="Shopify",
    icon="🛍️",
    category="Business Apps",
    description=("Looks up Shopify orders, products or customers (read-only): recent entries of "
                 "the chosen resource, optionally filtered by a substring of the name / number / "
                 "email. Admin API access token + shop domain in config."),
    default_config={"shop_domain": "", "access_token": "", "action": "orders", "api_version": "2024-10",
                    "max_results": 25},
    order=90,
    required=("shop_domain", "access_token"),
    selects={"action": Select("Action", (("orders", "Recent orders"), ("products", "Products"),
                                         ("customers", "Customers")))},
    parameters=params(
        {"search": {"type": "string", "description": "Substring to filter by (order #, product title, customer name / email); empty = the most recent"}},
        {
            "action": enum(["orders", "products", "customers"], "What to look up"),
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Most entries to fetch"},
        },
    ),
    input_param="search",
)


def _line_order(o: Dict[str, Any]) -> str:
    bits = [f"{o.get('name')}", f"{o.get('email') or '—'}", f"{o.get('financial_status') or '?'}",
            f"{o.get('fulfillment_status') or 'unfulfilled'}"]
    total = (o.get("total_price") or "")
    currency = o.get("currency") or ""
    return f"- {' · '.join(bits)} · {total} {currency}".rstrip()


def _line_product(p: Dict[str, Any]) -> str:
    return f"- {p.get('title')} · status {p.get('status') or '?'} · {'variant(s) ' + str(len(p.get('variants') or []))}"


def _line_customer(c: Dict[str, Any]) -> str:
    name = " ".join(str(x) for x in (c.get("first_name"), c.get("last_name")) if x).strip() or "(no name)"
    orders = f"{c.get('orders_count', 0)} order(s)"
    return f"- {name} · {c.get('email') or '—'} · {orders}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    domain = (cfg.get("shop_domain") or "").strip().replace("https://", "").strip("/")
    if not domain:
        return f"{LABEL} shop_domain is required in config (e.g. my-store.myshopify.com)."
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return f"{LABEL} access_token is required in config (an Admin API access token)."
    version = (cfg.get("api_version") or "2024-10").strip()
    action = (cfg.get("action") or "orders").strip().lower()
    if action not in ("orders", "products", "customers"):
        return f'{LABEL} Action is "orders", "products" or "customers" — got "{action}".'
    limit = min(max(int(cfg.get("max_results", 25) or 25), 1), 100)
    needle = str(inp or "").strip()

    path = {"orders": "orders.json?status=any&limit={}", "products": "products.json?limit={}",
            "customers": "customers.json?limit={}"}[action].format(limit)
    try:
        async with httpx.AsyncClient(timeout=25.0, headers={"X-Shopify-Access-Token": token,
                                                            "Accept": "application/json"}) as client:
            resp = await client.get(f"https://{domain}/admin/api/{version}/{path}")
    except Exception as e:
        return f"{LABEL} Error: {e}"
    if resp.status_code != 200:
        return _error(resp)
    entries: list = (resp.json() or {}).get(action) or []
    if needle:
        entries = [e for e in entries if _matches(e, needle)]
    if not entries:
        return f'{LABEL} No {action} match "{needle}".' if needle else f"{LABEL} No {action} in the shop yet."
    line = {"orders": _line_order, "products": _line_product, "customers": _line_customer}[action]
    scope = f' matching "{needle}"' if needle else " (most recent)"
    return f"{LABEL} {len(entries)} {action}{scope}\n\n" + "\n".join(line(e) for e in entries)
