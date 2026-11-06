"""
extraction_reviews.py — the review queue for extracted fields (plan.md P1).

The Structured Extract tool (tools/data/structured_extract.py) files every field it extracts here
as ``pending``, with its citation (page, quote) and whether the quote was found on that page.
A reviewer then, per field:

    approve   the value is right                         → status approved,  final_value = value
    correct   the value is wrong; here's the right one   → status corrected, final_value = theirs
    reject    the field doesn't apply / can't be known    → status rejected,  final_value = null

``bulk_approve`` approves, in one go, pending fields whose quote was found on the cited page and
whose confidence is at or above a threshold (never conflicting ones); they're flagged ``bulk``.

Each cited page's text is kept (``extraction_review_pages``) so the reviewer reads the quote in
context (``page``). ``report`` is per-field accuracy from human decisions, by model and prompt
version.

``export_cases`` turns reviewed documents into eval cases (input: the document's source, expected
output: the reviewed fields as JSON), so every correction becomes a test the next prompt or model
has to pass before it can be published.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from db import get_db_connection

STATUSES = ("pending", "approved", "corrected", "rejected")
DECISIONS = {"approve": "approved", "correct": "corrected", "reject": "rejected"}
COLUMNS = ("id, batch, source, field, description, field_type, value, page, page_label, quote, confidence, "
           "verified, status, final_value, note, model, created_by, reviewed_by, reviewed_at, created_at, "
           "prompt_version, alternatives, conflict, bulk")
MIN_BULK_CONFIDENCE = 0.5


class ReviewError(ValueError):
    pass


def _dump(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _load(raw: Optional[str]) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _row(r: Any) -> Dict[str, Any]:
    d = dict(zip([c.strip() for c in COLUMNS.split(",")], r))
    d["value"], d["final_value"] = _load(d["value"]), _load(d["final_value"])
    d["alternatives"] = _load(d["alternatives"]) or []
    d["verified"], d["conflict"], d["bulk"] = bool(d["verified"]), bool(d["conflict"]), bool(d["bulk"])
    return d


def add(tenant_id: str, project_id: str, source: str, results: List[Dict[str, Any]], batch: str = "",
        created_by: str = "", model: str = "", prompt_version: str = "",
        pages: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """File extraction results (services/extraction.check / merge) as pending reviews. A document filed
    again replaces its earlier *pending* rows in the same batch; decided rows are kept. ``pages``
    (services/extraction.pages_of) → the text of every cited page is kept for the reviewer."""
    now = datetime.utcnow().isoformat()
    batch, source = batch[:200], source[:1000]
    ids = []
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM extraction_reviews WHERE tenant_id = ? AND project_id = ? AND source = ? "
                     "AND batch = ? AND status = 'pending'", (tenant_id, project_id, source, batch))
        for f in results:
            rid = f"rv_{uuid.uuid4().hex[:16]}"
            conn.execute(
                "INSERT INTO extraction_reviews (id, tenant_id, project_id, batch, source, field, description, "
                "field_type, value, page, page_label, quote, confidence, verified, status, note, model, "
                "created_by, created_at, prompt_version, alternatives, conflict, bulk) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending','',?,?,?,?,?,?,?)",
                (rid, tenant_id, project_id, batch, source, f["name"], f.get("description") or "",
                 f.get("type") or "text", _dump(f.get("value")), f.get("page"), f.get("page_label"), f.get("quote"),
                 float(f.get("confidence") or 0), bool(f.get("verified")), model[:200], created_by or "", now,
                 prompt_version[:64], _dump(f.get("alternatives") or None), bool(f.get("conflict")), False),
            )
            ids.append(rid)
        cited = {f.get("page") for f in results} | {a.get("page") for f in results for a in f.get("alternatives") or []}
        for p in pages or []:
            if p["page"] not in cited:
                continue
            conn.execute("DELETE FROM extraction_review_pages WHERE tenant_id = ? AND project_id = ? AND batch = ? "
                         "AND source = ? AND page = ?", (tenant_id, project_id, batch, source, p["page"]))
            conn.execute("INSERT INTO extraction_review_pages (tenant_id, project_id, batch, source, page, page_label, "
                         "text, created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (tenant_id, project_id, batch, source, p["page"], p.get("label"), p["text"], now))
        conn.commit()
    finally:
        conn.close()
    return ids


def list_reviews(tenant_id: str, project_id: str, status: str = "", source: str = "", batch: str = "",
                 limit: int = 200, offset: int = 0) -> Dict[str, Any]:
    """Reviews newest first; within a document, unverified and low-confidence fields first.
    ``counts`` is per status for the same source / batch filter (ignoring ``status``)."""
    where = "tenant_id = ? AND project_id = ?"
    args: List[Any] = [tenant_id, project_id]
    for col, val in (("source", source), ("batch", batch)):
        if val:
            where += f" AND {col} = ?"
            args.append(val)
    conn = get_db_connection()
    try:
        counts = {s: 0 for s in STATUSES}
        for s, n in conn.execute(f"SELECT status, COUNT(*) FROM extraction_reviews WHERE {where} GROUP BY status",
                                 args).fetchall():
            counts[s] = n
        if status:
            where += " AND status = ?"
            args.append(status)
        rows = conn.execute(
            f"SELECT {COLUMNS} FROM extraction_reviews WHERE {where} "
            "ORDER BY created_at DESC, source, verified, confidence, field LIMIT ? OFFSET ?",
            (*args, limit, offset)).fetchall()
    finally:
        conn.close()
    return {"items": [_row(r) for r in rows], "counts": counts}


def get(tenant_id: str, project_id: str, review_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        r = conn.execute(f"SELECT {COLUMNS} FROM extraction_reviews WHERE id = ? AND tenant_id = ? AND project_id = ?",
                         (review_id, tenant_id, project_id)).fetchone()
    finally:
        conn.close()
    return _row(r) if r else None


def decide(tenant_id: str, project_id: str, review_id: str, decision: str, user: str,
           value: Any = None, note: str = "") -> Optional[Dict[str, Any]]:
    """Record a reviewer's decision (a later decision replaces an earlier one). None = not found."""
    status = DECISIONS.get(decision)
    if status is None:
        raise ReviewError(f"Unknown decision '{decision}' (approve, correct or reject).")
    item = get(tenant_id, project_id, review_id)
    if item is None:
        return None
    if status == "corrected" and (value is None or (isinstance(value, str) and not value.strip())):
        raise ReviewError("A correction needs the right value.")
    final = item["value"] if status == "approved" else value if status == "corrected" else None
    conn = get_db_connection()
    try:
        conn.execute("UPDATE extraction_reviews SET status = ?, final_value = ?, note = ?, reviewed_by = ?, "
                     "reviewed_at = ?, bulk = ? WHERE id = ?",
                     (status, _dump(final), (note or "")[:2000], user, datetime.utcnow().isoformat(), False,
                      review_id))
        conn.commit()
    finally:
        conn.close()
    return get(tenant_id, project_id, review_id)


