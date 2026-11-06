"""YAML ⇄ JSON — built-in tool `yaml_json_converter`."""

import json
from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params

TOOL = ToolSpec(
    id="yaml_json_converter",
    name="YAML ⇄ JSON",
    icon="🔁",
    category="Data & Files",
    description="Converts YAML to JSON or JSON to YAML.",
    default_config={"direction": "auto"},
    order=110,
    selects={
        "direction": Select("Direction", (("auto", "Auto-detect"), ("yaml_to_json", "YAML → JSON"), ("json_to_yaml", "JSON → YAML"))),
    },
    parameters=params(
        {"content": {"type": "string", "description": "YAML or JSON text"}},
        {"direction": enum(["auto", "yaml_to_json", "json_to_yaml"], "Which way")},
    ),
    input_param="content",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import yaml
    direction = cfg.get("direction", "auto")
    text = inp.strip()
    if not text:
        return "[YAML/JSON] Please provide YAML or JSON text."
    try:
        if direction == "json_to_yaml" or (direction == "auto" and text[:1] in "{["):
            return yaml.safe_dump(json.loads(text), sort_keys=False, allow_unicode=True)
        return json.dumps(yaml.safe_load(text), indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        return f"[YAML/JSON] Couldn't convert: {e}"
