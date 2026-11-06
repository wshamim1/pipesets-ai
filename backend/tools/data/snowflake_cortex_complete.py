"""Snowflake Cortex Complete — built-in tool `snowflake_cortex_complete`: a prompt to an LLM hosted in
Snowflake Cortex through the REST API. The reply may arrive as one JSON body or as server-sent
events; both are read."""

import json
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data import _snowflake as sf

LABEL = "Snowflake Cortex Complete"

TOOL = ToolSpec(
    id="snowflake_cortex_complete",
    name=LABEL,
    icon="🧠",
    category="Data & Files",
    description="Sends a prompt to an LLM hosted in Snowflake Cortex (Claude, Llama, Mistral…) and returns the reply.",
    default_config={**sf.DEFAULT_CONFIG, "model": "claude-sonnet-4-5", "max_tokens": 1024},
    required=(*sf.REQUIRED, "model"),
    selects={"token_type": sf.TOKEN_SELECT},
    order=415,
    parameters=params(
        {"prompt": {"type": "string", "description": "The prompt to send"}},
        {"max_tokens": {"type": "integer", "minimum": 1, "maximum": 8192, "description": "Maximum tokens to generate"}},
    ),
    input_param="prompt",
    config_args=("max_tokens",),
)


def _reply_text(data: Any) -> str:
    """The assistant text from a JSON completion or an SSE stream of delta chunks."""
    if isinstance(data, dict):
        message = ((data.get("choices") or [{}])[0]).get("message") or {}
        return message.get("content") or ""
    chunks = []
    for line in str(data).splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except ValueError:
            continue
        delta = ((event.get("choices") or [{}])[0]).get("delta") or {}
        chunks.append(delta.get("content") or delta.get("text") or "")
    return "".join(chunks)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    model = (cfg.get("model") or "").strip()
    problem = sf.credentials_missing(LABEL, cfg) or sf.missing(LABEL, model=model, prompt=inp)
    if problem:
        return problem
    body = {"model": model, "messages": [{"role": "user", "content": inp}],
            "max_tokens": int(cfg.get("max_tokens") or 1024), "stream": False}
    data, error = await sf.request(LABEL, cfg, "POST", "/api/v2/cortex/inference:complete", body=body, timeout=120.0)
    if error:
        return error
    return f"[{LABEL}] {model}\n{_reply_text(data)}"
