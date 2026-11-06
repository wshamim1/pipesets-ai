"""Trello — built-in tool `trello` (Trello REST API v1 with an API key + token).

Actions: ``search`` (cards matching text, optionally on one board), ``list`` (the open cards in a
list) and ``create`` (a card in a list: the first line is its name, the rest its description).
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Trello]"
API = "https://api.trello.com/1"

TOOL = ToolSpec(
    id="trello",
    name="Trello",
    icon="📋",
    category="Productivity",
    description="Searches Trello cards, lists the cards in a list, or creates a card. Input: search text (search), or the card name with its description on the next lines (create).",
    default_config={"api_key": "", "token": "", "action": "search", "board_id": "", "list_id": "", "max_results": 10},
    order=70,
    required=("api_key", "token"),
    selects={"action": Select("Action", (("search", "Search cards"), ("list", "Cards in a list"), ("create", "Create a card")))},
    parameters=params(
        {"request": {"type": "string", "description": "Search text (search), or the card name + description on the next lines (create)"}},
        {
            "action": enum(["search", "list", "create"], "search = find cards, list = cards in the list, create = add a card"),
            "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Cards to return"},
        },
    ),
    input_param="request",
)


def _error(resp: httpx.Response) -> str:
    text = resp.text[:200].strip()
    if resp.status_code == 401:
        return f"{LABEL} The api_key or token is invalid ({text})."
    if resp.status_code == 404:
        return f"{LABEL} Not found — check the board / list id."
    return f"{LABEL} HTTP {resp.status_code}: {text}"


def _card(c: Dict[str, Any]) -> str:
    due = f" · due {c['due'][:10]}" if c.get("due") else ""
    desc = (c.get("desc") or "").strip().replace("\n", " ")
    return f"- {c.get('name', '')}{due}{' (archived)' if c.get('closed') else ''}\n  {c.get('shortUrl') or c.get('url', '')}" + \
           (f"\n  {desc[:200]}" if desc else "")


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    for key in ("api_key", "token"):
        if not str(cfg.get(key) or "").strip():
            return f"{LABEL} {key} is required in config (from trello.com/power-ups/admin)."
    action = (cfg.get("action") or "search").strip().lower()
    if action not in ("search", "list", "create"):
        return f'{LABEL} Action is "search", "list" or "create" — got "{action}".'
    auth = {"key": cfg["api_key"].strip(), "token": cfg["token"].strip()}
    limit = max(1, min(int(cfg.get("max_results") or 10), 50))
    list_id = str(cfg.get("list_id") or "").strip()
    text = inp.strip()

    async with httpx.AsyncClient(timeout=20.0) as client:
        if action == "create":
            if not list_id:
                return f"{LABEL} Set list_id to create a card."
            name, _, desc = text.partition("\n")
            if not name.strip():
                return f"{LABEL} Provide the card name."
            resp = await client.post(f"{API}/cards", params={**auth, "idList": list_id, "name": name.strip()[:16384],
                                                             "desc": desc.strip()[:16384]})
            if resp.status_code != 200:
                return _error(resp)
            card = resp.json()
            return f"{LABEL} Created card '{card.get('name')}'\n{card.get('shortUrl') or card.get('url', '')}"

        if action == "list":
            if not list_id:
                return f"{LABEL} Set list_id to read a list."
            resp = await client.get(f"{API}/lists/{list_id}/cards", params={**auth, "fields": "name,desc,due,closed,shortUrl"})
            if resp.status_code != 200:
                return _error(resp)
            cards = resp.json()[:limit]
            if not cards:
                return f"{LABEL} The list is empty."
            return f"{LABEL} {len(cards)} card(s)\n\n" + "\n".join(_card(c) for c in cards)

        if not text:
            return f"{LABEL} Provide text to search for."
        q = {**auth, "query": text, "modelTypes": "cards", "cards_limit": limit, "partial": "true",
             "card_fields": "name,desc,due,closed,shortUrl"}
        if cfg.get("board_id"):
            q["idBoards"] = str(cfg["board_id"]).strip()
        resp = await client.get(f"{API}/search", params=q)
        if resp.status_code != 200:
            return _error(resp)
        cards = resp.json().get("cards", [])
        if not cards:
            return f"{LABEL} No cards match '{text}'."
        return f"{LABEL} {len(cards)} card(s) matching '{text}'\n\n" + "\n".join(_card(c) for c in cards)
