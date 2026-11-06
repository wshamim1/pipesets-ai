"""JSON — document loader `json`."""

import asyncio
import json
from typing import Any, Dict, List

from loaders._common import read_file, decode
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="json",
    label="JSON",
    icon="🧾",
    category="Files",
    desc="Load records from a JSON / JSONL file",
    source_label="File Path",
    placeholder="/path/to/data.json",
    file_based=True,
    aliases=("jsonl", "jsonloader"),
    order=50,
)
EXTENSIONS = (".json", ".jsonl", ".ndjson")


def _record_text(record: Any) -> str:
    if isinstance(record, dict):
        return "\n".join(f"{k}: {v if isinstance(v, (str, int, float, bool)) or v is None else json.dumps(v, ensure_ascii=False)}"
                         for k, v in record.items())
    return record if isinstance(record, str) else json.dumps(record, ensure_ascii=False, indent=2)


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    """JSONL / arrays: one document per record. Objects: one document, unless `records_key` names a list in it."""
    text = decode(data).strip()
    try:
        if name.lower().endswith((".jsonl", ".ndjson")):
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            parsed = json.loads(text)
            key = cfg.get("records_key")
            records = parsed if isinstance(parsed, list) else (parsed.get(key) if key and isinstance(parsed.get(key), list) else [parsed])
    except json.JSONDecodeError as e:
        raise LoaderError(f"{name} isn't valid JSON: {e}")
    docs = [document(_record_text(r), source=name, record=i) for i, r in enumerate(records, 1)]
    return [d for d in docs if d["text"].strip()] or [document(text, source=name)]


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
