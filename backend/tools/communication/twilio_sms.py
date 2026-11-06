"""Twilio SMS — built-in tool `twilio_sms`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="twilio_sms",
    name="Twilio SMS",
    icon="📱",
    category="Communication",
    description="Sends an SMS through Twilio. Input is the message body.",
    default_config={"account_sid": "", "auth_token": "", "from_number": "", "to_number": ""},
    order=70,
    required=("account_sid", "auth_token", "from_number", "to_number"),
    parameters=params({"body": {"type": "string", "description": "The SMS text"}}),
    input_param="body",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    sid = cfg.get("account_sid", "") or os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = cfg.get("auth_token", "") or os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number, to_number = cfg.get("from_number", ""), cfg.get("to_number", "")
    if not (sid and token and from_number and to_number):
        return "[Twilio] account_sid, auth_token, from_number and to_number are required in config."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data={"From": from_number, "To": to_number, "Body": inp[:1600]},
                auth=(sid, token),
            )
        if resp.status_code in (200, 201):
            return f"[Twilio] SMS queued to {to_number} (sid {resp.json().get('sid', '?')})."
        return f"[Twilio] HTTP {resp.status_code}: {resp.json().get('message', resp.text)}"
    except Exception as e:
        return f"[Twilio] Error: {e}"
