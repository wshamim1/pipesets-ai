"""JSON formatter — built-in tool `json_formatter`."""

import json
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="json_formatter",
    name="JSON Formatter",
    icon="🧩",
    category="Data & Files",
    description="Pretty-prints JSON text and validates that the input is valid JSON.",
    default_config={"indent": 2},
    order=40,
    parameters=params(
        {"json_text": {"type": "string", "description": "JSON text to validate and format"}},
        {
            "indent": {
                "type": "integer",
                "minimum": 0,
                "maximum": 8,
                "description": "Whitespace to indent each level of the JSON output",
            }
        },
    ),
    input_param="json_text",
    config_args=("indent",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    text = (inp or "").strip()
    if not text:
        return "[JSON Formatter] Please provide JSON text to format."

    try:
        value = json.loads(text)
    except Exception as exc:  # pragma: no cover - exercised in tests via validation
        return f"[JSON Formatter] Invalid JSON: {exc}"

    indent = max(0, min(8, int(cfg.get("indent") or 2)))
    return json.dumps(value, ensure_ascii=False, indent=indent)
