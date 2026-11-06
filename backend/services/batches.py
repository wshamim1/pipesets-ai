"""
batches.py — run a published pipeline once per input row (plan.md F5).

A batch is a pipeline, a prompt template and a list of rows (CSV, JSONL, Excel or one prompt per
line, ``parse_file``). ``{column}`` placeholders in the template make one prompt per row; each row is
a ``batch_items`` row worked as a ``batch.run`` job, through the same path as schedules and webhooks
(scheduler.run_attempt): latest published version, as the batch's creator, checkpointed under the
item's id, retried with backoff, dead-lettered when it keeps failing.

Item lifecycle
--------------
    pending ──top_up──▶ queued ──▶ running ──▶ completed | failed | paused (waiting at a human gate)
                                      └──▶ retrying ──▶ running …
    pending / queued / running / retrying ──cancel──▶ cancelled
    failed / cancelled ──retry_failed──▶ pending

Fair share: at most ``concurrency`` items of one batch are queued or running at a time, so a big
batch can't starve schedules and webhooks on the same workers. ``top_up`` queues the next pending
items whenever one finishes, and a periodic sweep (``batch.top_up``) does it too, so a chain lost
to a crash between finishing an item and queueing the next one picks up again. Claiming a pending
item is a conditional UPDATE, so no item is ever queued twice.

The batch is ``done`` once no item is pending, queued, running or retrying.

Documents as rows
-----------------
``create_from_documents`` takes uploaded files instead of a table: each file is saved under
``<data dir>/uploads/batches/<batch id>/`` and becomes a row ``{filename, path}``. The template can use
``{filename}``, ``{path}`` (for tools that load the file themselves, like Structured Extract) and
``{document}``, the file's text, read when its row runs with the loader for its type (PDF with OCR
for scanned pages, image OCR, email, Word, Excel, text — or Docling for PDFs and images). A file that
can't be read fails its row without a run. Each run knows its batch (``RunScope.batch``), so
Structured Extract files its fields in the review queue under the batch's name.
"""

import asyncio
import csv
import io
import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from db import get_db_connection
from paths import data_path
from services import jobs, scheduler

logger = logging.getLogger("pipesets-ai-backend")

JOB_KIND = "batch.run"
MAX_ROWS = 5000
MAX_CONCURRENCY = 10
DEFAULT_CONCURRENCY = 2
PREVIEW_ROWS = 20

ACTIVE = ("queued", "running", "retrying")
UNFINISHED = ("pending",) + ACTIVE
FINISHED = ("completed", "failed", "paused", "cancelled")

_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")

# Documents as rows
MAX_DOCUMENTS = 500
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
DEFAULT_DOCUMENT_CHARS = 100000   # {document} is cut here, so one huge file can't blow the model's context
DOCUMENT_COLUMNS = ["filename", "path"]
DOCUMENT_TEMPLATE = "{document}"
# file extension -> loader; "docling" instead reads PDFs and images with Docling (layout, tables)
EXT_LOADERS = {
    ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image", ".tif": "image", ".tiff": "image",
    ".bmp": "image", ".webp": "image", ".eml": "email", ".msg": "email", ".docx": "docx", ".xlsx": "excel",
    ".txt": "text", ".md": "text", ".csv": "text", ".json": "text", ".html": "text",
}
LOADER_CHOICES = ("auto", "docling")
OCR_ENGINES = ("auto", "tesseract", "ocrmypdf", "docling", "off")


class BatchError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── Input ─────────────────────────────────────────────────────────────────────

