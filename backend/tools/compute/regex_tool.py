"""Regex — built-in tool `regex_tool`."""

import json
from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, json_input, params

TOOL = ToolSpec(
    id="regex_tool",
    name="Regex",
    icon="🔍",
    category="Code & Compute",
    description="Finds, tests, splits or replaces text with a regular expression. Input is the text, or JSON with pattern/text/action.",
    default_config={"pattern": "", "flags": "", "action": "findall", "replacement": ""},
    order=40,
    selects={
        "action": Select("Action", (("findall", "Find all matches"), ("test", "Test (true / false)"), ("sub", "Replace"), ("split", "Split"))),
    },
    parameters=params(
        {
            "pattern": {"type": "string", "description": "Regular expression"},
            "text": {"type": "string", "description": "Text to apply it to"},
        },
        {
            "action": enum(["findall", "test", "sub", "split"], "What to do; default findall"),
            "replacement": {"type": "string", "description": "For sub: the replacement"},
            "flags": {"type": "string", "description": "Any of i, m, s"},
        },
    ),
    to_input=json_input,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import re
    # Input is the text; or JSON {"text", "pattern", "action", "replacement"} to override config
    params = dict(cfg)
    text = inp
    if inp.startswith("{"):
        try:
            override = json.loads(inp)
            params.update({k: v for k, v in override.items() if k != "text"})
            text = str(override.get("text", ""))
        except json.JSONDecodeError:
            pass
    pattern = params.get("pattern", "")
    if not pattern:
        return "[Regex] Set a pattern in config or pass {\"pattern\": ..., \"text\": ...} as input."
    flag_map = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}
    flags = 0
    for f in str(params.get("flags", "")).replace(",", ""):
        flags |= flag_map.get(f.lower(), 0)
    text = text[:200_000]
    try:
        rx = re.compile(pattern, flags)
    except re.error as e:
        return f"[Regex] Invalid pattern: {e}"
    action = params.get("action", "findall")
    if action == "sub":
        return rx.sub(str(params.get("replacement", "")), text)
    if action == "split":
        return json.dumps(rx.split(text), indent=2)
    if action == "test":
        return "true" if rx.search(text) else "false"
    matches = rx.findall(text)
    return json.dumps(matches[:500], indent=2) if matches else "[Regex] No matches."
