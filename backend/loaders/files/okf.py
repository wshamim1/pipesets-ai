"""OKF bundle — document loader `okf`.

Reads an Open Knowledge Format bundle (https://github.com/open-knowledge-format/open-knowledge-format,
v0.2 / v0.3): a folder (or .zip) of markdown concept files, each starting with YAML frontmatter.
``index.md`` and ``log.md`` are reserved and not concepts.

Every concept becomes one document. Its frontmatter is kept as chunk metadata (``okf_type``, ``title``,
``tags``, ``status``, ``trust``, ``stale``, ``links``, …) and summarised in a short header at the top
of the text, so a model answering from a retrieved chunk can see whether it is deprecated, stale or
only machine-checked.

Settings (``cfg``):
  okf_include_deprecated  false — skip ``status: deprecated`` concepts (they name a ``superseded_by``)
  okf_include_stale       true  — keep concepts past ``stale_after`` (tagged ``stale: true``)
  okf_min_trust           "any" | "machine" | "human" — the lowest trust tier to load

Following the spec's consumer rules, a bundle is never rejected for unknown keys or types, missing
optional fields, broken links or a missing index; files whose frontmatter can't be parsed, or that have
no ``type``, aren't conformant concepts and are skipped (and counted in ``okf_skipped``).
"""

import asyncio
import os
import posixpath
import re
import zipfile
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

import yaml

from loaders._common import MAX_FILE_BYTES, decode
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="okf",
    label="OKF Bundle",
    icon="📚",
    category="Files",
    desc="Load an Open Knowledge Format bundle (folder or .zip) with its trust, freshness and status",
    source_label="Bundle Path",
    placeholder="/path/to/bundle or bundle.zip",
    aliases=("open_knowledge_format", "openknowledgeformat", "okf_bundle"),
    order=85,
)

RESERVED = {"index.md", "log.md"}
TRUST_TIERS = ("unverified", "machine", "human")   # derived per spec §5.3, lowest first
MAX_CONCEPTS = 5000
MAX_BUNDLE_BYTES = 200 * 1024 * 1024

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


# ── Bundle access ─────────────────────────────────────────────────────────────

