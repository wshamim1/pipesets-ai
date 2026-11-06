"""URL fetcher — built-in tool `url_fetcher`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="url_fetcher",
    name="URL Fetcher",
    icon="🌐",
    category="APIs & Integrations",
    description="Fetches a URL and returns a concise text preview of the response body.",
    default_config={"timeout": 15, "max_chars": 4000},
    order=30,
    parameters=params(
        {"url": {"type": "string", "description": "URL to fetch"}},
        {
            "max_chars": {
                "type": "integer",
                "minimum": 200,
                "maximum": 20000,
                "description": "Maximum number of characters to include in the result",
            },
            "timeout": {
                "type": "number",
                "minimum": 1,
                "maximum": 60,
                "description": "HTTP timeout in seconds",
            },
        },
    ),
    input_param="url",
    config_args=("max_chars", "timeout"),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    raw_url = (inp or "").strip()
    if not raw_url:
        return "[URL Fetcher] Please provide a URL."

    url = raw_url if raw_url.startswith(("http://", "https://")) else f"https://{raw_url}"

    timeout = float(cfg.get("timeout") or 15)
    max_chars = int(cfg.get("max_chars") or 4000)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text
    except Exception as exc:
        return f"[URL Fetcher] Error fetching {url}: {exc}"

    if not text:
        return f"[URL Fetcher] {url} returned no content."

    clipped = text.strip().replace("\r", "")
    if len(clipped) > max_chars:
        clipped = clipped[:max_chars].rstrip() + "\n…"
    return f"URL: {url}\n\n{clipped}"
