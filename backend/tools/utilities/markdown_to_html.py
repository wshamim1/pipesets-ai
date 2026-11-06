"""Markdown → HTML — built-in tool `markdown_to_html`."""

import html
import re
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="markdown_to_html",
    name="Markdown → HTML",
    icon="📝",
    category="Data & Files",
    description="Converts Markdown text into a simple HTML fragment for display or embedding.",
    default_config={"wrap_in_html": False},
    order=80,
    parameters=params(
        {"markdown": {"type": "string", "description": "Markdown content to convert to HTML"}},
        {
            "wrap_in_html": {
                "type": "boolean",
                "description": "Wrap the output in a full HTML document with <html><body> tags",
            }
        },
    ),
    input_param="markdown",
    config_args=("wrap_in_html",),
)


def _convert_inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    markdown = (inp or "").strip()
    if not markdown:
        return "[Markdown → HTML] Please provide markdown text to convert."

    lines = markdown.splitlines()
    html_chunks: list[str] = []
    in_code = False
    code_lines: list[str] = []
    in_list = False
    list_items: list[str] = []
    in_quote = False
    quote_lines: list[str] = []

    def flush_list() -> None:
        nonlocal in_list, list_items
        if in_list and list_items:
            html_chunks.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
            list_items = []
            in_list = False

    def flush_quote() -> None:
        nonlocal in_quote, quote_lines
        if in_quote and quote_lines:
            html_chunks.append("<blockquote>" + "".join(f"<p>{_convert_inline(line)}</p>" for line in quote_lines) + "</blockquote>")
            quote_lines = []
            in_quote = False

    for line in lines:
        if line.startswith("```"):
            if in_code:
                html_chunks.append("<pre><code>" + html.escape("\n".join(code_lines), quote=False) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                flush_list()
                flush_quote()
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            flush_list()
            flush_quote()
            continue

        if stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("+ "):
            flush_quote()
            in_list = True
            list_items.append(_convert_inline(stripped[2:].strip()))
            continue

        if stripped.startswith("> "):
            flush_list()
            in_quote = True
            quote_lines.append(stripped[2:].strip())
            continue

        flush_list()
        flush_quote()

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            html_chunks.append(f"<h{level}>{_convert_inline(heading_match.group(2))}</h{level}>")
            continue

        html_chunks.append(f"<p>{_convert_inline(stripped)}</p>")

    flush_list()
    flush_quote()

    result = "\n".join(html_chunks)
    wrap_in_html = bool(cfg.get("wrap_in_html", False))
    if wrap_in_html:
        return "<html><body>" + result + "</body></html>"
    return result
