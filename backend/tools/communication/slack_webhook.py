"""Slack webhook — built-in tool `slack_webhook`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="slack_webhook",
    name="Slack Webhook",
    icon="💬",
    category="Communication",
    description="Posts messages to Slack via an incoming webhook URL.",
    default_config={"webhook_url": "", "channel": "", "username": "Agentic Bot"},
    order=20,
    required=("webhook_url",),
    parameters=params({"message": {"type": "string", "description": "The message to post"}}),
    input_param="message",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    webhook_url = cfg.get("webhook_url", "")
    channel = cfg.get("channel", "")
    username = cfg.get("username", "Agentic Bot")
    if not webhook_url:
        return "[Slack] webhook_url is required in config."
    payload: Dict[str, Any] = {"text": inp, "username": username}
    if channel:
        payload["channel"] = channel
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code == 200:
                return f"[Slack] Message posted to {channel or 'default channel'}."
            return f"[Slack] HTTP {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"[Slack] Error: {e}"
