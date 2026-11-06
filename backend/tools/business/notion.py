"""Notion — built-in tool `notion`."""

import re
from typing import Any, Dict, List, Optional

import httpx

from tools.base import MAX_RESULTS, Select, ToolSpec, params

TOOL = ToolSpec(
    id="notion",
    name="Notion",
    icon="📓",
    category="Business Apps",
    description="Searches Notion pages shared with your integration, reads a page's content, or creates a page under a parent. Input: search text, a page URL/ID, or 'create: Title' + body.",
    default_config={"api_token": "", "action": "auto", "parent_page_id": "", "max_results": 5, "max_chars": 8000},
    order=30,
    required=("api_token",),
    selects={
        "action": Select("Action", (("auto", "Auto (URL/ID → read, 'create:' → create, else search)"),
                                    ("search", "Search"), ("read", "Read page"), ("create", "Create page"))),
    },
    parameters=params(
        {
            "request": {"type": "string", "description": "Search text, a page URL / ID to read, or 'create: Title' + the body on the next lines"},
        },
        {"max_results": MAX_RESULTS},
    ),
    input_param="request",
)

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
# Page IDs: 32 hex chars, with or without UUID dashes (URLs end in "Page-Title-<id>")
_ID = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}(?![0-9a-f])", re.I)


def _page_id(text: str) -> Optional[str]:
    found = _ID.findall(text)
    return found[-1].replace("-", "") if found else None


def _title(page: Dict[str, Any]) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", [])) or "Untitled"
    return "Untitled"


def _rich(block: Dict[str, Any], kind: str) -> str:
    return "".join(t.get("plain_text", "") for t in (block.get(kind) or {}).get("rich_text", []))


def _block_text(block: Dict[str, Any]) -> str:
    kind = block.get("type", "")
    text = _rich(block, kind)
    prefix = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ", "bulleted_list_item": "- ",
              "numbered_list_item": "1. ", "quote": "> ", "callout": "> "}.get(kind, "")
    if kind == "to_do":
        prefix = "[x] " if (block.get("to_do") or {}).get("checked") else "[ ] "
    if kind == "code":
        return f"```\n{text}\n```"
    if kind == "child_page":
        return f"📄 {(block.get('child_page') or {}).get('title', '')}"
    if kind == "divider":
        return "---"
    return f"{prefix}{text}" if text or prefix else ""


def _error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    code, msg = body.get("code", ""), body.get("message", resp.text[:200])
    if resp.status_code == 401:
        return "[Notion] The integration token is invalid."
    if code == "object_not_found":
        return "[Notion] Page not found — share it with your integration (page ⋯ → Connections)."
    return f"[Notion] HTTP {resp.status_code}: {msg}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("api_token") or "").strip()
    if not token:
        return "[Notion] api_token (an internal integration secret) is required in config."
    text = inp.strip()
    action = cfg.get("action", "auto")
    if action == "auto":
        if text.lower().startswith("create:"):
            action, text = "create", text[len("create:"):].strip()
        elif " " not in text and _page_id(text):
            action = "read"
        else:
            action = "search"
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": VERSION}

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        if action == "read":
            page_id = _page_id(text)
            if not page_id:
                return "[Notion] Provide a page URL or ID to read."
            page = await client.get(f"{API}/pages/{page_id}")
            if page.status_code != 200:
                return _error(page)
            blocks: List[Dict[str, Any]] = []
            cursor = None
            while len(blocks) < 300:
                params: Dict[str, Any] = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                resp = await client.get(f"{API}/blocks/{page_id}/children", params=params)
                if resp.status_code != 200:
                    return _error(resp)
                d = resp.json()
                blocks += d.get("results", [])
                if not d.get("has_more"):
                    break
                cursor = d.get("next_cursor")
            body = "\n".join(t for t in (_block_text(b) for b in blocks) if t)
            max_chars = int(cfg.get("max_chars", 8000))
            p = page.json()
            return (f"[Notion: {_title(p)}]\n{p.get('url', '')}\n\n"
                    + (body[:max_chars] + ("\n\n…(truncated)" if len(body) > max_chars else "") if body else "(empty page)"))

        if action == "create":
            parent = _page_id(cfg.get("parent_page_id") or "")
            if not parent:
                return "[Notion] Set parent_page_id in config (a page shared with the integration) to create pages."
            title, _, body = text.partition("\n")
            children = [{"object": "block", "type": "paragraph",
                         "paragraph": {"rich_text": [{"type": "text", "text": {"content": para[:2000]}}]}}
                        for para in (p.strip() for p in body.split("\n\n")) if para][:100]
            resp = await client.post(f"{API}/pages", json={
                "parent": {"page_id": parent},
                "properties": {"title": {"title": [{"type": "text", "text": {"content": title.strip()[:2000] or "Untitled"}}]}},
                "children": children,
            })
            if resp.status_code != 200:
                return _error(resp)
            return f"[Notion] Created page '{title.strip()}'\n{resp.json().get('url', '')}"

        resp = await client.post(f"{API}/search", json={
            "query": text, "page_size": int(cfg.get("max_results", 5)),
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        })
        if resp.status_code != 200:
            return _error(resp)
        pages = resp.json().get("results", [])
        if not pages:
            return f"[Notion] No pages match '{text}' (only pages shared with the integration are searchable)."
        lines = [f"[Notion: '{text}']\n"]
        for i, p in enumerate(pages, 1):
            lines.append(f"{i}. {_title(p)} — edited {(p.get('last_edited_time') or '')[:10]}\n   {p.get('url', '')}")
        return "\n".join(lines)
