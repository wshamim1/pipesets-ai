"""Crawl4AI — async web crawler for LLM ingestion — built-in tool `crawl4ai`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec

TOOL = ToolSpec(
    id="crawl4ai",
    name="Crawl4AI",
    icon="🕷️",
    group="frameworks",
    description="Async web crawler built for LLM ingestion. Returns clean Markdown, structured JSON, or screenshots from any URL. Handles JavaScript-rendered pages, PDFs, sitemaps, and deep crawls.",
    default_config={
        "url": "",
        "output_format": "markdown",
        "max_pages": 1,
        "max_chars": 80000,
        "css_selector": "",
        "screenshot": False,
    },
    order=20,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    url = (cfg.get("url") or "").strip() or inp.strip()
    output_format = cfg.get("output_format", "markdown").lower()
    max_pages = int(cfg.get("max_pages", 1))
    max_chars = int(cfg.get("max_chars", 80000))
    css_selector = (cfg.get("css_selector") or "").strip() or None
    screenshot = bool(cfg.get("screenshot", False))

    if not url:
        return "[Crawl4AI] No URL provided. Set 'url' in config or pass it as input."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        import asyncio as _asyncio
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

        browser_cfg = BrowserConfig(headless=True, verbose=False)
        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            css_selector=css_selector,
            screenshot=screenshot,
            word_count_threshold=10,
        )

        pages_content: list[str] = []

        async def _crawl():
            async with AsyncWebCrawler(config=browser_cfg) as crawler:
                if max_pages == 1:
                    result = await crawler.arun(url=url, config=run_cfg)
                    if result.success:
                        pages_content.append(result.markdown if output_format == "markdown" else result.extracted_content or result.markdown)
                    else:
                        pages_content.append(f"[Error] {result.error_message}")
                else:
                    results = await crawler.arun_many(
                        urls=[url],
                        config=run_cfg,
                    )
                    for r in results:
                        if r.success:
                            pages_content.append(r.markdown if output_format == "markdown" else r.extracted_content or r.markdown)

        _asyncio.get_event_loop().run_until_complete(_crawl())

        combined = "\n\n---\n\n".join(pages_content)
        total = len(combined)

        # Size guard
        truncated = ""
        if max_chars > 0 and total > max_chars:
            head = int(max_chars * 0.75)
            tail = max_chars - head
            combined = (
                combined[:head]
                + f"\n\n... [{total - max_chars:,} chars omitted] ...\n\n"
                + combined[-tail:]
            )
            truncated = f" (truncated from {total:,} chars)"

        return f"[Crawl4AI — {output_format.upper()}]\nURL: {url}{truncated}\n\n{combined}"

    except ImportError:
        return (
            "[Crawl4AI] Package not found. Install it with:\n"
            "  pip install crawl4ai\n"
            "  python -m crawl4ai.install\n\n"
            "Then restart the backend server."
        )
    except Exception as e:
        return f"[Crawl4AI] Error: {e}"
