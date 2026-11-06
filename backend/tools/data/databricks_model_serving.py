"""Databricks model serving — built-in tool `databricks_model_serving`: queries a Model Serving
endpoint. Plain text is sent as a chat message; a JSON object is sent as the request body as-is
(for embeddings, classic ML models or custom payloads)."""

import json
from typing import Any, Dict, Optional
from urllib.parse import quote

from tools.base import ToolSpec, params
from tools.data._databricks import missing, report, request

LABEL = "Databricks Model Serving"

TOOL = ToolSpec(
    id="databricks_model_serving",
    name=LABEL,
    icon="🧠",
    category="Data & Files",
    description="Queries a Databricks Model Serving endpoint (foundation models, external models or custom models).",
    default_config={"host": "", "token": "", "endpoint_name": "", "max_tokens": 1024},
    required=("host", "token", "endpoint_name"),
    order=350,
    parameters=params(
        {"input": {"type": "string", "description": "A prompt for chat endpoints, or a JSON request body"}},
        {"max_tokens": {"type": "integer", "minimum": 1, "maximum": 8192,
                        "description": "Maximum tokens to generate (chat prompts only)"}},
    ),
    input_param="input",
    config_args=("max_tokens",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    endpoint = (cfg.get("endpoint_name") or "").strip()
    problem = missing(LABEL, endpoint_name=endpoint, input=inp)
    if problem:
        return problem

    body: Dict[str, Any]
    try:
        parsed = json.loads(inp)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        body = parsed
    else:
        body = {"messages": [{"role": "user", "content": inp}], "max_tokens": int(cfg.get("max_tokens") or 1024)}

    data, error = await request(LABEL, cfg, "POST", f"/serving-endpoints/{quote(endpoint, safe='')}/invocations",
                                body=body, timeout=120.0)
    if error:
        return error
    choices = data.get("choices") if isinstance(data, dict) else None
    if choices and isinstance(choices[0].get("message"), dict):
        return f"[{LABEL}] {endpoint}\n{choices[0]['message'].get('content') or ''}"
    return report(LABEL, data)
