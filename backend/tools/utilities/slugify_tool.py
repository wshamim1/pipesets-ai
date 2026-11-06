"""Slugify — built-in tool `slugify_tool`."""

import re
from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params

TOOL = ToolSpec(
    id="slugify_tool",
    name="Slugify",
    icon="🔠",
    category="Everyday Utilities",
    description="Turns a title or phrase into a clean URL-safe slug for files, slugs, and IDs.",
    default_config={"separator": "-"},
    order=60,
    selects={
        "separator": Select("Separator", (("-", "Hyphen (-)"), ("_", "Underscore (_)"))),
    },
    parameters=params(
        {"text": {"type": "string", "description": "Text to convert into a slug"}},
        {
            "separator": enum(["-", "_"], "Separator used between words"),
        },
    ),
    input_param="text",
    config_args=("separator",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    text = (inp or "").strip()
    if not text:
        return "[Slugify] Please provide some text to convert into a slug."

    separator = str(cfg.get("separator") or "-")
    if separator not in {"-", "_"}:
        separator = "-"

    value = text.lower()
    value = re.sub(r"[^a-z0-9]+", separator, value)
    value = re.sub(rf"{re.escape(separator)}+", separator, value)
    value = value.strip(separator)
    return value or "[Slugify] No slug could be generated from the supplied text."