def page(tenant_id: str, project_id: str, review_id: str, page_no: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The cited page's text for a review (or ``page_no``: one of its alternatives' pages).
    None = no such review; ``text`` None = the page wasn't kept (filed before pages were)."""
    item = get(tenant_id, project_id, review_id)
    if item is None:
        return None
    allowed = {item["page"]} | {a.get("page") for a in item["alternatives"]}
    no = item["page"] if page_no is None else page_no
    if no is None or no not in allowed:
        raise ReviewError("This review doesn't cite that page.")
    conn = get_db_connection()
    try:
        r = conn.execute("SELECT page_label, text FROM extraction_review_pages WHERE tenant_id = ? AND project_id = ? "
                         "AND batch = ? AND source = ? AND page = ?",
                         (tenant_id, project_id, item["batch"], item["source"], no)).fetchone()
    finally:
        conn.close()
    return {"review_id": review_id, "source": item["source"], "page": no,
            "page_label": r[0] if r else None, "text": r[1] if r else None}


def bulk_approve(tenant_id: str, project_id: str, min_confidence: float, user: str, batch: str = "",
                 source: str = "", dry_run: bool = False) -> Dict[str, Any]:
    """Approve pending fields with a verified quote and confidence ≥ ``min_confidence`` (not conflicting
    ones, not 'not found'). ``dry_run`` only counts them."""
    if not MIN_BULK_CONFIDENCE <= min_confidence <= 1:
        raise ReviewError(f"The threshold must be between {MIN_BULK_CONFIDENCE} and 1.")
    where = ("tenant_id = ? AND project_id = ? AND status = 'pending' AND verified = ? AND conflict = ? "
             "AND value IS NOT NULL AND confidence >= ?")
    args: List[Any] = [tenant_id, project_id, True, False, min_confidence]
    for col, val in (("batch", batch), ("source", source)):
        if val:
            where += f" AND {col} = ?"
            args.append(val)
    conn = get_db_connection()
    try:
        rows = conn.execute(f"SELECT id, value FROM extraction_reviews WHERE {where}", args).fetchall()
        if not dry_run:
            now, note = datetime.utcnow().isoformat(), f"Bulk approved: quote found, confidence ≥ {min_confidence:.2f}"
            for rid, value in rows:
                conn.execute("UPDATE extraction_reviews SET status = 'approved', final_value = ?, note = ?, "
                             "reviewed_by = ?, reviewed_at = ?, bulk = ? WHERE id = ?",
                             (value, note, user, now, True, rid))
            conn.commit()
    finally:
        conn.close()
    return {"approved": 0 if dry_run else len(rows), "matching": len(rows), "ids": [r[0] for r in rows]}


