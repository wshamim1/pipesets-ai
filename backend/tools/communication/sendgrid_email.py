"""SendGrid email — built-in tool `sendgrid_email`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="sendgrid_email",
    name="SendGrid Email",
    icon="✉️",
    category="Communication",
    description="Sends email through the SendGrid API. Input is the message body.",
    default_config={
        "api_key": "",
        "from_address": "",
        "to_address": "",
        "subject": "Message from Pipesets AI",
    },
    order=100,
    required=("api_key", "from_address", "to_address"),
    parameters=params(
        {"body": {"type": "string", "description": "The email body"}},
        {"subject": {"type": "string", "description": "Subject line"}},
    ),
    input_param="body",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api_key = cfg.get("api_key", "") or os.environ.get("SENDGRID_API_KEY", "")
    from_addr, to_addr = cfg.get("from_address", ""), cfg.get("to_address", "")
    if not (api_key and from_addr and to_addr):
        return "[SendGrid] api_key, from_address and to_address are required in config."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post("https://api.sendgrid.com/v3/mail/send", headers={"Authorization": f"Bearer {api_key}"}, json={
                "personalizations": [{"to": [{"email": a.strip()} for a in to_addr.split(",") if a.strip()]}],
                "from": {"email": from_addr},
                "subject": cfg.get("subject", "Message from Pipesets AI"),
                "content": [{"type": "text/plain", "value": inp}],
            })
        if resp.status_code == 202:
            return f"[SendGrid] Email accepted for delivery to {to_addr}."
        return f"[SendGrid] HTTP {resp.status_code}: {resp.text[:300]}"
    except Exception as e:
        return f"[SendGrid] Error: {e}"
