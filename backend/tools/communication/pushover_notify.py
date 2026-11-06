"""Pushover — built-in tool `pushover_notify` (Pushover Messages API)."""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Pushover]"
API = "https://api.pushover.net/1/messages.json"
PRIORITIES = {"lowest": -2, "low": -1, "normal": 0, "high": 1}

TOOL = ToolSpec(
    id="pushover_notify",
    name="Pushover Notification",
    icon="📲",
    category="Communication",
    description="Sends a push notification to phones, tablets and desktops through Pushover.",
    default_config={"app_token": "", "user_key": "", "title": "Pipesets AI", "priority": "normal", "device": "", "sound": ""},
    order=110,
    required=("app_token", "user_key"),
    selects={"priority": Select("Priority", (("lowest", "Lowest (no alert)"), ("low", "Low (quiet)"),
                                             ("normal", "Normal"), ("high", "High (bypasses quiet hours)")))},
    parameters=params(
        {"message": {"type": "string", "description": "The notification text (up to 1024 characters)"}},
        {"title": {"type": "string", "description": "Notification title"},
         "priority": enum(list(PRIORITIES), "Notification priority")},
    ),
    input_param="message",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("app_token") or "").strip()
    user = (cfg.get("user_key") or "").strip()
    if not token:
        return f"{LABEL} app_token (create an application at pushover.net/apps) is required in config."
    if not user:
        return f"{LABEL} user_key (shown on your pushover.net dashboard) is required in config."
    if not inp:
        return f"{LABEL} Provide the message to send."
    priority = str(cfg.get("priority") or "normal").lower()
    if priority not in PRIORITIES:
        return f"{LABEL} Priority is one of {', '.join(PRIORITIES)} — got '{priority}'."
    form = {"token": token, "user": user, "message": inp[:1024], "title": (cfg.get("title") or "Pipesets AI")[:250],
            "priority": PRIORITIES[priority]}
    for key in ("device", "sound"):
        if (cfg.get(key) or "").strip():
            form[key] = cfg[key].strip()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(API, data=form)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach Pushover: {e}"
    try:
        body = resp.json()
    except ValueError:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    if resp.status_code == 200 and body.get("status") == 1:
        return f"{LABEL} Notification sent" + (" (message cut to 1024 characters)." if len(inp) > 1024 else ".")
    return f"{LABEL} Not sent: {'; '.join(body.get('errors') or []) or f'HTTP {resp.status_code}'}"
