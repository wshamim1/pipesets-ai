"""Discord webhook — built-in tool `discord_webhook`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="discord_webhook",
    name="Discord Webhook",
    icon="🎮",
    category="Communication",
    description="Posts messages to a Discord channel via a webhook URL.",
    default_config={"webhook_url": "", "username": "Agentic Bot"},
    order=30,
    required=("webhook_url",),
    parameters=params({"message": {"type": "string", "description": "The message to post"}}),
    input_param="message",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    webhook_url = cfg.get("webhook_url", "")
    if not webhook_url:
        return "[Discord] webhook_url is required in config."
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={"content": inp[:2000], "username": cfg.get("username", "Agentic Bot")})
            if resp.status_code in (200, 204):
                return "[Discord] Message posted."
            return f"[Discord] HTTP {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"[Discord] Error: {e}"