def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def parse_file(filename: str, content: bytes) -> Tuple[List[str], List[Dict[str, Any]]]:
    """(columns, rows) from a .csv / .tsv, .jsonl, .json (array of objects), .xlsx or .txt
    (one prompt per line, column ``prompt``)."""
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(it, [])]
        columns = [h or f"column_{i + 1}" for i, h in enumerate(header)]
        rows = [{c: _cell(v) for c, v in zip(columns, r)} for r in it if any(v not in (None, "") for v in r)]
        return columns, rows
    text = content.decode("utf-8-sig", errors="replace")
    if name.endswith(".jsonl") or name.endswith(".ndjson"):
        rows = []
        for n, line in enumerate(text.splitlines(), 1):
            if line.strip():
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise BatchError(422, f"Line {n} isn't valid JSON: {e.msg}")
                rows.append(obj if isinstance(obj, dict) else {"prompt": obj})
        return _columns(rows), [{k: _cell(v) for k, v in r.items()} for r in rows]
    if name.endswith(".json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise BatchError(422, f"Not valid JSON: {e.msg}")
        if not isinstance(data, list):
            raise BatchError(422, "A JSON file must hold an array of rows")
        rows = [r if isinstance(r, dict) else {"prompt": r} for r in data]
        return _columns(rows), [{k: _cell(v) for k, v in r.items()} for r in rows]
    if name.endswith(".csv") or name.endswith(".tsv"):
        reader = csv.DictReader(io.StringIO(text), delimiter="\t" if name.endswith(".tsv") else ",")
        raw = reader.fieldnames or []
        columns = [c.strip() or f"column_{i + 1}" for i, c in enumerate(raw)]
        rows = []
        for r in reader:
            row = {c: (r.get(k) or "") for k, c in zip(raw, columns)}
            if any(str(v).strip() for v in row.values()):
                rows.append(row)
        return columns, rows
    if name.endswith(".txt") or not name:
        return ["prompt"], [{"prompt": line.strip()} for line in text.splitlines() if line.strip()]
    raise BatchError(415, "Upload a .csv, .tsv, .jsonl, .json, .xlsx or .txt file")


def _columns(rows: List[Dict[str, Any]]) -> List[str]:
    seen: Dict[str, None] = {}
    for r in rows:
        for k in r:
            seen.setdefault(str(k), None)
    return list(seen)


def default_template(columns: List[str]) -> str:
    if "prompt" in columns:
        return "{prompt}"
    return f"{{{columns[0]}}}" if len(columns) == 1 else ""


def placeholders(template: str) -> List[str]:
    return [m.strip() for m in _PLACEHOLDER.findall(template)]


def render(template: str, row: Dict[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda m: str(row.get(m.group(1).strip(), "")), template).strip()


# ── Create ────────────────────────────────────────────────────────────────────

def _published_app(conn, app_id: str, tenant_id: str, project_id: str):
    app = conn.execute("SELECT id, name, version, status FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                       (app_id, tenant_id, project_id)).fetchone()
    if not app:
        raise BatchError(404, "Pipeline not found")
    if not app["version"]:
        raise BatchError(409, "Publish the pipeline before running a batch")
    return app


def create(tenant_id: str, project_id: str, user_id: str, app_id: str, rows: List[Dict[str, Any]],
           template: str = "", name: str = "", concurrency: int = DEFAULT_CONCURRENCY,
           retries: Optional[int] = None, timeout_ms: int = 120000,
           source: Optional[Dict[str, Any]] = None, batch_id: Optional[str] = None) -> Dict[str, Any]:
    """Record a batch and its items, queue the first ``concurrency`` of them; returns the batch."""
    source = source or {"kind": "rows"}
    documents = source.get("kind") == "documents"
    if not rows:
        raise BatchError(422, "The batch has no rows")
    if len(rows) > MAX_ROWS:
        raise BatchError(413, f"A batch can have at most {MAX_ROWS} rows (this one has {len(rows)})")
    columns = _columns(rows)
    template = (template or "").strip() or (DOCUMENT_TEMPLATE if documents else default_template(columns))
    if not template:
        raise BatchError(422, "Write a prompt template with {column} placeholders — the rows have several columns")
    known = columns + (["document"] if documents else [])
    missing = [p for p in placeholders(template) if p not in known]
    if missing:
        raise BatchError(422, f"No column named {', '.join(repr(m) for m in missing)} — columns: {', '.join(known)}")
    concurrency = max(1, min(int(concurrency or DEFAULT_CONCURRENCY), MAX_CONCURRENCY))
    retries = jobs.default_retries() if retries is None else max(-1, min(int(retries), jobs.MAX_RETRIES))

    batch_id = batch_id or new_batch_id()
    now = _now()
    conn = get_db_connection()
    try:
        app = _published_app(conn, app_id, tenant_id, project_id)
        conn.execute(
            "INSERT INTO batch_runs (id, tenant_id, project_id, app_id, name, prompt_template, columns, concurrency, "
            "retries, timeout_ms, status, total, created_by, created_at, updated_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)",
            (batch_id, tenant_id, project_id, app_id, (name or "").strip()[:200] or f"{app['name']} batch", template,
             json.dumps(columns), concurrency, retries, int(timeout_ms), len(rows), user_id, now, now,
             json.dumps(source)),
        )
        items = []
        names = placeholders(template)
        for i, row in enumerate(rows):
            # A document's text is read when its row runs; the stored prompt names it instead
            prompt = render(template, {**row, "document": f"‹text of {row.get('filename')}›"} if documents else row)
            # A row with nothing in its placeholders fails up front instead of costing a run
            blank = not prompt or (not documents and names and not any(str(row.get(n, "")).strip() for n in names))
            status, error = ("failed", "The prompt for this row is empty") if blank else ("pending", None)
            items.append((f"bi_{uuid.uuid4().hex}", batch_id, i, json.dumps(row, default=str), "" if blank else prompt,
                          status, error, now if blank else None))
        conn.executemany("INSERT INTO batch_items (id, batch_id, idx, input, prompt, status, error, finished_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", items)
        conn.commit()
    finally:
        conn.close()
    top_up(batch_id)
    return get(batch_id, tenant_id, project_id)


def new_batch_id() -> str:
    return f"batch_{uuid.uuid4().hex}"


def documents_dir(batch_id: str) -> str:
    return data_path("uploads", "batches", batch_id)


def _safe_filename(name: str, taken: set) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(name or "").strip()) or "document"
    stem, ext = os.path.splitext(base)
    out, n = base, 1
    while out.lower() in taken:
        n += 1
        out = f"{stem} ({n}){ext}"
    taken.add(out.lower())
    return out


def create_from_documents(tenant_id: str, project_id: str, user_id: str, app_id: str,
                          files: List[Tuple[str, bytes]], template: str = "", name: str = "",
                          concurrency: int = DEFAULT_CONCURRENCY, retries: Optional[int] = None,
                          timeout_ms: int = 120000, loader: str = "auto", ocr_engine: str = "auto",
                          max_chars: int = DEFAULT_DOCUMENT_CHARS) -> Dict[str, Any]:
    """A batch with one row per uploaded file (see the module docstring)."""
    if not files:
        raise BatchError(422, "Add at least one document")
    if len(files) > MAX_DOCUMENTS:
        raise BatchError(413, f"A batch can have at most {MAX_DOCUMENTS} documents (this one has {len(files)})")
    if loader not in LOADER_CHOICES:
        raise BatchError(422, f"Read documents with one of: {', '.join(LOADER_CHOICES)}")
    if ocr_engine not in OCR_ENGINES:
        raise BatchError(422, f"OCR engine must be one of: {', '.join(OCR_ENGINES)}")
    unsupported = sorted({os.path.splitext(f)[1].lower() or f for f, _ in files
                          if os.path.splitext(f)[1].lower() not in EXT_LOADERS})
    if unsupported:
        raise BatchError(415, f"Can't read {', '.join(unsupported)} files — use PDF, images, email, Word, Excel or text")
    too_big = [f for f, data in files if len(data) > MAX_DOCUMENT_BYTES]
    if too_big:
        raise BatchError(413, f"Larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB: {', '.join(too_big[:5])}")

    batch_id = new_batch_id()
    folder = documents_dir(batch_id)
    os.makedirs(folder, exist_ok=True)
    rows, taken = [], set()
    try:
        for filename, data in files:
            stored = _safe_filename(filename, taken)
            path = os.path.join(folder, stored)
            with open(path, "wb") as f:
                f.write(data)
            rows.append({"filename": os.path.basename(filename) or stored, "path": path})
        source = {"kind": "documents", "loader": loader, "ocr_engine": ocr_engine,
                  "max_chars": max(1000, min(int(max_chars or DEFAULT_DOCUMENT_CHARS), 1000000))}
        return create(tenant_id, project_id, user_id, app_id, rows, template, name, concurrency, retries,
                      timeout_ms, source=source, batch_id=batch_id)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)   # no batch, no files left behind
        raise


async def read_document(source: Dict[str, Any], path: str) -> str:
    """The text of one uploaded document, as its row's ``{document}``."""
    import loaders

    ext = os.path.splitext(path)[1].lower()
    loader = EXT_LOADERS.get(ext, "text")
    if source.get("loader") == "docling" and loader in ("pdf", "image"):
        loader = "docling"
    docs = await loaders.load_documents(loader, path, {"ocr_engine": source.get("ocr_engine") or "auto"})
    text = "\n\n".join((d.get("text") or "").strip() for d in docs if (d.get("text") or "").strip())
    limit = int(source.get("max_chars") or DEFAULT_DOCUMENT_CHARS)
    if len(text) > limit:
        text = text[:limit] + f"\n\n[… cut at {limit} characters]"
    return text


# ── Scheduling ────────────────────────────────────────────────────────────────

def dedupe_key(batch_id: str) -> str:
    return f"batch:{batch_id}"


def top_up(batch_id: str) -> int:
    """Queue pending items until ``concurrency`` are active; mark the batch done when nothing is
    left. Returns how many were queued."""
    conn = get_db_connection()
    queued = 0
    try:
        batch = conn.execute("SELECT * FROM batch_runs WHERE id = ?", (batch_id,)).fetchone()
        if not batch or batch["status"] != "running":
            return 0
        marks = ", ".join("?" for _ in ACTIVE)
        active = conn.execute(f"SELECT COUNT(*) AS n FROM batch_items WHERE batch_id = ? AND status IN ({marks})",
                              (batch_id, *ACTIVE)).fetchone()["n"]
        slots = int(batch["concurrency"]) - int(active)
        if slots > 0:
            pending = conn.execute("SELECT id FROM batch_items WHERE batch_id = ? AND status = 'pending' "
                                   "ORDER BY idx LIMIT ?", (batch_id, slots)).fetchall()
            for item in pending:
                if conn.execute("UPDATE batch_items SET status = 'queued' WHERE id = ? AND status = 'pending'",
                                (item["id"],)).rowcount != 1:
                    continue   # another process queued it
                job_id = jobs.enqueue(JOB_KIND, {"batch_id": batch_id, "item_id": item["id"]},
                                      tenant_id=batch["tenant_id"], project_id=batch["project_id"],
                                      dedupe_key=dedupe_key(batch_id),
                                      max_attempts=jobs.attempts_for(batch["retries"]), conn=conn)
                conn.execute("UPDATE batch_items SET job_id = ? WHERE id = ?", (job_id, item["id"]))
                queued += 1
        if not queued and not active:
            left = conn.execute("SELECT COUNT(*) AS n FROM batch_items WHERE batch_id = ? AND status = 'pending'",
                                (batch_id,)).fetchone()["n"]
            if not left:
                now = _now()
                conn.execute("UPDATE batch_runs SET status = 'done', finished_at = ?, updated_at = ? "
                             "WHERE id = ? AND status = 'running'", (now, now, batch_id))
        conn.commit()
    finally:
        conn.close()
    if queued:
        jobs.wake_workers()
    return queued


@jobs.periodic("batch.top_up", 60)
async def _sweep() -> None:
    """Keep every running batch moving, whatever happened to the job that should have topped it up."""
    conn = get_db_connection()
    try:
        ids = [r["id"] for r in conn.execute("SELECT id FROM batch_runs WHERE status = 'running'").fetchall()]
    finally:
        conn.close()
    for batch_id in ids:
        await asyncio.to_thread(top_up, batch_id)


# ── Execution ─────────────────────────────────────────────────────────────────

def _load(batch_id: str, item_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    conn = get_db_connection()
    try:
        batch = conn.execute("SELECT * FROM batch_runs WHERE id = ?", (batch_id,)).fetchone()
        item = conn.execute("SELECT * FROM batch_items WHERE id = ? AND batch_id = ?", (item_id, batch_id)).fetchone()
    finally:
        conn.close()
    return (dict(batch) if batch else None), (dict(item) if item else None)


def _source(batch: Dict[str, Any]) -> Dict[str, Any]:
    """The batch in the shape scheduler.run_published expects of a schedule / webhook."""
    return {"id": batch["id"], "app_id": batch["app_id"], "tenant_id": batch["tenant_id"],
            "project_id": batch["project_id"], "owner_user_id": batch["created_by"], "timeout_ms": batch["timeout_ms"],
            "batch_name": batch["name"]}


def _finish_item(item_id: str, version: int, res: Dict[str, Any], status: Optional[str] = None) -> None:
    meta = res.get("meta") or {}
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE batch_items SET status = ?, version = ?, run_id = ?, output = ?, error = ?, latency_ms = ?, "
            "cost_usd = ?, finished_at = ? WHERE id = ? AND status NOT IN ('completed', 'cancelled')",
            (status or res.get("status") or "failed", version, res.get("run_id") or None, res.get("output") or None,
             res.get("error"), int(res.get("latency_ms") or 0), float(meta.get("cost_usd") or 0.0), _now(), item_id),
        )
        conn.commit()
    finally:
        conn.close()


async def _on_dead(payload: Dict[str, Any], job: jobs.Job, error: str) -> None:
    batch, _ = await asyncio.to_thread(_load, payload["batch_id"], payload["item_id"])
    status = "cancelled" if batch and batch["status"] == "cancelled" else "failed"
    await asyncio.to_thread(_finish_item, payload["item_id"], 0, scheduler.crashed_result(error), status)
    await asyncio.to_thread(top_up, payload["batch_id"])


@jobs.handler(JOB_KIND, on_dead=_on_dead)
async def _run_job(payload: Dict[str, Any], job: jobs.Job) -> None:
    """One attempt at one row. Raises RunFailed when it should be retried, or — on the last
    attempt — after recording the failure, so the job ends up in the dead-letter view."""
    batch, item = await asyncio.to_thread(_load, payload["batch_id"], payload["item_id"])
    if batch is None or item is None or item["status"] in FINISHED:
        return   # deleted, cancelled or already done (a job may run twice)
    if batch["status"] == "cancelled":   # claimed just as the batch was cancelled
        await asyncio.to_thread(_finish_item, item["id"], 0, scheduler.crashed_result("Cancelled"), "cancelled")
        return
    prompt = item["prompt"]
    source = json.loads(batch.get("source") or "{}")
    if source.get("kind") == "documents":
        row = json.loads(item["input"] or "{}")
        try:
            text = await read_document(source, row["path"]) if "document" in placeholders(batch["prompt_template"]) else ""
        except Exception as e:   # unreadable: no retry would help, and no run is paid for
            await asyncio.to_thread(_finish_item, item["id"], 0, {"status": "failed", "output": "", "meta": {},
                                    "error": f"Couldn't read {row.get('filename')}: {e}"})
            await asyncio.to_thread(top_up, batch["id"])
            return
        prompt = render(batch["prompt_template"], {**row, "document": text})
    version, res = await scheduler.run_attempt("batch_items", _source(batch), item["id"], prompt, job)
    await asyncio.to_thread(_finish_item, item["id"], version, res)
    await asyncio.to_thread(top_up, batch["id"])
    if scheduler.retryable(res):
        raise scheduler.RunFailed(res.get("error") or "Run failed")


# ── Reading and managing ──────────────────────────────────────────────────────

def _counts(conn, batch_id: str) -> Dict[str, int]:
    counts = {s: 0 for s in UNFINISHED + FINISHED}
    for r in conn.execute("SELECT status, COUNT(*) AS n FROM batch_items WHERE batch_id = ? GROUP BY status", (batch_id,)):
        counts[r["status"]] = int(r["n"])
    return counts


def _public(conn, row: Any) -> Dict[str, Any]:
    d = dict(row)
    d["columns"] = json.loads(d.get("columns") or "[]")
    d["source"] = json.loads(d.get("source") or '{"kind": "rows"}')
    d["counts"] = _counts(conn, d["id"])
    d["finished"] = sum(d["counts"][s] for s in FINISHED)
    totals = conn.execute("SELECT SUM(cost_usd) AS cost, AVG(CASE WHEN status = 'completed' THEN latency_ms END) AS lat "
                          "FROM batch_items WHERE batch_id = ?", (d["id"],)).fetchone()
    d["cost_usd"] = round(float(totals["cost"] or 0.0), 6)
    d["avg_latency_ms"] = int(totals["lat"] or 0)
    app = conn.execute("SELECT name FROM apps WHERE id = ?", (d["app_id"],)).fetchone()
    d["app_name"] = app["name"] if app else ""
    return d


def get(batch_id: str, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM batch_runs WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (batch_id, tenant_id, project_id)).fetchone()
        return _public(conn, row) if row else None
    finally:
        conn.close()


def list_batches(tenant_id: str, project_id: str, app_id: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM batch_runs WHERE tenant_id = ? AND project_id = ?"
    params: List[Any] = [tenant_id, project_id]
    if app_id:
        sql += " AND app_id = ?"
        params.append(app_id)
    conn = get_db_connection()
    try:
        rows = conn.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*params, limit)).fetchall()
        return [_public(conn, r) for r in rows]
    finally:
        conn.close()


