"""Python interpreter — built-in tool `python_interpreter`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="python_interpreter",
    name="Python Sandbox",
    icon="🐍",
    category="Code & Compute",
    description="Executes Python scripts in a podman/docker container (no network, read-only, resource-limited). Falls back to a hardened local subprocess when no container engine is running.",
    default_config={
        "timeout": 10,
        "backend": "auto",
        "memory_mb": 256,
        "allow_network": False,
        "image": "python:3.12-slim",
    },
    order=10,
    parameters=params({"code": {"type": "string", "description": "Python code to run; print() what you need back"}}),
    input_param="code",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    from services.sandbox import run_python
    return await run_python(inp, cfg)
