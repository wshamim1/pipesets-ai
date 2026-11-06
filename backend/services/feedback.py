"""
feedback.py — 👍 / 👎 on runs, from the people who read the answers (plan.md F2).

Who can rate
------------
  runner     a builder in the Prompt Runner (``rater`` = their user id)
  chat_link  a chat-link visitor (``rater`` = ``link:<link id>:<session>``); visitors never see run
             ids, so the answer's ``done`` event carries ``chat_token(...)``, sealed and bound to the
             link and the visitor's session, and they rate with that
  api        a ``/v1`` caller (``rater`` = ``key:<key id>:<user>``, the request's ``user`` or "")

One rating per (run, rater): rating again replaces it. Only finished runs of the rater's own
tenant / project can be rated. A rating keeps the pipeline's version at the time, so versions can be
compared; the prompt and answer are read from ``agent_runs`` when listing, not copied.

Feedback → evals: ``to_cases`` turns rated runs into eval cases — the prompt is the run's input, the
expected output is the rater's correction, else the answer itself for a 👍 (a known-good reference),
else empty for a 👎 without a correction (the case still lands, tagged, for someone to fill in).
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from db import get_db_connection
from services import secret_store

SOURCES = ("runner", "chat_link", "api")
MAX_COMMENT = 4000
MAX_CORRECTION = 20000
PREVIEW_CHARS = 2000


class FeedbackError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── Chat-link feedback tokens ─────────────────────────────────────────────────

def chat_token(link_id: str, sid: str, run_id: str) -> str:
    return secret_store.encrypt(json.dumps({"l": link_id, "s": sid, "r": run_id}))


def open_chat_token(token: str, link_id: str, sid: str) -> Optional[str]:
    """The run id inside ``token`` when it was issued to this visitor on this link, else None."""
    try:
        data = json.loads(secret_store.decrypt(token))
    except Exception:
        return None
    return data.get("r") if data.get("l") == link_id and data.get("s") == sid and data.get("r") else None


# ── Rating ────────────────────────────────────────────────────────────────────

def rate(tenant_id: str, project_id: str, run_id: str, source: str, rater: str, rating: int,
         comment: str = "", correction: str = "") -> Dict[str, Any]:
    """Record (or replace) ``rater``'s rating of ``run_id``; returns the stored feedback."""
    if source not in SOURCES:
        raise FeedbackError(400, f"Unknown source '{source}'")
    if rating not in (1, -1):
        raise FeedbackError(422, "rating must be 1 (👍) or -1 (👎)")
    now = _now()
    conn = get_db_connection()
    try:
        run = conn.execute("SELECT app_id, status FROM agent_runs WHERE run_id = ? AND tenant_id = ? AND project_id = ?",
                           (run_id, tenant_id, project_id)).fetchone()
        if not run:
            raise FeedbackError(404, "Run not found")
        if run["status"] in ("running", "cancelling"):
            raise FeedbackError(409, "The run hasn't finished yet")
        app = conn.execute("SELECT version FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (run["app_id"], tenant_id, project_id)).fetchone() if run["app_id"] else None
        fields = {"rating": rating, "comment": (comment or "").strip()[:MAX_COMMENT],
                  "correction": (correction or "").strip()[:MAX_CORRECTION], "updated_at": now}
        existing = conn.execute("SELECT id FROM run_feedback WHERE run_id = ? AND rater = ?", (run_id, rater)).fetchone()
        if existing:
            feedback_id = existing["id"]
            conn.execute(f"UPDATE run_feedback SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), feedback_id))
        else:
            feedback_id = f"fb_{uuid.uuid4().hex}"
            row = {"id": feedback_id, "tenant_id": tenant_id, "project_id": project_id, "app_id": run["app_id"],
                   "app_version": int(app["version"] or 0) if app else 0, "run_id": run_id, "source": source,
                   "rater": rater, "created_at": now, **fields}
            conn.execute(f"INSERT INTO run_feedback ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                         tuple(row.values()))
        conn.commit()
    finally:
        conn.close()
    return get(tenant_id, project_id, feedback_id)


def remove(tenant_id: str, project_id: str, run_id: str, rater: str) -> bool:
    """Take back a rating."""
    conn = get_db_connection()
    try:
        n = conn.execute("DELETE FROM run_feedback WHERE run_id = ? AND rater = ? AND tenant_id = ? AND project_id = ?",
                         (run_id, rater, tenant_id, project_id)).rowcount
        conn.commit()
    finally:
        conn.close()
    return n > 0


# ── Reading ───────────────────────────────────────────────────────────────────

_SELECT = ("SELECT f.*, r.goal AS prompt, r.final_answer AS output, a.name AS app_name "
           "FROM run_feedback f LEFT JOIN agent_runs r ON r.run_id = f.run_id "
           "LEFT JOIN apps a ON a.id = f.app_id ")


def _row(r: Any, full: bool = False) -> Dict[str, Any]:
    d = dict(r)
    if not full:
        for k in ("prompt", "output"):
            if d.get(k) and len(d[k]) > PREVIEW_CHARS:
                d[k] = d[k][:PREVIEW_CHARS] + "…"
    d["prompt"], d["output"] = d.get("prompt") or "", d.get("output") or ""
    # A visitor's session and an API caller's key stay internal; the builder sees who in plain terms
    if d["source"] == "chat_link":
        d["rater"] = "chat visitor"
    elif d["source"] == "api":
        parts = d["rater"].split(":", 2)
        d["rater"] = (parts[2] if len(parts) == 3 else "") or "API caller"
    return d


def get(tenant_id: str, project_id: str, feedback_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        r = conn.execute(_SELECT + "WHERE f.id = ? AND f.tenant_id = ? AND f.project_id = ?",
                         (feedback_id, tenant_id, project_id)).fetchone()
    finally:
        conn.close()
    return _row(r, full=True) if r else None


def mine(tenant_id: str, project_id: str, run_id: str, rater: str) -> Optional[Dict[str, Any]]:
    """``rater``'s rating of ``run_id``, if any (the runner shows it again when a run is reopened)."""
    conn = get_db_connection()
    try:
        r = conn.execute(_SELECT + "WHERE f.run_id = ? AND f.rater = ? AND f.tenant_id = ? AND f.project_id = ?",
                         (run_id, rater, tenant_id, project_id)).fetchone()
    finally:
        conn.close()
    return _row(r) if r else None


def _filters(tenant_id: str, project_id: str, app_id: str, rating: Optional[int], version: Optional[int],
             source: str, days: int) -> tuple:
    where = ["f.tenant_id = ?", "f.project_id = ?"]
    params: List[Any] = [tenant_id, project_id]
    if app_id:
        where.append("f.app_id = ?")
        params.append(app_id)
    if rating in (1, -1):
        where.append("f.rating = ?")
        params.append(rating)
    if version:
        where.append("f.app_version = ?")
        params.append(version)
    if source:
        where.append("f.source = ?")
        params.append(source)
    if days:
        where.append("f.updated_at >= ?")
        params.append((datetime.utcnow() - timedelta(days=days)).isoformat())
    return " AND ".join(where), params


def list_feedback(tenant_id: str, project_id: str, app_id: str = "", rating: Optional[int] = None,
                  version: Optional[int] = None, source: str = "", days: int = 0,
                  limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    where, params = _filters(tenant_id, project_id, app_id, rating, version, source, days)
    conn = get_db_connection()
    try:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM run_feedback f WHERE {where}", tuple(params)).fetchone()["n"]
        rows = conn.execute(_SELECT + f"WHERE {where} ORDER BY f.updated_at DESC LIMIT ? OFFSET ?",
                            (*params, limit, offset)).fetchall()
    finally:
        conn.close()
    return {"total": int(total), "items": [_row(r) for r in rows]}


def summary(tenant_id: str, project_id: str, app_id: str = "", days: int = 0) -> List[Dict[str, Any]]:
    """👍 / 👎 counts and the 👍 share per pipeline and version, newest version first."""
    where, params = _filters(tenant_id, project_id, app_id, None, None, "", days)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT f.app_id, a.name AS app_name, f.app_version, "
            "SUM(CASE WHEN f.rating > 0 THEN 1 ELSE 0 END) AS up, "
            "SUM(CASE WHEN f.rating < 0 THEN 1 ELSE 0 END) AS down, "
            "SUM(CASE WHEN f.comment <> '' THEN 1 ELSE 0 END) AS comments, MAX(f.updated_at) AS last_at "
            f"FROM run_feedback f LEFT JOIN apps a ON a.id = f.app_id WHERE {where} "
            "GROUP BY f.app_id, a.name, f.app_version ORDER BY f.app_id, f.app_version DESC",
            tuple(params),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        up, down = int(r["up"] or 0), int(r["down"] or 0)
        out.append({"app_id": r["app_id"], "app_name": r["app_name"] or "", "version": int(r["app_version"] or 0),
                    "up": up, "down": down, "total": up + down, "comments": int(r["comments"] or 0),
                    "satisfaction": round(up / (up + down), 4) if up + down else None, "last_at": r["last_at"]})
    return out


# ── Feedback → eval cases ─────────────────────────────────────────────────────

def to_cases(tenant_id: str, project_id: str, feedback_ids: List[str]) -> List[Dict[str, Any]]:
    """Eval cases for these ratings (in this project, with a prompt); see the module docstring."""
    if not feedback_ids:
        return []
    marks = ", ".join("?" for _ in feedback_ids)
    conn = get_db_connection()
    try:
        rows = conn.execute(_SELECT + f"WHERE f.id IN ({marks}) AND f.tenant_id = ? AND f.project_id = ?",
                            (*feedback_ids, tenant_id, project_id)).fetchall()
    finally:
        conn.close()
    cases = []
    for r in rows:
        d = _row(r, full=True)
        if not d["prompt"].strip():
            continue
        expected = d["correction"] or (d["output"] if d["rating"] > 0 else "")
        tags = ["feedback", "thumbs_up" if d["rating"] > 0 else "thumbs_down", d["source"]]
        if d["app_version"]:
            tags.append(f"v{d['app_version']}")
        cases.append({"feedback_id": d["id"], "prompt": d["prompt"], "expected_output": expected,
                      "tags": tags, "source": "feedback"})
    return cases


def mark_exported(tenant_id: str, project_id: str, feedback_ids: List[str], dataset_id: str) -> None:
    if not feedback_ids:
        return
    marks = ", ".join("?" for _ in feedback_ids)
    conn = get_db_connection()
    try:
        conn.execute(f"UPDATE run_feedback SET dataset_id = ? WHERE id IN ({marks}) AND tenant_id = ? AND project_id = ?",
                     (dataset_id, *feedback_ids, tenant_id, project_id))
        conn.commit()
    finally:
        conn.close()
