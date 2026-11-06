"""JSON transformer — built-in tool `json_transformer`."""

import json
from typing import Any, Dict, Optional

from tools.base import ToolSpec, json_value, params

TOOL = ToolSpec(
    id="json_transformer",
    name="JSON Transformer",
    icon="🔄",
    category="Data & Files",
    description="Parses and transforms JSON with dot-path or jq-style filters.",
    default_config={"filter": "."},
    order=40,
    parameters=params(
        {"data": {"description": "The JSON to transform"}},
        {
            "filter": {"type": "string", "description": "Dot path like .results.items, or a jq-style filter; default ."},
        },
    ),
    to_input=json_value("data"),
    config_args=("filter",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    jq_filter = cfg.get("filter", ".")
    try:
        data = json.loads(inp)
    except json.JSONDecodeError as e:
        return f"[JSON Transformer] Invalid JSON input: {e}"
    # Simple built-in transforms without jq binary dependency
    if jq_filter == ".":
        return json.dumps(data, indent=2)
    if jq_filter.startswith(".") and "[" not in jq_filter:
        # Dot-path traversal: e.g. ".results" or ".data.items"
        parts = [p for p in jq_filter.lstrip(".").split(".") if p]
        node = data
        for part in parts:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return f"[JSON Transformer] Key '{part}' not found in path"
        return json.dumps(node, indent=2) if node is not None else "null"
    # keys / values / length shortcuts
    if jq_filter == "keys":
        return json.dumps(list(data.keys()) if isinstance(data, dict) else list(range(len(data))), indent=2)
    if jq_filter == "length":
        return str(len(data))
    return f"[JSON Transformer] Unsupported filter '{jq_filter}'. Use '.', '.key', 'keys', or 'length'."
