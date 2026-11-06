"""Confluence Cloud — built-in tool `confluence`."""

import re
from typing import Any, Dict, Optional

from tools.base import MAX_RESULTS, Select, ToolSpec, params
from tools.business._atlassian import atlassian_client, http_error

TOOL = ToolSpec(
    id="confluence",
    name="Confluence",
    icon="🗒️",
    category="Business Apps",
    description="Searches Confluence pages (optionally within one space) or reads a page's content. Input: search text, or a page ID / page URL to read.",
    default_config={"base_url": "", "email": "", "api_token": "", "action": "auto", "space_key": "",
                    "max_results": 5, "max_chars": 8000},
    order=20,
    required=("base_url", "email", "api_token"),
    selects={
        "action": Select("Action", (("auto", "Auto (page ID/URL → read, else search)"), ("search", "Search"), ("get", "Read page"))),
    },
    parameters=params(
        {"query": {"type": "string", "description": "Search text, or a page ID / URL to read"}},
        {"max_results": MAX_RESULTS},
    ),
    input_param="query",
)


def _clean_excerpt(text: str) -> str:
    text = re.sub(r"@@@(end)?hl@@@", "", text or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    client, base, err = atlassian_client(cfg, "Confluence")
    if err:
        return err
    text = inp.strip()
    if not text:
        return "[Confluence] Provide search text or a page ID / URL."
    page_id = text if text.isdigit() else (re.search(r"/pages/(\d+)", text) or [None, None])[1]
    action = cfg.get("action", "auto")
    if action == "auto":
        action = "get" if page_id else "search"

    async with client:
        if action == "get":
            if not page_id:
                return "[Confluence] Provide a numeric page ID or a page URL to read."
            resp = await client.get(f"{base}/wiki/rest/api/content/{page_id}", params={"expand": "body.storage,version,space"})
            if resp.status_code != 200:
                return http_error("Confluence", resp)
            from bs4 import BeautifulSoup
            d = resp.json()
            body = BeautifulSoup(((d.get("body") or {}).get("storage") or {}).get("value", ""), "html.parser").get_text("\n")
            body = re.sub(r"\n{3,}", "\n\n", body).strip()
            max_chars = int(cfg.get("max_chars", 8000))
            links = d.get("_links", {})
            return (f"[Confluence: {d.get('title', '')}] space {(d.get('space') or {}).get('name', '?')} · "
                    f"version {(d.get('version') or {}).get('number', '?')}\n{links.get('base', base + '/wiki')}{links.get('webui', '')}\n\n"
                    + (body[:max_chars] + ("\n\n…(truncated)" if len(body) > max_chars else "") or "(empty page)"))

        cql = 'type = page AND text ~ "' + text.replace('"', '\\"') + '"'
        if cfg.get("space_key"):
            cql += f' AND space = "{cfg["space_key"]}"'
        resp = await client.get(f"{base}/wiki/rest/api/search", params={"cql": cql, "limit": int(cfg.get("max_results", 5))})
        if resp.status_code != 200:
            return http_error("Confluence", resp)
        d = resp.json()
        results = d.get("results", [])
        if not results:
            return f"[Confluence] No pages match: {text}"
        site = (d.get("_links") or {}).get("base", base + "/wiki")
        lines = [f"[Confluence: '{text}']\n"]
        for i, r in enumerate(results, 1):
            content = r.get("content") or {}
            space = (r.get("resultGlobalContainer") or {}).get("title", "")
            lines.append(f"{i}. {content.get('title') or r.get('title', '')}" + (f" — {space}" if space else "")
                         + f" (id {content.get('id', '?')}, {r.get('friendlyLastModified', '')})"
                         + f"\n   {_clean_excerpt(r.get('excerpt', ''))[:250]}\n   {site}{r.get('url', '')}")
        return "\n".join(lines)
