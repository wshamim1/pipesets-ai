"""
extraction.py — structured extraction with field-level citations (plan.md P1).

Given a document's pages (from any loader: ``{"text", "metadata": {"page", ...}}``) and a list of
fields, a model returns each field's value, the page it found it on and the exact text it read it
from. The quote is then checked against that page here, not trusted:

    verified    the quote (whitespace / case / punctuation aside) appears on the cited page, or
                at least 90% of it does in order (OCR noise)
    confidence  the model's own 0–1 estimate, capped at 0.3 when the quote isn't verified and 0
                when the field wasn't found

Every result names its source and page, so a reviewer (services/extraction_reviews.py) can open
the page and check it, and nothing reaches the database without a citation.

Documents longer than ``max_chars`` (a lease with its exhibits) are split into parts on page
boundaries, preferring to start a part at an article / section / exhibit heading. Each part is one
model call; the results are merged per field: a verified quote beats an unverified one, then the
higher confidence, then the earlier page. Other values the parts found are kept as
``alternatives``, and when a verified one disagrees the field is marked ``conflict`` and its
confidence capped at 0.5, so it is never bulk-approved.

Fields are given as JSON (``[{"name", "description", "type"}]``) or one per line,
``name: what to look for``. ``type`` is a hint for the model (text, date, money, number, boolean).
"""

import asyncio
import difflib
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from loaders.base import Document

MAX_FIELDS = 60
DEFAULT_MAX_CHARS = 150_000   # per model call; longer documents are split into parts
MIN_MAX_CHARS = 2_000
MAX_PARTS = 20
PART_CONCURRENCY = 3
UNVERIFIED_CAP = 0.3
CONFLICT_CAP = 0.5
MATCH_RATIO = 0.9
_SECTION_START = re.compile(r"^[\s#*>|_-]*(article|section|exhibit|schedule|appendix|addendum|amendment|rider)\b",
                            re.IGNORECASE)

SYSTEM_PROMPT = (
    "You extract fields from documents for a compliance database. Every value must come from the "
    "document: never guess or infer what isn't written. For each field return the value, the page "
    "number it is on and `quote`: the exact words copied from that page that state it (one sentence "
    "or table row, at most 300 characters). If a field isn't in the document, return value null, "
    "page null and quote null. `confidence` is 0 to 1: how sure you are the value is right and "
    "complete. Dates as YYYY-MM-DD, money as a plain number without currency signs, booleans as "
    "true / false.\n\nAnswer with JSON only: "
    '{"fields": [{"name": "...", "value": ..., "page": 1, "quote": "...", "confidence": 0.9}]}'
)


class ExtractionError(ValueError):
    """A readable problem with the fields, the documents or the model's answer."""


def parse_fields(spec: Any) -> List[Dict[str, str]]:
    """Field list from JSON (a list of objects or names) or ``name: description`` lines."""
    items: List[Any]
    if isinstance(spec, list):
        items = spec
    else:
        text = str(spec or "").strip()
        if text.startswith("["):
            try:
                items = json.loads(text)
            except json.JSONDecodeError as e:
                raise ExtractionError(f"Fields aren't valid JSON: {e}") from e
        else:
            items = []
            for line in text.splitlines():
                line = line.strip().lstrip("-*• ").strip()
                if line and not line.startswith("#"):
                    name, _, desc = line.partition(":")
                    items.append({"name": name, "description": desc})
    fields: List[Dict[str, str]] = []
    seen = set()
    for item in items:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = re.sub(r"[^a-z0-9]+", "_", str(item.get("name") or "").strip().lower()).strip("_")
        if not name or name in seen:
            continue
        seen.add(name)
        fields.append({"name": name, "description": str(item.get("description") or "").strip(),
                       "type": str(item.get("type") or "text").strip().lower()})
    if not fields:
        raise ExtractionError("No fields to extract. List them one per line as `name: what to look for`.")
    if len(fields) > MAX_FIELDS:
        raise ExtractionError(f"Too many fields ({len(fields)}); extract at most {MAX_FIELDS} per run.")
    return fields


def pages_of(docs: List[Document]) -> List[Dict[str, Any]]:
    """[{"page", "label", "text"}] in document order. The loader's page numbers are kept when they're
    unique; otherwise (an email and its attachments, rows of a report) pages are numbered in order
    and ``label`` says where each came from ("license.pdf p.2", "row 14")."""
    metas = [d.get("metadata") or {} for d in docs]
    numbers = [m.get("page") for m in metas]
    own = all(isinstance(n, int) for n in numbers) and len(set(numbers)) == len(numbers)
    pages = []
    for i, (d, meta) in enumerate(zip(docs, metas), 1):
        where = [meta.get("attachment"), f"p.{meta['page']}" if meta.get("page") else None,
                 f"sheet {meta['sheet']}" if meta.get("sheet") else None, f"row {meta['row']}" if meta.get("row") else None]
        label = " ".join(w for w in where if w) or None
        pages.append({"page": meta["page"] if own else i, "label": None if own else label, "text": d.get("text") or ""})
    return pages


