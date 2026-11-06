"""JSON Schema validator — built-in tool `json_schema_validator`."""

import json
from typing import Any, Dict, Optional

from tools.base import ToolSpec, json_input, json_value, params

TOOL = ToolSpec(
    id="json_schema_validator",
    name="JSON Schema Validator",
    icon="✅",
    category="Code & Compute",
    description="Validates JSON against a JSON Schema and lists every violation.",
    default_config={"schema": ""},
    order=90,
    parameters=params(
        {"data": {"description": "The JSON document to check"}},
        {"schema": {"type": "object", "description": "JSON Schema; default the one in the node's config"}},
    ),
    to_input=lambda a: json_input(a) if a.get("schema") else json_value("data")(a),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import jsonschema
    try:
        payload = json.loads(inp) if inp else {}
    except json.JSONDecodeError as e:
        return f"[JSON Schema] Input is not valid JSON: {e}"
    # Input: the document (schema in config), or {"schema": ..., "data": ...}
    if isinstance(payload, dict) and "schema" in payload and "data" in payload:
        schema, data = payload["schema"], payload["data"]
    else:
        schema, data = cfg.get("schema") or {}, payload
        if isinstance(schema, str):
            try:
                schema = json.loads(schema)
            except json.JSONDecodeError as e:
                return f"[JSON Schema] The configured schema is not valid JSON: {e}"
    if not schema:
        return '[JSON Schema] Set a schema in config, or pass {"schema": ..., "data": ...} as input.'
    try:
        validator = jsonschema.Draft202012Validator(schema)
    except jsonschema.SchemaError as e:
        return f"[JSON Schema] Invalid schema: {e.message}"
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if not errors:
        return "[JSON Schema] ✓ Valid."
    return "[JSON Schema] ✗ Invalid:\n" + "\n".join(
        f"  - {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors[:20])
