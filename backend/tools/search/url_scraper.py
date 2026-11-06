"""URL Scraper — built-in tool `url_scraper`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="url_scraper",
    name="URL Scraper",
    icon="🕷️",
    category="Web Search",
    description="Fetches and extracts readable text from any public URL. Input is the URL.",
    default_config={"max_chars": 4000, "timeout": 15},
    order=80,
    parameters=params({"url": {"type": "string", "description": "The page to read (http/https)"}},
                      {"max_chars": {"type": "integer", "minimum": 200, "maximum": 20000, "description": "Longest text to return"}}),
    input_param="url",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    max_chars = int(cfg.get("max_chars", 4000))
    timeout = int(cfg.get("timeout", 15))
    url = inp.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AgenticBot/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.text
        # Strip HTML tags for readable text
        import re as _re
        # Remove scripts, styles, and tags
        raw = _re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", raw, flags=_re.DOTALL | _re.IGNORECASE)
        raw = _re.sub(r"<[^>]+>", " ", raw)
        raw = _re.sub(r"[ \t]+", " ", raw)
        raw = _re.sub(r"\n{3,}", "\n\n", raw).strip()
        truncated = raw[:max_chars]
        suffix = f"\n\n...(truncated to {max_chars} chars)" if len(raw) > max_chars else ""
        return f"[URL Scraper: {url}]\n\n{truncated}{suffix}"
    except Exception as e:
        return f"[URL Scraper] Error fetching {url}: {e}"
