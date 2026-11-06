"""Wolfram Alpha (short answers) — built-in tool `wolfram_alpha`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

TOOL = ToolSpec(
    id="wolfram_alpha",
    name="Wolfram Alpha",
    icon="🔺",
    category="Research & Knowledge",
    description="Answers math, science, unit and factual questions with computed short answers. Requires a Wolfram App ID.",
    default_config={"app_id": "", "units": "metric"},
    order=40,
    required=("app_id",),
    selects={
        "units": Select("Units", (("metric", "Metric"), ("imperial", "Imperial"))),
    },
    parameters=params(
        {"question": {"type": "string", "description": "A math, science, unit or factual question"}},
        {"units": enum(["metric", "imperial"], "Unit system")},
    ),
    input_param="question",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    app_id = cfg.get("app_id", "") or os.environ.get("WOLFRAM_APP_ID", "")
    if not app_id:
        return "[Wolfram Alpha] app_id is required in config (or set WOLFRAM_APP_ID)."
    if not inp:
        return "[Wolfram Alpha] Please provide a question."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://api.wolframalpha.com/v1/result", params={
                "appid": app_id, "i": inp, "units": cfg.get("units", "metric"),
            })
        if resp.status_code == 501:
            return f"[Wolfram Alpha] No short answer available for: {inp}"
        resp.raise_for_status()
        return f"[Wolfram Alpha] {resp.text}"
    except Exception as e:
        return f"[Wolfram Alpha] Error: {e}"
