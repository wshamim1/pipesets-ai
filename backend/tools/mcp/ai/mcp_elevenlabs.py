"""MCP ElevenLabs — built-in MCP server `mcp_elevenlabs` (elevenlabs-mcp, by ElevenLabs; version pinned).

Text to speech, speech to text, sound effects, voice search and design, and conversational agents.
The API key goes in ``ELEVENLABS_API_KEY``. Generated audio is written to ``output_dir`` (the server
would otherwise use ~/Desktop, which a server host may not have). The input is spoken with the
default voice; with no input, the account's voices are listed.
"""

import os
import tempfile
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_elevenlabs",
    name="MCP ElevenLabs",
    type="mcp",
    icon="🔊",
    group="mcp_servers",
    category="AI & Memory",
    description="Text to speech, transcription, sound effects and voice search with ElevenLabs. Audio files are saved to output_dir.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["elevenlabs-mcp@0.12.2"],
        "elevenlabs_api_key": "",
        "output_dir": "",
        "default_voice_id": "",
    },
    required=("elevenlabs_api_key",),
    order=340,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["elevenlabs-mcp@0.12.2"]
DEFAULT_TOOL = "text_to_speech"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["ELEVENLABS_API_KEY"] = config_value(config, "elevenlabs_api_key")
    env_vars["ELEVENLABS_MCP_BASE_PATH"] = (config_value(config, "output_dir")
                                            or os.path.join(tempfile.gettempdir(), "pipesets-elevenlabs"))
    voice = config_value(config, "default_voice_id")
    if voice:
        env_vars["ELEVENLABS_DEFAULT_VOICE_ID"] = voice
    if config.get("tool_name"):
        return args, config["tool_name"], config.get("arguments") or {}
    text = input_text.strip()
    if not text:
        return args, "search_voices", {}
    return args, defaults["default_tool"], {"text": text}


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
