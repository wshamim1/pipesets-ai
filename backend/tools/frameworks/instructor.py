"""Instructor — structured LLM output extraction — built-in tool `instructor`."""

import os
from typing import Any, Dict, Optional

from tools.base import ToolSpec

TOOL = ToolSpec(
    id="instructor",
    name="Instructor",
    icon="📐",
    group="frameworks",
    description="Extract structured, typed data from any text or LLM response using Pydantic schemas. Guarantees the output matches your schema — no regex or manual parsing needed.",
    default_config={
        "schema_json": "{\"name\": \"string\", \"age\": \"int\"}",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "",
        "max_retries": 3,
    },
    order=30,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    text_input = inp.strip()
    schema_json = (cfg.get("schema_json") or "{}").strip()
    provider = (cfg.get("provider") or "openai").lower()
    model = (cfg.get("model") or "gpt-4o-mini").strip()
    api_key = (cfg.get("api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
    max_retries = int(cfg.get("max_retries", 3))

    if not text_input:
        return "[Instructor] No input text provided."
    if not api_key:
        return "[Instructor] No API key provided. Set 'api_key' in config or OPENAI_API_KEY env var."

    try:
        import json as _json
        import instructor as _instructor
        import openai as _openai
        from pydantic import BaseModel as _BaseModel, create_model as _create_model

        # Parse schema_json to build a dynamic Pydantic model
        try:
            schema_def = _json.loads(schema_json)
        except _json.JSONDecodeError as je:
            return f"[Instructor] Invalid schema_json: {je}"

        # Build a dynamic Pydantic model from the schema dict
        # Supports "string", "int", "float", "bool", "list", "dict" type names
        _type_map = {
            "string": str, "str": str,
            "int": int, "integer": int,
            "float": float, "number": float,
            "bool": bool, "boolean": bool,
            "list": list, "array": list,
            "dict": dict, "object": dict,
        }
        fields: dict = {}
        for field_name, field_type in schema_def.items():
            py_type = _type_map.get(str(field_type).lower(), str)
            fields[field_name] = (py_type, ...)

        DynamicModel = _create_model("ExtractedData", **fields)

        client = _instructor.from_openai(_openai.OpenAI(api_key=api_key))

        extracted = client.chat.completions.create(
            model=model,
            response_model=DynamicModel,
            max_retries=max_retries,
            messages=[
                {"role": "system", "content": "Extract the requested structured data from the provided text. Return only what is present; use null for missing fields."},
                {"role": "user", "content": text_input},
            ],
        )
        result_dict = extracted.model_dump()
        return f"[Instructor — Structured Extraction]\nSchema: {schema_json}\n\n{_json.dumps(result_dict, indent=2)}"

    except ImportError:
        return (
            "[Instructor] Package not found. Install it with:\n"
            "  pip install instructor\n\n"
            "Then restart the backend server."
        )
    except Exception as e:
        return f"[Instructor] Error: {e}"