def _field_lines(fields: List[Dict[str, str]]) -> str:
    return "\n".join(f"- {f['name']} ({f['type']}): {f['description'] or f['name'].replace('_', ' ')}"
                     for f in fields)


def prompt_version(fields: List[Dict[str, str]], instructions: str = "") -> str:
    """A short id for the prompt (system prompt + fields + instructions), so the accuracy report can
    compare prompt changes. The document and the part it's in don't count."""
    text = "\n\n".join((SYSTEM_PROMPT, _field_lines(fields), instructions.strip()))
    return "pv_" + hashlib.sha256(text.encode()).hexdigest()[:10]


def build_messages(pages: List[Dict[str, Any]], fields: List[Dict[str, str]], instructions: str = "",
                   max_chars: int = DEFAULT_MAX_CHARS, part: Optional[Tuple[int, int]] = None) -> List[Dict[str, str]]:
    """``part`` = (this part, number of parts) when ``pages`` is one part of a longer document."""
    total = sum(len(p["text"]) for p in pages)
    if total > max_chars:
        raise ExtractionError(f"The document is {total:,} characters; the limit is {max_chars:,}. "
                              "Raise max_chars or split the document.")
    doc = "\n\n".join(f"<page number=\"{p['page']}\"" + (f" from=\"{p['label']}\"" if p["label"] else "")
                       + f">\n{p['text']}\n</page>" for p in pages)
    system = SYSTEM_PROMPT
    if part and part[1] > 1:
        system += (f"\n\nThis is part {part[0]} of {part[1]} of a longer document (pages {pages[0]['page']}"
                   f"–{pages[-1]['page']}). Extract only what these pages state; a field that isn't in them "
                   "is null here even if it's elsewhere in the document.")
    if instructions.strip():
        system += f"\n\nAdditional instructions:\n{instructions.strip()}"
    user = f"Fields:\n{_field_lines(fields)}\n\nDocument:\n{doc}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _pieces(page: Dict[str, Any], max_chars: int) -> List[Dict[str, Any]]:
    """A page longer than ``max_chars`` cut at paragraph (then line, then any) breaks; every piece keeps
    the page number, so citations still point at the page."""
    text, out = page["text"], []
    while len(text) > max_chars:
        cut = next((c for c in (text.rfind("\n\n", 0, max_chars), text.rfind("\n", 0, max_chars))
                    if c > max_chars // 2), max_chars)
        out.append({**page, "text": text[:cut]})
        text = text[cut:].lstrip("\n")
    return out + [{**page, "text": text}]


def split_parts(pages: List[Dict[str, Any]], max_chars: int = DEFAULT_MAX_CHARS) -> List[List[Dict[str, Any]]]:
    """Consecutive pages in parts of at most ``max_chars`` characters. Once a part is two-thirds full it
    ends before a page that opens an article, section or exhibit, so a section isn't cut in two."""
    max_chars = max(MIN_MAX_CHARS, int(max_chars))
    parts: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    size = 0
    for page in pages:
        for piece in _pieces(page, max_chars):
            n = len(piece["text"])
            starts_section = bool(_SECTION_START.match(piece["text"]))
            if current and (size + n > max_chars or (starts_section and size >= max_chars * 2 // 3)):
                parts.append(current)
                current, size = [], 0
            current.append(piece)
            size += n
    if current:
        parts.append(current)
    if len(parts) > MAX_PARTS:
        raise ExtractionError(f"The document needs {len(parts)} parts of {max_chars:,} characters; the limit is "
                              f"{MAX_PARTS}. Raise max_chars or split the document.")
    return parts


def _answer(raw: str) -> List[Dict[str, Any]]:
    m = re.search(r"\{.*\}", raw or "", flags=re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("fields"), list):
        raise ExtractionError("The model didn't answer with the expected JSON ({\"fields\": [...]}).")
    return [f for f in data["fields"] if isinstance(f, dict)]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def quote_found(quote: Optional[str], page_text: str) -> bool:
    q, p = _norm(quote or ""), _norm(page_text)
    if not q or not p:
        return False
    if q in p:
        return True
    matcher = difflib.SequenceMatcher(None, q, p, autojunk=False)
    matched = sum(b.size for b in matcher.get_matching_blocks())
    return matched / len(q) >= MATCH_RATIO


def _confidence(raw: Any) -> float:
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.5


def check(answer: List[Dict[str, Any]], fields: List[Dict[str, str]], pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One result per requested field, in the requested order, with the quote checked."""
    by_name = {re.sub(r"[^a-z0-9]+", "_", str(a.get("name") or "").lower()).strip("_"): a for a in answer}
    text_by_page = {p["page"]: p["text"] for p in pages}
    label_by_page = {p["page"]: p["label"] for p in pages}
    results = []
    for f in fields:
        a = by_name.get(f["name"], {})
        value = a.get("value")
        if isinstance(value, str) and not value.strip():
            value = None
        try:
            page: Optional[int] = int(a["page"]) if a.get("page") is not None else None
        except (TypeError, ValueError):
            page = None
        quote = str(a.get("quote") or "").strip()[:500] or None
        if value is None:
            verified, confidence = False, 0.0
        else:
            verified = page in text_by_page and quote_found(quote, text_by_page[page])
            if not verified and quote:   # right quote, wrong page number
                other = next((no for no, t in text_by_page.items() if quote_found(quote, t)), None)
                if other is not None:
                    page, verified = other, True
            confidence = _confidence(a.get("confidence"))
            if not verified:
                confidence = min(confidence, UNVERIFIED_CAP)
        results.append({"name": f["name"], "description": f["description"], "type": f["type"],
                        "value": value, "page": page, "page_label": label_by_page.get(page) if page else None,
                        "quote": quote, "verified": verified,
                        "confidence": round(confidence, 3), "alternatives": [], "conflict": False})
    return results


def _value_key(value: Any) -> str:
    """Compare values the way a reviewer would: 185000, 185000.0 and "185,000" are the same."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\W+", "", str(value).lower())


def merge(part_results: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """One result per field from each part's ``check`` results (same field order in every part)."""
    merged = []
    for i, first in enumerate(part_results[0]):
        found = [p[i] for p in part_results if p[i]["value"] is not None]
        if not found:
            merged.append(first)
            continue
        found.sort(key=lambda r: (not r["verified"], -r["confidence"], r["page"] or 0))
        best, seen, alternatives = dict(found[0]), {_value_key(found[0]["value"])}, []
        for r in found[1:]:
            key = _value_key(r["value"])
            if key not in seen:
                seen.add(key)
                alternatives.append({k: r[k] for k in ("value", "page", "page_label", "quote", "verified", "confidence")})
        best["alternatives"] = alternatives
        best["conflict"] = any(a["verified"] for a in alternatives)
        if best["conflict"]:
            best["confidence"] = min(best["confidence"], CONFLICT_CAP)
        merged.append(best)
    return merged


async def extract(docs: List[Document], fields: List[Dict[str, str]], llm_cfg: Any, instructions: str = "",
                  max_chars: int = DEFAULT_MAX_CHARS) -> Tuple[List[Dict[str, Any]], int]:
    """Ask the model for every field, one call per part of the document, then check its quotes against
    the pages and merge the parts. → (results, number of parts).

    ``llm_cfg`` has ``provider``, ``model``, ``api_key`` and ``base_url`` (an LLM node config).
    """
    import llm

    pages = pages_of(docs)
    if not any(p["text"].strip() for p in pages):
        raise ExtractionError("The document has no text to extract from.")
    parts = split_parts([p for p in pages if p["text"].strip()], max_chars)
    sem = asyncio.Semaphore(PART_CONCURRENCY)

    async def run(no: int, part: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        messages = build_messages(part, fields, instructions, max(MIN_MAX_CHARS, int(max_chars)), (no, len(parts)))
        where = f" (part {no} of {len(parts)})" if len(parts) > 1 else ""
        async with sem:
            try:
                completion = await llm.complete(llm.request_from_config(
                    llm_cfg, messages, temperature=0.0, max_tokens=min(16000, 400 + 250 * len(fields)),
                    timeout_s=180))
            except Exception as e:  # noqa: BLE001 — shown to the builder as-is
                raise ExtractionError(f"{llm_cfg.provider}/{llm_cfg.model} failed{where}: {e}") from e
        try:
            answer = _answer(completion.text)
        except ExtractionError as e:
            raise ExtractionError(f"{e}{where}") from e
        return check(answer, fields, pages)   # every page, so a quote cited on the wrong page is still found

    results = await asyncio.gather(*(run(no, part) for no, part in enumerate(parts, 1)))
    return merge(list(results)), len(parts)
