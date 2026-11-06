"""Shell / bash executor — built-in tool `shell_executor`."""

import subprocess
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="shell_executor",
    name="Shell Executor",
    icon="💻",
    category="Code & Compute",
    description="Runs shell commands (bash). Optionally restrict to an allowlist.",
    default_config={"allowed_commands": "ls,cat,echo,pwd,date", "timeout": 15},
    order=30,
    parameters=params({"command": {"type": "string", "description": "A bash command"}}),
    input_param="command",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    allowed_cmds_raw = cfg.get("allowed_commands", "")
    timeout = int(cfg.get("timeout", 15))
    allowed = [c.strip() for c in allowed_cmds_raw.split(",") if c.strip()]
    first_word = inp.split()[0] if inp.strip() else ""
    if allowed and first_word not in allowed:
        return f"[Shell] Command '{first_word}' is not in the allowed list: {allowed}"
    try:
        res = subprocess.run(
            inp, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        out = res.stdout or ""
        err = res.stderr or ""
        if res.returncode == 0:
            return out or "(Command finished with no output)"
        return f"Exit code {res.returncode}\nstdout: {out}\nstderr: {err}"
    except subprocess.TimeoutExpired:
        return f"[Shell] Timed out after {timeout}s"
    except Exception as e:
        return f"[Shell] Error: {e}"
