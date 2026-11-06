"""Google Chat webhook — built-in tool `google_chat_webhook`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="google_chat_webhook",
    name="Google Chat Webhook",
    icon="💭",
    category="Communication",
    description="Posts messages to a Google Chat space via an incoming webhook URL.",
    default_config={"webhook_url": ""},
    order=50,
    required=("webhook_url",),
    parameters=params({"message": {"type": "string", "description": "The message to post"}}),
    input_param="message",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    webhook_url = cfg.get("webhook_url", "")
    if not webhook_url:
        return "[Google Chat] webhook_url is required in config."
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={"text": inp})
        if resp.status_code == 200:
            return "[Google Chat] Message posted."
        return f"[Google Chat] HTTP {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"[Google Chat] Error: {e}"
