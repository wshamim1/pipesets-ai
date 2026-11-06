"""Text Chunker / Splitter — built-in tool `text_summarizer`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="text_summarizer",
    name="Text Chunker / Splitter",
    icon="✂️",
    category="Data & Files",
    description="Splits long text into smaller chunks with configurable size and overlap.",
    default_config={"chunk_size": 500, "overlap": 50},
    order=60,
    parameters=params(
        {"text": {"type": "string", "description": "The text to split"}},
        {
            "chunk_size": {"type": "integer", "minimum": 100, "maximum": 20000, "description": "Characters per chunk"},
            "overlap": {"type": "integer", "minimum": 0, "maximum": 5000, "description": "Characters shared between chunks"},
        },
    ),
    input_param="text",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    chunk_size = int(cfg.get("chunk_size", 500))
    overlap = int(cfg.get("overlap", 50))
    if not inp:
        return "[Text Chunker] No text provided."
    chunks = []
    start = 0
    while start < len(inp):
        end = start + chunk_size
        chunks.append(inp[start:end])
        start += chunk_size - overlap
        if start >= len(inp):
            break
    lines = [f"[Text Chunker] {len(chunks)} chunk(s) — size={chunk_size}, overlap={overlap}]\n"]
    for i, chunk in enumerate(chunks, 1):
        lines.append(f"--- Chunk {i} ---\n{chunk}\n")
    return "\n".join(lines)
