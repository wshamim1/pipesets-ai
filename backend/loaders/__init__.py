"""
Document loader registry.

Every module in this package (searched recursively) that defines ``LOADER`` and ``load``
is registered automatically; ``_planned.py`` lists the loaders that aren't built yet.
``catalog()`` feeds ``GET /api/retrieval/loaders``; ``load_documents()`` runs a loader for
``POST /api/retrieval/ingest/loader``.
"""

import importlib
import os
import pkgutil
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loaders.base import Document, LoaderError, LoaderSpec

Loader = Callable[[str, Dict[str, Any]], Awaitable[List[Document]]]
Parser = Callable[[str, bytes, Dict[str, Any]], List[Document]]

# Sidebar groups, in display order (unknown categories go last)
CATEGORY_ORDER = [
    "Files", "Web & Feeds", "Cloud Storage", "Databases", "Knowledge & SaaS", "Chat & Social", "Research & Media",
]

_specs: Dict[str, LoaderSpec] = {}
_loaders: Dict[str, Loader] = {}
_parsers: Dict[str, Parser] = {}       # ".pdf" -> parse()
_aliases: Dict[str, str] = {}
_loaded = False


def _norm(name: str) -> str:
    return re.sub(r"[\s_-]+", "", str(name or "").lower())


def _register(spec: LoaderSpec, load: Optional[Loader]) -> None:
    if spec.type in _specs:
        raise RuntimeError(f"Loader '{spec.type}' is defined twice — remove it from _planned.py once implemented")
    _specs[spec.type] = spec
    if load is not None:
        _loaders[spec.type] = load
    _aliases[_norm(spec.type)] = spec.type   # a loader's own name beats another loader's alias
    for alias in spec.aliases:
        _aliases.setdefault(_norm(alias), spec.type)


def _load() -> None:
    global _loaded
    if _loaded:
        return
    planned = []
    for mod_info in pkgutil.walk_packages(__path__, prefix=f"{__name__}."):
        leaf = mod_info.name.rsplit(".", 1)[-1]
        if mod_info.name == f"{__name__}._planned":
            planned = importlib.import_module(mod_info.name).LOADERS
            continue
        if leaf.startswith("_") or mod_info.name == f"{__name__}.base":
            continue
        module = importlib.import_module(mod_info.name)
        if not hasattr(module, "LOADER"):
            continue
        _register(module.LOADER, getattr(module, "load", None))
        for ext in getattr(module, "EXTENSIONS", ()):
            _parsers[ext.lower()] = module.parse
    for spec in planned:   # implemented modules registered first win the aliases
        _register(spec, None)
    _loaded = True


def _sort_key(spec: LoaderSpec):
    cat = CATEGORY_ORDER.index(spec.category) if spec.category in CATEGORY_ORDER else len(CATEGORY_ORDER)
    return (cat, spec.category, spec.order, spec.label.lower())


def catalog() -> List[Dict[str, Any]]:
    _load()
    return [s.catalog_entry(s.type in _loaders) for s in sorted(_specs.values(), key=_sort_key)]


def resolve(loader_type: str) -> Optional[str]:
    """Canonical loader type for a type or alias (e.g. "PyPDFLoader" → "pdf")."""
    _load()
    return _aliases.get(_norm(loader_type))


def get_spec(loader_type: str) -> Optional[LoaderSpec]:
    _load()
    return _specs.get(resolve(loader_type) or loader_type)


def parser_for(filename: str) -> Optional[Parser]:
    """The file-format parser for a file name, by extension (used by Directory / S3)."""
    _load()
    return _parsers.get(os.path.splitext(filename)[1].lower())


def supported_extensions() -> List[str]:
    _load()
    return sorted(_parsers)


async def load_documents(loader_type: str, source: str, cfg: Optional[Dict[str, Any]] = None) -> List[Document]:
    """Run a loader. Raises LoaderError with a readable message on any problem."""
    _load()
    canonical = resolve(loader_type) or loader_type
    spec = _specs.get(canonical)
    if spec is None:
        raise LoaderError(f"Unknown document loader '{loader_type}'.")
    load = _loaders.get(canonical)
    if load is None:
        raise LoaderError(f"The {spec.label} loader isn't available yet.")
    if not (source or "").strip() and not spec.uses_connection:
        raise LoaderError(f"Set the {spec.source_label} on the {spec.label} node.")
    return await load(source.strip(), cfg or {})
