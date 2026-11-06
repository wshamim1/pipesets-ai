"""
base.py — building blocks for document loaders.

A loader is a module under ``backend/loaders/`` that defines:

    LOADER = LoaderSpec(type=..., label=..., icon=..., category=..., ...)

    async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
        ...

``source`` is what the user typed in the node (path, URL, query, …); ``cfg`` holds the
node's loader settings plus ``connection`` (the linked Connection node's config, secrets
already decrypted). File-format loaders also define ``EXTENSIONS`` and a synchronous
``parse(name, data, cfg)`` so the Directory and S3 loaders can reuse them on raw bytes.

Loaders that aren't built yet are listed as specs in ``_planned.py`` — shown in the UI as
"Soon" and not runnable. Implementing one = add its module, delete its planned entry.
"""

from dataclasses import dataclass
from typing import Any, Dict, Tuple

Document = Dict[str, Any]  # {"text": str, "metadata": {...}}


def document(text: str, **metadata: Any) -> Document:
    return {"text": text, "metadata": {k: v for k, v in metadata.items() if v not in (None, "")}}


class LoaderError(Exception):
    """A readable problem with the source or settings (shown to the user as-is)."""


@dataclass(frozen=True)
class LoaderSpec:
    type: str
    label: str
    icon: str
    desc: str
    category: str
    source_label: str = "Source"
    placeholder: str = ""
    file_based: bool = False          # shows the upload dropzone in the node config
    uses_connection: bool = False     # credentials come from a linked Connection node
    aliases: Tuple[str, ...] = ()     # other names an LLM / code importer may use
    order: int = 1000                 # position within its category

    def catalog_entry(self, available: bool) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "type": self.type, "label": self.label, "icon": self.icon, "desc": self.desc,
            "category": self.category, "sourceLabel": self.source_label, "placeholder": self.placeholder,
            "available": available,
        }
        if self.file_based:
            entry["fileBased"] = True
        if self.uses_connection:
            entry["usesConnection"] = True
        if self.aliases:
            entry["aliases"] = list(self.aliases)
        return entry