def _item(r: Any, preview: bool) -> Dict[str, Any]:
    d = {k: r[k] for k in ("id", "idx", "prompt", "status", "attempts", "run_id", "version", "output", "error",
                           "latency_ms", "cost_usd", "finished_at")}
    d["input"] = json.loads(r["input"] or "{}")
    if preview and d["output"] and len(d["output"]) > 2000:
        d["output"] = d["output"][:2000] + "…"
    return d


def items(batch_id: str, tenant_id: str, project_id: str, status: str = "", offset: int = 0,
          limit: int = 100, preview: bool = True) -> Optional[Dict[str, Any]]:
    if not get(batch_id, tenant_id, project_id):
        return None
    sql = "FROM batch_items WHERE batch_id = ?"
    params: List[Any] = [batch_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    conn = get_db_connection()
    try:
        total = conn.execute(f"SELECT COUNT(*) AS n {sql}", tuple(params)).fetchone()["n"]
        rows = conn.execute(f"SELECT * {sql} ORDER BY idx LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
    finally:
        conn.close()
    return {"total": int(total), "items": [_item(r, preview) for r in rows]}


def export_csv(batch_id: str, tenant_id: str, project_id: str) -> Optional[str]:
    """Every row: its input columns, then output, status, error, cost, latency, run id."""
    batch = get(batch_id, tenant_id, project_id)
    if not batch:
        return None
    res = items(batch_id, tenant_id, project_id, limit=MAX_ROWS, preview=False) or {"items": []}
    out = io.StringIO()
    extra = ["output", "status", "error", "cost_usd", "latency_ms", "run_id"]
    columns = [c for c in batch["columns"] if c not in extra]
    w = csv.writer(out)
    w.writerow(columns + extra)
    for it in res["items"]:
        w.writerow([it["input"].get(c, "") for c in columns] + [it.get(k) if it.get(k) is not None else "" for k in extra])
    return out.getvalue()


def cancel(batch_id: str, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    """Stop the batch: pending rows are cancelled now, queued and running ones as their jobs stop."""
    now = _now()
    conn = get_db_connection()
    try:
        cur = conn.execute("UPDATE batch_runs SET status = 'cancelled', finished_at = ?, updated_at = ? "
                           "WHERE id = ? AND tenant_id = ? AND project_id = ? AND status = 'running'",
                           (now, now, batch_id, tenant_id, project_id))
        if cur.rowcount != 1:
            conn.commit()
            return None
        conn.execute("UPDATE batch_items SET status = 'cancelled', finished_at = ? WHERE batch_id = ? AND status = 'pending'",
                     (now, batch_id))
        marks = ", ".join("?" for _ in ACTIVE)
        active = [r["job_id"] for r in conn.execute(
            f"SELECT job_id FROM batch_items WHERE batch_id = ? AND status IN ({marks}) AND job_id IS NOT NULL",
            (batch_id, *ACTIVE)).fetchall()]
        conn.commit()
    finally:
        conn.close()
    for job_id in active:
        try:
            buried = jobs.cancel(job_id, tenant_id, project_id, "Cancelled")
        except LookupError:
            continue   # finished meanwhile
        if buried:   # it was still queued: record it now (a running one is recorded by its worker)
            payload = buried.payload
            _finish_item(payload["item_id"], 0, scheduler.crashed_result("Cancelled"), "cancelled")
    return get(batch_id, tenant_id, project_id)


def retry_failed(batch_id: str, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    """Run failed and cancelled rows again (a cancelled batch starts running again)."""
    now = _now()
    conn = get_db_connection()
    try:
        batch = conn.execute("SELECT status FROM batch_runs WHERE id = ? AND tenant_id = ? AND project_id = ?",
                             (batch_id, tenant_id, project_id)).fetchone()
        if not batch:
            return None
        n = conn.execute("UPDATE batch_items SET status = 'pending', error = NULL, output = NULL, job_id = NULL, "
                         "attempts = 0, finished_at = NULL WHERE batch_id = ? AND status IN ('failed', 'cancelled') "
                         "AND prompt <> ''", (batch_id,)).rowcount
        if not n:
            conn.commit()
            raise BatchError(409, "No failed or cancelled rows to retry")
        conn.execute("UPDATE batch_runs SET status = 'running', finished_at = NULL, updated_at = ? WHERE id = ?",
                     (now, batch_id))
        conn.commit()
    finally:
        conn.close()
    top_up(batch_id)
    return get(batch_id, tenant_id, project_id)


def delete(batch_id: str, tenant_id: str, project_id: str) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT status FROM batch_runs WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (batch_id, tenant_id, project_id)).fetchone()
        if not row:
            return False
        if row["status"] == "running":
            raise BatchError(409, "Cancel the batch before deleting it")
        conn.execute("DELETE FROM batch_items WHERE batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM batch_runs WHERE id = ?", (batch_id,))
        conn.commit()
    finally:
        conn.close()
    shutil.rmtree(documents_dir(batch_id), ignore_errors=True)   # its uploaded documents, if any
    return True
