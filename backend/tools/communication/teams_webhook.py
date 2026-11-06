"""Microsoft Teams webhook (Workflows / incoming webhook) — built-in tool `teams_webhook`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="teams_webhook",
    name="Microsoft Teams Webhook",
    icon="👥",
    category="Communication",
    description="Posts messages to a Microsoft Teams channel via a Workflows webhook URL.",
    default_config={"webhook_url": ""},
    order=40,
    required=("webhook_url",),
    parameters=params({"message": {"type": "string", "description": "The message to post"}}),
    input_param="message",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    webhook_url = cfg.get("webhook_url", "")
    if not webhook_url:
        return "[Teams] webhook_url is required in config."
    card = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "version": "1.4",
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "body": [{"type": "TextBlock", "text": inp, "wrap": True}],
            },
        }],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=card)
            if resp.status_code in (200, 202):
                return "[Teams] Message posted."
            return f"[Teams] HTTP {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"[Teams] Error: {e}"
