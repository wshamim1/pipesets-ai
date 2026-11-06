"""Encode / hash — built-in tool `encode_hash`."""

from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params

TOOL = ToolSpec(
    id="encode_hash",
    name="Encode / Hash",
    icon="🔐",
    category="Code & Compute",
    description="Base64/URL encode or decode, hash (sha256, sha1, md5) or generate a UUID. Prefix input with 'operation:' to pick per call.",
    default_config={"operation": "sha256"},
    order=50,
    selects={
        "operation": Select("Operation", (("sha256", "SHA-256"), ("sha1", "SHA-1"), ("md5", "MD5"), ("base64_encode", "Base64 encode"), ("base64_decode", "Base64 decode"), ("url_encode", "URL encode"), ("url_decode", "URL decode"), ("uuid", "Generate UUID"))),
    },
    parameters=params(
        {"text": {"type": "string", "description": "The text (ignored for uuid)"}},
        {
            "operation": enum(["sha256", "sha1", "md5", "base64_encode", "base64_decode", "url_encode", "url_decode", "uuid"], "What to do with the text"),
        },
    ),
    input_param="text",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import base64
    import hashlib
    import uuid
    from urllib.parse import quote, unquote
    ops = {
        "base64_encode": lambda s: base64.b64encode(s.encode()).decode(),
        "base64_decode": lambda s: base64.b64decode(s.encode()).decode("utf-8", errors="replace"),
        "url_encode": lambda s: quote(s, safe=""),
        "url_decode": unquote,
        "sha256": lambda s: hashlib.sha256(s.encode()).hexdigest(),
        "sha1": lambda s: hashlib.sha1(s.encode()).hexdigest(),
        "md5": lambda s: hashlib.md5(s.encode()).hexdigest(),
        "uuid": lambda s: str(uuid.uuid4()),
    }
    op, text = cfg.get("operation", "sha256"), inp
    # Allow "operation: text" in the input to pick the operation per call
    head, sep, rest = inp.partition(":")
    if sep and head.strip().lower() in ops:
        op, text = head.strip().lower(), rest.lstrip()
    if op not in ops:
        return f"[Encode/Hash] Unknown operation '{op}'. Use one of: {', '.join(ops)}."
    try:
        return ops[op](text)
    except Exception as e:
        return f"[Encode/Hash] {op} failed: {e}"
