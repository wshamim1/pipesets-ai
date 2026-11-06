"""Shared result formatting for the web search tools."""


def format_search(provider: str, query: str, items: list, answer: str = "") -> str:
    """items: (title, url, snippet) tuples."""
    if not items and not answer:
        return f"[{provider}] No results found for: {query}"
    lines = [f"[{provider} Web Search: '{query}']\n"]
    if answer:
        lines.append(f"Answer: {answer}\n")
    for i, (title, url, snippet) in enumerate(items, 1):
        lines.append(f"{i}. {title}\n   {url}\n   {(snippet or '')[:200]}")
    return "\n".join(lines)
