"""ntfy push notification — built-in tool `ntfy_push`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

TOOL = ToolSpec(
    id="ntfy_push",
    name="ntfy Push Notification",
    icon="🔔",
    category="Communication",
    description="Sends a push notification to phones/desktops via ntfy (free; self-hostable).",
    default_config={
        "topic": "",
        "server": "https://ntfy.sh",
        "title": "Pipesets AI",
        "priority": "default",
        "access_token": "",
    },
    order=80,
    required=("topic",),
    selects={
        "priority": Select("Priority", (("min", "Min"), ("low", "Low"), ("default", "Default"), ("high", "High"), ("urgent", "Urgent"))),
    },
    parameters=params(
        {"message": {"type": "string", "description": "The notification text"}},
        {
            "title": {"type": "string", "description": "Notification title"},
            "priority": enum(["min", "low", "default", "high", "urgent"], "Notification priority"),
        },
    ),
    input_param="message",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    topic = cfg.get("topic", "").strip()
    if not topic:
        return "[ntfy] topic is required in config (pick a hard-to-guess name; anyone with it can read)."
    server = (cfg.get("server", "") or "https://ntfy.sh").rstrip("/")
    headers = {"Title": cfg.get("title", "Pipesets AI"), "Priority": str(cfg.get("priority", "default"))}
    if cfg.get("access_token"):
        headers["Authorization"] = f"Bearer {cfg['access_token']}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{server}/{topic}", content=inp.encode("utf-8"), headers=headers)
        if resp.status_code == 200:
            return f"[ntfy] Notification sent to topic '{topic}'."
        return f"[ntfy] HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return f"[ntfy] Error: {e}"
