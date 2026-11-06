"""
chat_links.py — a public URL that opens a chat with one published pipeline.

A link looks like ``https://<public host>/c/pc_<32 url-safe chars>``. The token is the credential:
anyone who has the URL can chat (``access = 'public'``; passcode and sign-in links are planned,
plan.md C9). It can do nothing but run that one pipeline's latest published version, through
``/v1/chat/{token}/…`` (routers/v1_chat.py), as the user who created the link, so that user's ACLs,
budgets and middleware apply, and the link stops working when they lose access to the project.

Storage: ``token_hash`` (SHA-256) to find a link from its URL, and ``token_sealed`` (encrypted under
the master key) so the builder can copy the link again later; the plaintext is never stored.

Sessions
--------
Visitors don't pick their session: ``new_session`` hands out an opaque, encrypted ``{link, id}``
token and ``open_session`` checks it belongs to this link, so one visitor can't read or continue
another's conversation. The conversation itself lives in the pipeline's memory (``memory_session``).

Limits (per link, all shared across replicas through services/shared_state.py)
-------------------------------------------------------------------------------
  rate_limit_per_min   messages per minute from one IP address (0 = unlimited)
  max_turns            messages in one session, over 24 h (0 = unlimited)
  max_message_chars    longest message accepted
  daily_message_cap    messages to the link from everyone, over 24 h (0 = unlimited)

What the page shows
-------------------
``starter_prompts`` (up to MAX_STARTERS) are offered as taps on an empty chat. With ``show_details``
on, the page also shows ``about(...)``: the pipeline's id, published version, description and the
*names* of its models, tools, MCP servers, agents and sub-pipelines, read from the published flow. Never system prompts,
connection details, document collections or keys.
"""

import hashlib
import json
import secrets
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from db import get_db_connection
from services import secret_store, shared_state

TOKEN_PREFIX = "pc_"
DAY = 24 * 3600

# Limits a new link gets unless the builder sets others
MAX_STARTERS = 6

DEFAULT_LIMITS = {"rate_limit_per_min": 10, "max_turns": 50, "max_message_chars": 4000, "daily_message_cap": 500}

# A pipeline without a Memory node still remembers the conversation when it is reached through a link
DEFAULT_MEMORY = {"strategy": "sliding_window", "token_budget": 4096}


