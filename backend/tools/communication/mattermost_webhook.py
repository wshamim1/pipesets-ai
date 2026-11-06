"""Mattermost webhook — built-in tool `mattermost_webhook`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="mattermost_webhook",
    name="Mattermost Webhook",
    icon="🗨️",
    category="Communication",
    description="Posts messages to a Mattermost channel via an incoming webhook URL.",
    default_config={"webhook_url": "", "channel": "", "username": "Agentic Bot"},
    order=90,
    required=("webhook_url",),
    parameters=params({"message": {"type": "string", "description": "The message to post"}}),
    input_param="message",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    webhook_url = cfg.get("webhook_url", "")
    if not webhook_url:
        return "[Mattermost] webhook_url is required in config."
    payload = {"text": inp, "username": cfg.get("username", "Agentic Bot")}
    if cfg.get("channel"):
        payload["channel"] = cfg["channel"]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
        if resp.status_code == 200:
            return "[Mattermost] Message posted."
        return f"[Mattermost] HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return f"[Mattermost] Error: {e}"