def _iter_dir(root: str) -> Iterator[Tuple[str, bytes]]:
    """(bundle-relative posix path, bytes) for every .md file under a folder."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fname in sorted(filenames):
            if not fname.lower().endswith(".md") or fname.startswith("."):
                continue
            path = os.path.join(dirpath, fname)
            size = os.path.getsize(path)
            if size > MAX_FILE_BYTES:
                continue
            total += size
            if total > MAX_BUNDLE_BYTES:
                raise LoaderError(f"The bundle is larger than {MAX_BUNDLE_BYTES // (1024 * 1024)} MB.")
            with open(path, "rb") as f:
                yield os.path.relpath(path, root).replace(os.sep, "/"), f.read()


def _iter_zip(path: str) -> Iterator[Tuple[str, bytes]]:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise LoaderError(f"{os.path.basename(path)} is not a valid .zip file.")
    with zf:
        infos = [i for i in zf.infolist()
                 if not i.is_dir() and i.filename.lower().endswith(".md")
                 and not any(p.startswith(".") or p == "__MACOSX" for p in i.filename.split("/"))]
        names = [i.filename for i in infos]
        # A zip of a folder has one top-level directory; the bundle root is inside it
        prefix = ""
        tops = {n.split("/", 1)[0] for n in names}
        if len(tops) == 1 and all("/" in n for n in names):
            prefix = tops.pop() + "/"
        total = 0
        for info in infos:
            if info.file_size > MAX_FILE_BYTES:
                continue
            total += info.file_size
            if total > MAX_BUNDLE_BYTES:   # declared sizes; guards against zip bombs together with read limits
                raise LoaderError(f"The bundle is larger than {MAX_BUNDLE_BYTES // (1024 * 1024)} MB.")
            rel = posixpath.normpath(info.filename[len(prefix):])
            if rel.startswith("../") or rel.startswith("/"):
                continue
            with zf.open(info) as f:
                data = f.read(MAX_FILE_BYTES + 1)
            if len(data) <= MAX_FILE_BYTES:
                yield rel, data


# ── Parsing ───────────────────────────────────────────────────────────────────

def split_frontmatter(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """(frontmatter mapping or None when absent/unparseable, body)."""
    m = _FRONTMATTER.match(text)
    if not m:
        return None, text
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, text[m.end():]
    return (meta if isinstance(meta, dict) else None), text[m.end():]


def _parse_time(value: Any) -> Optional[datetime]:
    """An OKF timestamp: date-time with an offset, or a date (start of that UTC day). Else None."""
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    try:
        if len(s) == 10:
            d = date.fromisoformat(s)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def _events(value: Any) -> List[Dict[str, Any]]:
    """`verified` as a list of {by, at} (a bare mapping is a one-element list)."""
    if isinstance(value, dict):
        value = [value]
    return [e for e in value if isinstance(e, dict)] if isinstance(value, list) else []


def trust_tier(meta: Dict[str, Any]) -> str:
    """Spec §5.3: no verification → unverified; any `human:` verifier → human; others → machine.
    Only events at or after `generated.at` count (v0.3)."""
    generated = meta.get("generated") if isinstance(meta.get("generated"), dict) else {}
    since = _parse_time(generated.get("at"))
    tier = "unverified"
    for ev in _events(meta.get("verified")):
        by = str(ev.get("by") or "").strip()
        at = _parse_time(ev.get("at"))
        if not by or (since and (at is None or at < since)):
            continue
        if by.startswith("human:"):
            return "human"
        tier = "machine"
    return tier


def _resolve_link(target: str, rel_path: str, root_relative_fallback: bool) -> Optional[str]:
    """A bundle path for a markdown link target, or None for external / anchor-only links."""
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
        return None
    if target.startswith("/"):
        path = target.lstrip("/")
    elif root_relative_fallback and not target.startswith("."):
        path = target                                   # v0.2 / unversioned bundles (§6.2)
    else:
        path = posixpath.join(posixpath.dirname(rel_path), target)
    path = posixpath.normpath(path)
    return None if path.startswith("..") else path


def _str_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if v is not None and not isinstance(v, (dict, list))] if isinstance(value, list) else []


def _header(meta: Dict[str, Any], title: str, info: Dict[str, Any]) -> str:
    bits = [f"OKF {meta.get('type')}", f"status: {info['status']}", f"trust: {info['trust']}"]
    if info.get("stale"):
        bits.append("STALE")
    if info.get("superseded_by"):
        bits.append(f"superseded by {info['superseded_by']}")
    lines = [f"# {title}", f"[{' · '.join(bits)}]"]
    if meta.get("description"):
        lines.append(str(meta["description"]).strip())
    return "\n".join(lines)


def parse_bundle(files: List[Tuple[str, bytes]], bundle: str, cfg: Dict[str, Any],
                 now: Optional[datetime] = None) -> List[Document]:
    now = now or datetime.now(timezone.utc)
    include_deprecated = str(cfg.get("okf_include_deprecated", False)).lower() in ("1", "true", "yes")
    include_stale = str(cfg.get("okf_include_stale", True)).lower() not in ("0", "false", "no")
    min_trust = str(cfg.get("okf_min_trust") or "any").lower()
    if min_trust not in ("any", *TRUST_TIERS):
        raise LoaderError("okf_min_trust must be any, machine or human.")
    floor = 0 if min_trust == "any" else TRUST_TIERS.index(min_trust)

    by_path = {p: d for p, d in files}
    if not any(posixpath.basename(p).lower() not in RESERVED for p in by_path):
        raise LoaderError(f"No concept files (.md) found in {bundle}.")

    version = ""
    root_index = by_path.get("index.md")
    if root_index is not None:
        idx_meta, _ = split_frontmatter(decode(root_index))
        if idx_meta and idx_meta.get("okf_version") is not None:
            version = str(idx_meta["okf_version"])
    root_fallback = version in ("", "0.1", "0.2")

    docs: List[Document] = []
    skipped = {"nonconformant": 0, "deprecated": 0, "stale": 0, "trust": 0}
    for rel, data in sorted(by_path.items()):
        if posixpath.basename(rel).lower() in RESERVED:
            continue
        meta, body = split_frontmatter(decode(data))
        if not meta or not str(meta.get("type") or "").strip():
            skipped["nonconformant"] += 1
            continue

        status = str(meta.get("status") or "stable").strip().lower()
        stale_after = _parse_time(meta.get("stale_after"))
        stale = bool(stale_after and now >= stale_after)
        trust = trust_tier(meta)
        if status == "deprecated" and not include_deprecated:
            skipped["deprecated"] += 1
            continue
        if stale and not include_stale:
            skipped["stale"] += 1
            continue
        if TRUST_TIERS.index(trust) < floor:
            skipped["trust"] += 1
            continue
        if len(docs) >= MAX_CONCEPTS:
            raise LoaderError(f"The bundle has more than {MAX_CONCEPTS:,} concepts. Load a subfolder instead.")

        links = sorted({p for t in _LINK.findall(body) if (p := _resolve_link(t, rel, root_fallback))})
        sources = [s for s in meta.get("sources") or [] if isinstance(s, dict) and s.get("resource")] \
            if isinstance(meta.get("sources"), list) else []
        generated = meta.get("generated") if isinstance(meta.get("generated"), dict) else {}
        title = str(meta.get("title") or posixpath.splitext(posixpath.basename(rel))[0]).strip()
        info: Dict[str, Any] = {
            "status": status if status in ("draft", "stable", "deprecated") else f"unknown:{status}",
            "trust": trust,
            "stale": stale,
            "superseded_by": meta.get("superseded_by") if isinstance(meta.get("superseded_by"), str) else None,
        }
        text = f"{_header(meta, title, info)}\n\n{body.strip()}".strip()
        docs.append(document(
            text,
            source=f"{bundle}/{rel}" if bundle else rel,
            okf_path=rel,
            okf_type=str(meta["type"]).strip(),
            okf_version=version or None,
            title=title,
            description=str(meta.get("description") or "").strip() or None,
            resource=meta.get("resource") if isinstance(meta.get("resource"), str) else None,
            tags=_str_list(meta.get("tags")) or None,
            status=info["status"],
            trust=trust,
            stale=stale,
            stale_after=stale_after.isoformat() if stale_after else None,
            superseded_by=info["superseded_by"],
            generated_by=str(generated.get("by")) if generated.get("by") else None,
            sources=[str(s["resource"]) for s in sources] or None,
            links=links or None,
        ))

    if not docs:
        why = ", ".join(f"{n} {k}" for k, n in skipped.items() if n) or "nothing loadable"
        raise LoaderError(f"No concepts loaded from {bundle} (skipped: {why}).")
    if any(skipped.values()):
        docs[0]["metadata"]["okf_skipped"] = {k: n for k, n in skipped.items() if n}
    return docs


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    path = os.path.expanduser(source.strip().strip("'\""))
    if os.path.isdir(path):
        reader = _iter_dir
    elif os.path.isfile(path) and path.lower().endswith(".zip"):
        reader = _iter_zip
    elif os.path.isfile(path):
        raise LoaderError("Point the OKF loader at the bundle's folder or a .zip of it, not a single file.")
    else:
        raise LoaderError(f"Bundle not found: {path}")
    bundle = os.path.basename(path.rstrip("/"))

    def run() -> List[Document]:
        return parse_bundle(list(reader(path)), bundle, cfg)

    return await asyncio.to_thread(run)
