"""QR code — built-in tool `qr_code`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="qr_code",
    name="QR Code",
    icon="🔳",
    category="APIs & Integrations",
    description="Makes a QR code image link for any text or URL.",
    default_config={"size": 300},
    order=70,
    parameters=params(
        {"text": {"type": "string", "description": "Text or URL to encode"}},
        {"size": {"type": "integer", "minimum": 100, "maximum": 1000, "description": "Image size in pixels"}},
    ),
    input_param="text",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    from urllib.parse import urlencode
    if not inp:
        return "[QR Code] Provide the text or URL to encode."
    size = int(cfg.get("size", 300))
    url = "https://api.qrserver.com/v1/create-qr-code/?" + urlencode({"size": f"{size}x{size}", "data": inp[:900]})
    return f"[QR Code] PNG image for '{inp[:80]}':\n{url}"