def report(tenant_id: str, project_id: str, batch: str = "") -> Dict[str, Any]:
    """Accuracy per model, prompt version and field, from human decisions only:

        right   approved, or rejected when the model said "not found"
        wrong   corrected, or rejected when the model gave a value

    Bulk approvals aren't a check of the model, so they're counted (``bulk``) but not scored."""
    clause, args = "tenant_id = ? AND project_id = ?", [tenant_id, project_id]
    if batch:
        clause += " AND batch = ?"
        args.append(batch)
    conn = get_db_connection()
    try:
        rows = conn.execute(f"SELECT model, prompt_version, field, status, value, bulk FROM extraction_reviews "
                            f"WHERE {clause}", args).fetchall()
    finally:
        conn.close()

    def blank() -> Dict[str, Any]:
        return {"right": 0, "wrong": 0, "bulk": 0, "pending": 0, "approved": 0, "corrected": 0, "rejected": 0}

    groups: Dict[tuple, Dict[str, Any]] = {}
    for model, version, field, status, value, bulk in rows:
        g = groups.setdefault((model or "", version or ""), {"total": blank(), "fields": {}})
        for counts in (g["total"], g["fields"].setdefault(field, blank())):
            counts[status] = counts.get(status, 0) + 1
            if status == "pending":
                continue
            if bulk:
                counts["bulk"] += 1
            elif status == "approved" or (status == "rejected" and value is None):
                counts["right"] += 1
            else:
                counts["wrong"] += 1

    def scored(c: Dict[str, Any]) -> Dict[str, Any]:
        checked = c["right"] + c["wrong"]
        return {**c, "checked": checked, "accuracy": round(c["right"] / checked, 4) if checked else None}

    out = []
    for (model, version), g in sorted(groups.items()):
        out.append({"model": model, "prompt_version": version, **scored(g["total"]),
                    "fields": [{"field": f, **scored(c)} for f, c in sorted(g["fields"].items())]})
    return {"groups": out}


def export_cases(tenant_id: str, project_id: str, batch: str = "", only_complete: bool = True) -> List[Dict[str, Any]]:
    """Eval cases from reviewed documents: prompt = the source, expected output = {field: final value}.
    With ``only_complete``, documents that still have pending fields are left out."""
    conn = get_db_connection()
    try:
        args: List[Any] = [tenant_id, project_id]
        clause = "tenant_id = ? AND project_id = ?"
        if batch:
            clause += " AND batch = ?"
            args.append(batch)
        rows = conn.execute(f"SELECT source, field, status, final_value FROM extraction_reviews WHERE {clause} "
                            "ORDER BY source, field", args).fetchall()
    finally:
        conn.close()
    docs: Dict[str, Dict[str, Any]] = {}
    pending: set = set()
    corrected: set = set()
    for source, field, status, final in rows:
        if status == "pending":
            pending.add(source)
            continue
        docs.setdefault(source, {})[field] = _load(final)
        if status == "corrected":
            corrected.add(source)
    cases = []
    for source, fields in docs.items():
        if only_complete and source in pending:
            continue
        tags = ["extraction-review"] + (["corrected"] if source in corrected else [])
        cases.append({"prompt": source, "expected_output": json.dumps(fields, ensure_ascii=False, sort_keys=True),
                      "tags": tags, "source": "manual"})
    return cases