class LimitExceeded(Exception):
    def __init__(self, status: int, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.utcnow().isoformat()


def _public(row, with_token: bool = True) -> Dict[str, Any]:
    """The builder's view of a link: never the hash; the token itself when asked for."""
    d = {k: row[k] for k in ("id", "app_id", "created_by", "name", "title", "greeting", "access", "token_prefix",
                             "rate_limit_per_min", "max_turns", "max_message_chars", "daily_message_cap",
                             "message_count", "last_used_at", "created_at", "updated_at", "revoked_at")}
    d["active"] = row["revoked_at"] is None
    d["show_details"] = bool(row["show_details"])
    d["starter_prompts"] = parse_prompts(row["starter_prompts"])
    if with_token and d["active"]:
        d["token"] = secret_store.open_sealed(row["token_sealed"])
    return d


def parse_prompts(raw: Any) -> List[str]:
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    return [str(p).strip() for p in (items or []) if str(p).strip()][:MAX_STARTERS]


# ── Management ────────────────────────────────────────────────────────────────

def create(tenant_id: str, project_id: str, user_id: str, app_id: str, name: str,
           title: str = "", greeting: str = "", show_details: bool = True,
           starter_prompts: Optional[List[str]] = None, **limits: int) -> Dict[str, Any]:
    token = new_token()
    link_id = f"chat_{uuid.uuid4().hex[:12]}"
    now = _now()
    values = {**DEFAULT_LIMITS, **{k: v for k, v in limits.items() if k in DEFAULT_LIMITS and v is not None}}
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO chat_links (id, tenant_id, project_id, app_id, created_by, name, title, greeting, access, "
            "token_hash, token_prefix, token_sealed, rate_limit_per_min, max_turns, max_message_chars, "
            "daily_message_cap, message_count, show_details, starter_prompts, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'public', ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
            (link_id, tenant_id, project_id, app_id, user_id, name, title, greeting,
             hash_token(token), token[:12], secret_store.seal(token),
             values["rate_limit_per_min"], values["max_turns"], values["max_message_chars"],
             values["daily_message_cap"], int(show_details), json.dumps(parse_prompts(starter_prompts or [])),
             now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return get(link_id, tenant_id, project_id)


def get(link_id: str, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM chat_links WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (link_id, tenant_id, project_id)).fetchone()
    finally:
        conn.close()
    return _public(row) if row else None


def list_links(tenant_id: str, project_id: str, app_id: str = "") -> List[Dict[str, Any]]:
    sql, params = "SELECT * FROM chat_links WHERE tenant_id = ? AND project_id = ?", [tenant_id, project_id]
    if app_id:
        sql += " AND app_id = ?"
        params.append(app_id)
    conn = get_db_connection()
    try:
        rows = conn.execute(sql + " ORDER BY created_at DESC", tuple(params)).fetchall()
    finally:
        conn.close()
    return [_public(r) for r in rows]


def update(link_id: str, tenant_id: str, project_id: str, user_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """Change name / title / greeting / details / starter prompts / limits. Whoever saves it becomes the
    user its runs act as."""
    editable = ("name", "title", "greeting", "show_details", "starter_prompts", *DEFAULT_LIMITS)
    allowed = {k: v for k, v in fields.items() if v is not None and k in editable}
    if "show_details" in allowed:
        allowed["show_details"] = int(bool(allowed["show_details"]))
    if "starter_prompts" in allowed:
        allowed["starter_prompts"] = json.dumps(parse_prompts(allowed["starter_prompts"]))
    sets = ", ".join(f"{k} = ?" for k in allowed)
    conn = get_db_connection()
    try:
        cur = conn.execute(
            f"UPDATE chat_links SET {sets + ', ' if sets else ''}created_by = ?, updated_at = ? "
            "WHERE id = ? AND tenant_id = ? AND project_id = ? AND revoked_at IS NULL",
            (*allowed.values(), user_id, _now(), link_id, tenant_id, project_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get(link_id, tenant_id, project_id) if cur.rowcount else None


def rotate(link_id: str, tenant_id: str, project_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """A new URL for the same link (e.g. the old one leaked): the old URL stops working at once; settings,
    message count and visitors' conversations stay, since sessions belong to the link, not its token."""
    token = new_token()
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "UPDATE chat_links SET token_hash = ?, token_prefix = ?, token_sealed = ?, created_by = ?, updated_at = ? "
            "WHERE id = ? AND tenant_id = ? AND project_id = ? AND revoked_at IS NULL",
            (hash_token(token), token[:12], secret_store.seal(token), user_id, _now(), link_id, tenant_id, project_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get(link_id, tenant_id, project_id) if cur.rowcount else None


def revoke(link_id: str, tenant_id: str, project_id: str) -> bool:
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "UPDATE chat_links SET revoked_at = ?, updated_at = ? "
            "WHERE id = ? AND tenant_id = ? AND project_id = ? AND revoked_at IS NULL",
            (_now(), _now(), link_id, tenant_id, project_id),
        )
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0


# ── Public side ───────────────────────────────────────────────────────────────

_PROVIDER_NAMES = {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Google Gemini", "groq": "Groq",
                   "mistral": "Mistral", "bedrock": "AWS Bedrock", "azure": "Azure OpenAI", "ollama": "Ollama",
                   "watsonx": "IBM watsonx", "deepseek": "DeepSeek", "xai": "xAI", "mock": "Simulated"}


def about(app: Dict[str, Any], description: str = "") -> Dict[str, Any]:
    """What a visitor may learn about the pipeline: names only, read from its published flow."""
    models: List[str] = []
    tools: List[str] = []
    mcp: List[str] = []
    agents: List[str] = []
    pipelines: List[str] = []
    documents = False

    def add(items: List[str], value: Any) -> None:
        value = str(value or "").strip()
        if value and value not in items:
            items.append(value)

    for n in app["flow"].get("nodes", []):
        t, d = n.get("type"), n.get("data", {}) or {}
        if t in ("llm", "master_agent") or (t == "child_agent" and (d.get("kind") or "llm") == "llm"):
            if d.get("model"):
                provider = _PROVIDER_NAMES.get(d.get("provider", ""), d.get("provider", ""))
                add(models, f"{d['model']} ({provider})" if provider else d["model"])
        if t == "master_agent":
            add(agents, d.get("label") or "Master agent")
        elif t == "child_agent" and d.get("kind") == "pipeline":
            add(pipelines, d.get("app_name") or d.get("label"))
        elif t == "child_agent":
            add(agents, d.get("role") or d.get("label"))
        elif t == "tool":
            add(mcp if d.get("toolType") == "mcp" else tools, d.get("label") or d.get("toolId"))
        elif t == "toolkit":
            for st in d.get("subTools") or []:
                if isinstance(st, dict):
                    add(tools, st.get("label") or st.get("name") or st.get("id"))
        elif t == "skill":
            add(tools, d.get("label"))
        elif t in ("retriever", "knowledge_base", "vector_store"):
            documents = True
    return {"pipeline_id": app["id"], "version": app.get("version") or 0, "description": description.strip(),
            "models": models, "tools": tools, "mcp_servers": mcp, "agents": agents, "pipelines": pipelines,
            "answers_from_documents": documents}


def find_by_token(token: str) -> Optional[Dict[str, Any]]:
    """The active link for a URL token, as a raw row dict; None when unknown or revoked."""
    if not token.startswith(TOKEN_PREFIX):
        return None
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM chat_links WHERE token_hash = ? AND revoked_at IS NULL",
                           (hash_token(token),)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def new_session(link: Dict[str, Any]) -> str:
    return secret_store.encrypt(json.dumps({"l": link["id"], "s": uuid.uuid4().hex}))


def open_session(link: Dict[str, Any], session: str) -> Optional[str]:
    """The session id inside ``session`` when it was issued for this link, else None."""
    try:
        data = json.loads(secret_store.decrypt(session))
    except Exception:   # not ours, tampered with, or from another link's master key
        return None
    return data.get("s") if data.get("l") == link["id"] and data.get("s") else None


def memory_session(link: Dict[str, Any], sid: str) -> str:
    return f"chat:{link['id']}:{sid}"


def check_message(link: Dict[str, Any], sid: str, ip: str, message: str) -> None:
    """Raise LimitExceeded when this message may not be sent; otherwise count it."""
    if len(message) > link["max_message_chars"]:
        raise LimitExceeded(413, f"Message is longer than {link['max_message_chars']} characters")
    if link["rate_limit_per_min"] > 0:
        w = shared_state.add(f"rl:chat:{link['id']}:{ip}", 60, link["rate_limit_per_min"])
        if not w.allowed:
            raise LimitExceeded(429, "Too many messages — wait a moment and try again", w.retry_after)
    if link["max_turns"] > 0:
        w = shared_state.add(f"chat:turns:{link['id']}:{sid}", DAY, link["max_turns"])
        if not w.allowed:
            raise LimitExceeded(429, "This conversation has reached its message limit — start a new chat")
    if link["daily_message_cap"] > 0:
        w = shared_state.add(f"chat:day:{link['id']}", DAY, link["daily_message_cap"])
        if not w.allowed:
            raise LimitExceeded(429, "This chat is busy right now — try again later", w.retry_after)
    conn = get_db_connection()
    try:
        conn.execute("UPDATE chat_links SET message_count = message_count + 1, last_used_at = ? WHERE id = ?",
                     (_now(), link["id"]))
        conn.commit()
    finally:
        conn.close()
