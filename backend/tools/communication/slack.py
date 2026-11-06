"""Slack — built-in tool `slack` (Slack Web API with a bot token).

Actions: ``post`` (chat.postMessage, optionally as a thread reply) and ``history`` (a channel's
recent messages via conversations.history, or one thread via conversations.replies). Channels can
be given by ID or by name; names are looked up with conversations.list. Bot scopes:
chat:write, channels:history / groups:history, channels:read / groups:read, users:read.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Slack]"
API = "https://slack.com/api"
_CHANNEL_ID = re.compile(r"^[CGD][A-Z0-9]{8,}$")

TOOL = ToolSpec(
    id="slack",
    name="Slack",
    icon="💬",
    category="Communication",
    description="Posts messages to a Slack channel or thread, or reads a channel's recent messages, with a bot token. Input: the message to post (post). The channel is set in config.",
    default_config={"bot_token": "", "channel": "", "action": "post", "thread_ts": "", "max_results": 20},
    order=15,
    required=("bot_token",),
    selects={"action": Select("Action", (("post", "Post a message"), ("history", "Read recent messages")))},
    parameters=params(
        {"text": {"type": "string", "description": "The message to post (post); leave empty for history"}},
        {
            "action": enum(["post", "history"], "post = send a message, history = read recent messages"),
            "thread_ts": {"type": "string", "description": "A message ts: reply in its thread (post) or read the thread (history)"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Messages to read (history)"},
        },
    ),
    input_param="text",
)

_ERRORS = {
    "invalid_auth": "The bot_token is invalid.",
    "not_authed": "The bot_token is invalid.",
    "account_inactive": "The bot_token belongs to a deactivated app or user.",
    "channel_not_found": "Channel not found — check the ID / name, and that the bot can see it.",
    "not_in_channel": "The bot isn't in that channel — invite it with /invite @your-bot.",
    "is_archived": "That channel is archived.",
    "msg_too_long": "The message is too long (Slack's limit is 40,000 characters).",
    "ratelimited": "Slack rate limit hit — try again shortly.",
}


def _error(body: Dict[str, Any]) -> str:
    code = body.get("error", "unknown_error")
    if code == "missing_scope":
        return f"{LABEL} The bot token is missing a scope: add {body.get('needed', 'the needed scope')} to the Slack app."
    return f"{LABEL} {_ERRORS.get(code, code)}"


async def _call(client: httpx.AsyncClient, method: str, http: str = "GET", **kwargs) -> Dict[str, Any]:
    resp = await client.request(http, f"{API}/{method}", **kwargs)
    if resp.status_code == 429:
        return {"ok": False, "error": "ratelimited"}
    try:
        return resp.json()
    except ValueError:
        return {"ok": False, "error": f"HTTP {resp.status_code}"}


async def _channel_id(client: httpx.AsyncClient, channel: str) -> Any:
    """The channel's ID, or an error dict from Slack."""
    if _CHANNEL_ID.match(channel):
        return channel
    name, cursor = channel.lstrip("#").lower(), None
    for _ in range(10):   # 10 pages of 1000 channels
        q: Dict[str, Any] = {"types": "public_channel,private_channel", "exclude_archived": "true", "limit": 1000}
        if cursor:
            q["cursor"] = cursor
        body = await _call(client, "conversations.list", params=q)
        if not body.get("ok"):
            return body
        for c in body.get("channels", []):
            if c.get("name", "").lower() == name:
                return c["id"]
        cursor = (body.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return {"ok": False, "error": "channel_not_found"}


async def _names(client: httpx.AsyncClient, user_ids: List[str]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for uid in user_ids[:20]:
        body = await _call(client, "users.info", params={"user": uid})
        if body.get("ok"):
            u = body.get("user") or {}
            names[uid] = (u.get("profile") or {}).get("display_name") or u.get("real_name") or u.get("name") or uid
    return names


def _when(ts: str) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return ts


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("bot_token") or "").strip()
    if not token:
        return f"{LABEL} bot_token (a Slack bot token, xoxb-…) is required in config."
    action = (cfg.get("action") or "post").strip().lower()
    if action not in ("post", "history"):
        return f'{LABEL} Action is "post" or "history" — got "{action}".'
    channel = str(cfg.get("channel") or "").strip()
    if not channel:
        return f"{LABEL} Set a channel (ID or name) in config."
    thread_ts = str(cfg.get("thread_ts") or "").strip()
    text = inp.strip()

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        if action == "post":
            if not text:
                return f"{LABEL} Provide the message text to post."
            payload: Dict[str, Any] = {"channel": channel, "text": text[:40000]}
            if thread_ts:
                payload["thread_ts"] = thread_ts
            body = await _call(client, "chat.postMessage", "POST", json=payload,
                               headers={"Content-Type": "application/json; charset=utf-8"})
            if not body.get("ok"):
                return _error(body)
            where = f"thread {thread_ts} in {channel}" if thread_ts else channel
            return f"{LABEL} Posted to {where} (ts {body.get('ts')})."

        cid = await _channel_id(client, channel)
        if isinstance(cid, dict):
            return _error(cid)
        limit = max(1, min(int(cfg.get("max_results") or 20), 100))
        if thread_ts:
            body = await _call(client, "conversations.replies", params={"channel": cid, "ts": thread_ts, "limit": limit})
        else:
            body = await _call(client, "conversations.history", params={"channel": cid, "limit": limit})
        if not body.get("ok"):
            return _error(body)
        messages = body.get("messages", [])
        if not thread_ts:
            messages = list(reversed(messages))   # history is newest first; read it in order
        if not messages:
            return f"{LABEL} No messages in {channel}."
        names = await _names(client, sorted({m["user"] for m in messages if m.get("user")}))
        lines = [f"{LABEL} {len(messages)} message(s) in {'thread ' + thread_ts if thread_ts else channel}\n"]
        for m in messages:
            who = names.get(m.get("user", ""), m.get("user") or m.get("username") or "bot")
            replies = f" · {m['reply_count']} replies (thread_ts {m['ts']})" if m.get("reply_count") else ""
            lines.append(f"[{_when(m.get('ts', ''))}] {who}: {m.get('text', '')}{replies}")
        return "\n".join(lines)
