"""Shared helpers for the Atlassian Cloud tools (Jira, Confluence)."""

from typing import Any, Dict, Optional, Tuple

import httpx


def atlassian_client(cfg: Dict[str, Any], label: str) -> Tuple[Optional[httpx.AsyncClient], str, str]:
    """→ (client, base_url, error). Auth is the account email + an API token (id.atlassian.com)."""
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    email, token = (cfg.get("email") or "").strip(), (cfg.get("api_token") or "").strip()
    if not (base and email and token):
        return None, "", f"[{label}] base_url (https://your-site.atlassian.net), email and api_token are required in config."
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    client = httpx.AsyncClient(timeout=20.0, auth=(email, token), headers={"Accept": "application/json"})
    return client, base, ""


def http_error(label: str, resp: httpx.Response) -> str:
    if resp.status_code == 401:
        return f"[{label}] Authentication failed — check the email and API token."
    if resp.status_code == 403:
        return f"[{label}] The account doesn't have permission for this."
    if resp.status_code == 404:
        return f"[{label}] Not found (or not visible to this account)."
    try:
        body = resp.json()
        detail = "; ".join(body.get("errorMessages", [])) or "; ".join(f"{k}: {v}" for k, v in (body.get("errors") or {}).items()) \
            or body.get("message", "")
    except ValueError:
        detail = resp.text[:300]
    return f"[{label}] HTTP {resp.status_code}: {detail}"


def adf_to_text(node: Any) -> str:
    """Atlassian Document Format (Jira rich text) → plain text."""
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    inner = "".join(adf_to_text(c) for c in node.get("content", []))
    if kind in ("paragraph", "heading", "blockquote", "codeBlock"):
        return inner + "\n"
    if kind == "listItem":
        return f"- {inner.strip()}\n"
    if kind == "mention":
        return node.get("attrs", {}).get("text", "")
    return inner


def text_to_adf(text: str) -> Dict[str, Any]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()] or [""]
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": p}] if p else []} for p in paragraphs]}
