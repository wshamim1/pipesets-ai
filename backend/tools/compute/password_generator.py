"""Password / token generator — built-in tool `password_generator`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="password_generator",
    name="Password Generator",
    icon="🔑",
    category="Code & Compute",
    description="Generates strong random passwords or tokens with a cryptographic RNG.",
    default_config={"length": 20, "count": 1, "include_symbols": True, "exclude_ambiguous": True},
    order=80,
    parameters=params(
        {},
        {
            "length": {"type": "integer", "minimum": 8, "maximum": 128, "description": "Characters per password"},
            "count": {"type": "integer", "minimum": 1, "maximum": 20, "description": "How many"},
            "include_symbols": {"type": "boolean", "description": "Use symbols"},
            "exclude_ambiguous": {"type": "boolean", "description": "Leave out look-alikes like 0/O, l/1"},
        },
    ),
    input_param="",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import re
    import secrets as _secrets
    import string
    m = re.search(r"\d+", inp)
    length = max(8, min(128, int(m.group(0)) if m else int(cfg.get("length", 20))))
    count = max(1, min(10, int(cfg.get("count", 1))))
    alphabet = string.ascii_letters + string.digits + (cfg.get("symbols", "!@#$%^&*-_=+") if cfg.get("include_symbols", True) else "")
    if cfg.get("exclude_ambiguous", True):
        alphabet = "".join(c for c in alphabet if c not in "Il1O0o")
    passwords = ["".join(_secrets.choice(alphabet) for _ in range(length)) for _ in range(count)]
    return "[Password Generator]\n" + "\n".join(passwords)
