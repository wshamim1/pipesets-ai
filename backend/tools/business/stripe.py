"""Stripe — built-in tool `stripe` (Stripe API, read-only).

Actions: ``customers`` (find by id, email, or name / email text), ``payments`` (recent
PaymentIntents), ``invoices``, ``subscriptions`` — each for one customer (id or email) or the whole
account — and ``balance``. It only reads: use a restricted key with read access to those resources.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Stripe]"
API = "https://api.stripe.com/v1"
ACTIONS = ("customers", "payments", "invoices", "subscriptions", "balance")
# https://docs.stripe.com/currencies#zero-decimal
ZERO_DECIMAL = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv",
                "xaf", "xof", "xpf"}

TOOL = ToolSpec(
    id="stripe",
    name="Stripe",
    icon="💳",
    category="Business Apps",
    description="Looks up Stripe customers, payments, invoices, subscriptions and the account balance (read-only). Input: a customer id (cus_…) or email, name text to search customers, or empty for the latest across the account.",
    default_config={"api_key": "", "action": "customers", "max_results": 10},
    order=70,
    required=("api_key",),
    selects={"action": Select("Action", (("customers", "Find customers"), ("payments", "Recent payments"),
                                         ("invoices", "Invoices"), ("subscriptions", "Subscriptions"),
                                         ("balance", "Account balance")))},
    parameters=params(
        {"customer": {"type": "string", "description": "Customer id (cus_…), email, or name text; empty = the whole account"}},
        {
            "action": enum(list(ACTIONS), "What to look up"),
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Items to return"},
        },
    ),
    input_param="customer",
)


def money(amount: Optional[int], currency: str) -> str:
    if amount is None:
        return "—"
    cur = (currency or "").lower()
    value = amount if cur in ZERO_DECIMAL else amount / 100
    return f"{value:,.0f} {cur.upper()}" if cur in ZERO_DECIMAL else f"{value:,.2f} {cur.upper()}"


def _error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        err = {}
    msg = err.get("message") or resp.text[:200]
    if resp.status_code == 401:
        return f"{LABEL} The api_key is invalid."
    if resp.status_code == 403:
        return f"{LABEL} The key doesn't have read access to this: {msg}"
    if resp.status_code == 404:
        return f"{LABEL} Not found: {msg}"
    return f"{LABEL} HTTP {resp.status_code}: {msg}"


def _customer_line(c: Dict[str, Any]) -> str:
    bits = [c.get("email"), c.get("phone"), f"created {_date(c.get('created'))}" if c.get("created") else None,
            "delinquent" if c.get("delinquent") else None]
    return f"- {c.get('name') or '(no name)'} ({c.get('id')})" + "".join(f" · {b}" for b in bits if b)


def _date(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


async def _customer_id(client: httpx.AsyncClient, who: str) -> Any:
    """The customer id for an id or email ('' = none given), or an error string."""
    if not who or who.startswith("cus_"):
        return who
    if "@" in who:
        resp = await client.get(f"{API}/customers", params={"email": who, "limit": 1})
        if resp.status_code != 200:
            return _error(resp)
        data = resp.json().get("data", [])
        return data[0]["id"] if data else f"{LABEL} No customer with email {who}."
    return f"{LABEL} Give a customer id (cus_…) or email — or leave it empty for the whole account."


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    key = (cfg.get("api_key") or "").strip()
    if not key:
        return f"{LABEL} api_key is required in config — use a restricted, read-only key (rk_…)."
    action = (cfg.get("action") or "customers").strip().lower()
    if action not in ACTIONS:
        return f"{LABEL} Action is one of {', '.join(ACTIONS)} — got \"{action}\"."
    limit = max(1, min(int(cfg.get("max_results") or 10), 100))
    who = inp.strip()

    async with httpx.AsyncClient(timeout=20.0, headers={"Authorization": f"Bearer {key}"}) as client:
        if action == "balance":
            resp = await client.get(f"{API}/balance")
            if resp.status_code != 200:
                return _error(resp)
            b = resp.json()
            avail = ", ".join(money(x.get("amount"), x.get("currency")) for x in b.get("available", [])) or "—"
            pending = ", ".join(money(x.get("amount"), x.get("currency")) for x in b.get("pending", [])) or "—"
            return f"{LABEL} Balance\nAvailable: {avail}\nPending: {pending}"

        if action == "customers":
            if who.startswith("cus_"):
                resp = await client.get(f"{API}/customers/{who}")
                if resp.status_code != 200:
                    return _error(resp)
                return f"{LABEL} Customer\n{_customer_line(resp.json())}"
            if "@" in who or not who:
                resp = await client.get(f"{API}/customers", params={"limit": limit, **({"email": who} if who else {})})
            else:
                q = who.replace("\\", "").replace('"', "")
                resp = await client.get(f"{API}/customers/search",
                                        params={"query": f'name~"{q}" OR email~"{q}"', "limit": limit})
            if resp.status_code != 200:
                return _error(resp)
            found = resp.json().get("data", [])
            if not found:
                return f"{LABEL} No customers match '{who}'." if who else f"{LABEL} No customers yet."
            return f"{LABEL} {len(found)} customer(s)\n\n" + "\n".join(_customer_line(c) for c in found)

        cid = await _customer_id(client, who)
        if cid.startswith(LABEL):
            return cid
        q: Dict[str, Any] = {"limit": limit, **({"customer": cid} if cid else {})}
        if action == "subscriptions":
            q["status"] = "all"
        path = {"payments": "payment_intents", "invoices": "invoices", "subscriptions": "subscriptions"}[action]
        resp = await client.get(f"{API}/{path}", params=q)
        if resp.status_code != 200:
            return _error(resp)
        items = resp.json().get("data", [])
        scope = f"for {who}" if who else "across the account"
        if not items:
            return f"{LABEL} No {action} {scope}."
        lines = [f"{LABEL} {len(items)} {action} {scope}\n"]
        for x in items:
            if action == "payments":
                lines.append(f"- {money(x.get('amount'), x.get('currency'))} · {x.get('status')} · {_date(x.get('created'))}"
                             f" ({x.get('id')}){' · ' + x['description'] if x.get('description') else ''}")
            elif action == "invoices":
                lines.append(f"- {x.get('number') or x.get('id')} · {money(x.get('total'), x.get('currency'))} · {x.get('status')}"
                             f" · due {_date(x.get('due_date')) or '—'}"
                             f" · paid {money(x.get('amount_paid'), x.get('currency'))}"
                             + (f"\n  {x['hosted_invoice_url']}" if x.get("hosted_invoice_url") else ""))
            else:
                items_ = (x.get("items") or {}).get("data", [])
                plans = ", ".join(f"{money((i.get('price') or {}).get('unit_amount'), (i.get('price') or {}).get('currency'))}"
                                  f"/{((i.get('price') or {}).get('recurring') or {}).get('interval', '?')}" for i in items_)
                lines.append(f"- {x.get('id')} · {x.get('status')} · {plans or 'no items'}"
                             f" · customer {x.get('customer')}"
                             + (" · cancels at period end" if x.get("cancel_at_period_end") else ""))
        return "\n".join(lines)
