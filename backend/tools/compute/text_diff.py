"""Text diff — built-in tool `text_diff`."""

import json
from typing import Any, Dict, Optional

from tools.base import ToolSpec, json_input, params

TOOL = ToolSpec(
    id="text_diff",
    name="Text Diff",
    icon="🆚",
    category="Code & Compute",
    description="Compares two texts and returns a unified diff plus similarity score. Input is JSON {before, after}.",
    default_config={"context_lines": 3},
    order=60,
    parameters=params(
        {
            "before": {"type": "string", "description": "Original text"},
            "after": {"type": "string", "description": "Changed text"},
        },
    ),
    to_input=json_input,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import difflib
    # Input: JSON {"before": ..., "after": ...}, or the two texts separated by a line of "==="
    try:
        d = json.loads(inp)
        before, after = str(d.get("before", "")), str(d.get("after", ""))
    except (json.JSONDecodeError, AttributeError):
        parts = [p for p in inp.split("\n===\n")]
        if len(parts) != 2:
            return '[Text Diff] Input must be JSON {"before": ..., "after": ...} or two texts separated by a line "===".'
        before, after = parts
    diff = list(difflib.unified_diff(
        before.splitlines(), after.splitlines(), "before", "after",
        n=int(cfg.get("context_lines", 3)), lineterm="",
    ))
    if not diff:
        return "[Text Diff] The texts are identical."
    ratio = difflib.SequenceMatcher(None, before, after).ratio()
    return f"[Text Diff] Similarity {ratio:.0%}\n" + "\n".join(diff)
