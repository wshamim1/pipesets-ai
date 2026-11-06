"""
batches.py — run a published pipeline once per input row (see services/batches.py).

GET    /api/batches                      — batches in the caller's tenant/project (?app_id=)
POST   /api/batches/parse                — read an uploaded file into columns + rows (nothing is saved)
POST   /api/batches                      — start a batch: pipeline, rows, prompt template, concurrency
POST   /api/batches/documents            — start a batch over uploaded documents, one row per file
                                           ({document} = its text, {filename}, {path})
GET    /api/batches/{batch_id}           — one batch with per-status counts, cost and average latency
GET    /api/batches/{batch_id}/items     — its rows (?status=&offset=&limit=)
GET    /api/batches/{batch_id}/export    — every row with its output, as CSV
POST   /api/batches/{batch_id}/cancel    — stop it: pending rows now, running ones within seconds
POST   /api/batches/{batch_id}/retry     — run the failed and cancelled rows again
DELETE /api/batches/{batch_id}           — delete a finished or cancelled batch
"""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from services import batches
from services.acl import require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/batches", tags=["batches"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class BatchCreate(BaseModel):
    app_id: str = Field(..., min_length=1)
    rows: List[Dict[str, Any]] = Field(..., min_length=1, max_length=batches.MAX_ROWS)
    prompt_template: str = Field(default="", max_length=20000,
                                 description="{column} placeholders; default {prompt}, or the only column")
    name: str = Field(default="", max_length=200)
    concurrency: int = Field(default=batches.DEFAULT_CONCURRENCY, ge=1, le=batches.MAX_CONCURRENCY)
    retries: Optional[int] = Field(default=None, ge=-1, le=10)
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)


def _ctx(request: Request, action: str):
    ctx = get_request_context(request)
    require_access(ctx, "apps", action)
    return ctx


def _or_404(value: Any, what: str = "Batch not found") -> Any:
    if value is None:
        raise HTTPException(status_code=404, detail=what)
    return value


@router.get("")
def list_batches(request: Request, app_id: str = "", limit: int = Query(default=50, ge=1, le=200)) -> List[Dict[str, Any]]:
    ctx = _ctx(request, "read")
    return batches.list_batches(ctx.tenant_id, ctx.project_id, app_id, limit)


@router.post("/parse")
async def parse(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    _ctx(request, "read")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 20 MB")
    try:
        columns, rows = batches.parse_file(file.filename or "", content)
    except batches.BatchError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Couldn't read the file: {e}")
    if not rows:
        raise HTTPException(status_code=422, detail="The file has no rows")
    if len(rows) > batches.MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"A batch can have at most {batches.MAX_ROWS} rows (this file has {len(rows)})")
    return {"columns": columns, "rows": rows, "total": len(rows),
            "prompt_template": batches.default_template(columns)}


@router.post("", status_code=201)
def create_batch(body: BatchCreate, request: Request) -> Dict[str, Any]:
    ctx = _ctx(request, "write")
    try:
        return batches.create(ctx.tenant_id, ctx.project_id, ctx.user_id, body.app_id, body.rows, body.prompt_template,
                              body.name, body.concurrency, body.retries, body.timeout_ms)
    except batches.BatchError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.post("/documents", status_code=201)
async def create_document_batch(
    request: Request,
    files: List[UploadFile] = File(...),
    app_id: str = Form(...),
    prompt_template: str = Form(default=""),
    name: str = Form(default=""),
    concurrency: int = Form(default=batches.DEFAULT_CONCURRENCY, ge=1, le=batches.MAX_CONCURRENCY),
    retries: Optional[int] = Form(default=None, ge=-1, le=10),
    timeout_ms: int = Form(default=120000, ge=1000, le=600000),
    loader: str = Form(default="auto"),
    ocr_engine: str = Form(default="auto"),
    max_chars: int = Form(default=batches.DEFAULT_DOCUMENT_CHARS, ge=1000, le=1000000),
) -> Dict[str, Any]:
    ctx = _ctx(request, "write")
    if len(files) > batches.MAX_DOCUMENTS:
        raise HTTPException(status_code=413, detail=f"A batch can have at most {batches.MAX_DOCUMENTS} documents")
    loaded = []
    for f in files:
        data = await f.read(batches.MAX_DOCUMENT_BYTES + 1)
        loaded.append((f.filename or "document", data))
    try:
        return await asyncio.to_thread(
            batches.create_from_documents, ctx.tenant_id, ctx.project_id, ctx.user_id, app_id, loaded,
            prompt_template, name, concurrency, retries, timeout_ms, loader, ocr_engine, max_chars)
    except batches.BatchError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.get("/{batch_id}")
def get_batch(batch_id: str, request: Request) -> Dict[str, Any]:
    ctx = _ctx(request, "read")
    return _or_404(batches.get(batch_id, ctx.tenant_id, ctx.project_id))


@router.get("/{batch_id}/items")
def list_items(batch_id: str, request: Request, status: str = "", offset: int = Query(default=0, ge=0),
               limit: int = Query(default=100, ge=1, le=500)) -> Dict[str, Any]:
    ctx = _ctx(request, "read")
    return _or_404(batches.items(batch_id, ctx.tenant_id, ctx.project_id, status, offset, limit))


@router.get("/{batch_id}/export")
def export_batch(batch_id: str, request: Request) -> Response:
    ctx = _ctx(request, "read")
    content = _or_404(batches.export_csv(batch_id, ctx.tenant_id, ctx.project_id))
    return Response(content=content.encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{batch_id}.csv"'})


@router.post("/{batch_id}/cancel")
def cancel_batch(batch_id: str, request: Request) -> Dict[str, Any]:
    ctx = _ctx(request, "write")
    return _or_404(batches.cancel(batch_id, ctx.tenant_id, ctx.project_id), "Batch not found or not running")


@router.post("/{batch_id}/retry")
def retry_batch(batch_id: str, request: Request) -> Dict[str, Any]:
    ctx = _ctx(request, "write")
    try:
        return _or_404(batches.retry_failed(batch_id, ctx.tenant_id, ctx.project_id))
    except batches.BatchError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.delete("/{batch_id}")
def delete_batch(batch_id: str, request: Request) -> Dict[str, Any]:
    ctx = _ctx(request, "write")
    try:
        _or_404(batches.delete(batch_id, ctx.tenant_id, ctx.project_id) or None)
    except batches.BatchError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return {"deleted": True, "id": batch_id}
