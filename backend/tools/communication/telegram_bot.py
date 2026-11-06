"""Telegram bot — built-in tool `telegram_bot`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="telegram_bot",
    name="Telegram Bot",
    icon="✈️",
    category="Communication",
    description="Sends messages to a Telegram chat through a bot token.",
    default_config={"bot_token": "", "chat_id": ""},
    order=60,
    required=("bot_token", "chat_id"),
    parameters=params({"message": {"type": "string", "description": "The message to post"}}),
    input_param="message",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    bot_token = cfg.get("bot_token", "") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = cfg.get("chat_id", "")
    if not bot_token or not chat_id:
        return "[Telegram] bot_token and chat_id are required in config."
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": inp[:4096]},
            )
            d = resp.json()
            if d.get("ok"):
                return f"[Telegram] Message sent to chat {chat_id}."
            return f"[Telegram] Error: {d.get('description', resp.text)}"
    except Exception as e:
        return f"[Telegram] Error: {e}"
