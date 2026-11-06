"""HTML → Markdown — built-in tool `html_to_markdown`."""

import re
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="html_to_markdown",
    name="HTML → Markdown",
    icon="📝",
    category="Data & Files",
    description="Converts a web page or raw HTML into clean Markdown (headings, lists, links, tables), dropping scripts and navigation.",
    default_config={"include_links": True, "main_content_only": True, "max_chars": 15000},
    order=130,
    parameters=params(
        {"source": {"type": "string", "description": "A page URL or raw HTML"}},
        {
            "main_content_only": {"type": "boolean", "description": "Drop navigation, footers and sidebars"},
            "include_links": {"type": "boolean", "description": "Keep links"},
            "max_chars": {"type": "integer", "minimum": 200, "maximum": 50000, "description": "Longest text to return"},
        },
    ),
    input_param="source",
)

_NOISE = ["script", "style", "noscript", "svg", "iframe", "form", "button"]
_CHROME = ["nav", "header", "footer", "aside"]


def _convert(node, base: str, links: bool) -> str:
    from bs4 import Comment, NavigableString, Tag

    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return re.sub(r"\s+", " ", str(node))
    if not isinstance(node, Tag):
        return ""
    inner = lambda: "".join(_convert(c, base, links) for c in node.children)  # noqa: E731
    name = node.name
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return f"\n\n{'#' * int(name[1])} {inner().strip()}\n\n"
    if name in ("p", "div", "section", "article", "main"):
        return f"\n\n{inner().strip()}\n\n"
    if name == "br":
        return "\n"
    if name in ("strong", "b"):
        text = inner().strip()
        return f"**{text}**" if text else ""
    if name in ("em", "i"):
        text = inner().strip()
        return f"*{text}*" if text else ""
    if name == "code" and node.parent is not None and node.parent.name != "pre":
        return f"`{node.get_text()}`"
    if name == "pre":
        return f"\n\n```\n{node.get_text().strip()}\n```\n\n"
    if name == "a":
        text = inner().strip()
        href = node.get("href") or ""
        if links and href and not href.startswith(("#", "javascript:")) and text:
            return f"[{text}]({urljoin(base, href)})"
        return text
    if name == "img":
        alt = (node.get("alt") or "").strip()
        return f"![{alt}]({urljoin(base, node.get('src') or '')})" if links and alt else alt
    if name in ("ul", "ol"):
        items = [li for li in node.find_all("li", recursive=False)]
        lines = [f"{f'{i}.' if name == 'ol' else '-'} {_convert(li, base, links).strip()}" for i, li in enumerate(items, 1)]
        return "\n\n" + "\n".join(lines) + "\n\n"
    if name == "li":
        return inner()
    if name == "blockquote":
        return "\n\n" + "\n".join(f"> {l}" for l in inner().strip().splitlines()) + "\n\n"
    if name == "table":
        rows = [[re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
                for tr in node.find_all("tr")]
        rows = [r for r in rows if r]
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
        out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n\n" + "\n".join(out) + "\n\n"
    if name == "hr":
        return "\n\n---\n\n"
    return inner()


def html_to_markdown(html: str, base: str = "", include_links: bool = True, main_content_only: bool = True):
    """→ (title, markdown). Also used by the HTML / Web URL / Sitemap document loaders."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    root = soup.body or soup
    if main_content_only:
        root = soup.find("main") or soup.find("article") or root
        for tag in root.find_all(_CHROME):
            tag.decompose()
    md = _convert(root, base, include_links)
    md = re.sub(r"[ \t]+\n", "\n", md)
    return title, re.sub(r"\n{3,}", "\n\n", md).strip()


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[HTML → Markdown] Provide a URL or HTML."
    base = ""
    try:
        if inp.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                         headers={"User-Agent": "Mozilla/5.0 (compatible; PipesetsAI/1.0)"}) as client:
                resp = await client.get(inp)
                resp.raise_for_status()
            html, base = resp.text, str(resp.url)
        else:
            html = inp
        title, md = html_to_markdown(html, base, str(cfg.get("include_links", True)).lower() != "false",
                                     str(cfg.get("main_content_only", True)).lower() != "false")
        max_chars = int(cfg.get("max_chars", 15000))
        if len(md) > max_chars:
            md = md[:max_chars] + "\n\n…(truncated)"
        header = f"# {title}\n\n" if title and not md.startswith("# ") else ""
        return header + md if md else "[HTML → Markdown] No readable content found."
    except Exception as e:
        return f"[HTML → Markdown] Error: {e}"
