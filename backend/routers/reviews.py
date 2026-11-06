"""
reviews.py — the extraction review queue (see services/extraction_reviews.py).

GET  /api/reviews                       — reviews in the caller's tenant/project (?status=&source=&batch=)
GET  /api/reviews/report                — per-field accuracy by model and prompt version (?batch=)
GET  /api/reviews/bulk-approve          — how many pending fields bulk approval would approve (preview)
POST /api/reviews/bulk-approve          — approve pending fields with a found quote and confidence ≥ threshold
GET  /api/reviews/{review_id}           — one review
GET  /api/reviews/{review_id}/page      — the cited page's text (?page= one of its alternatives' pages)
POST /api/reviews/{review_id}/decision  — approve, correct (with the right value) or reject a field
POST /api/reviews/export                — reviewed documents → cases in an eval dataset (new or existing)

Decisions and exports are audited (services/audit.py): they're what a compliance record rests on.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services import extraction_reviews
from services.acl import require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class Decision(BaseModel):
    decision: str = Field(..., description="approve | correct | reject")
    value: Any = Field(default=None, description="the right value (correct)")
    note: str = Field(default="", max_length=2000)


class BulkApprove(BaseModel):
    min_confidence: float = Field(default=0.9, description="approve fields at or above this confidence")
    batch: str = ""
    source: str = ""


class Export(BaseModel):
    dataset_id: Optional[str] = Field(default=None, description="add to this dataset")
    dataset_name: str = Field(default="", max_length=200, description="or create one with this name")
    batch: str = ""
    only_complete: bool = Field(default=True, description="skip documents that still have pending fields")


@router.get("")
def list_reviews(request: Request, status: str = "", source: str = "", batch: str = "",
                 limit: int = 200, offset: int = 0) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    if status and status not in extraction_reviews.STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(extraction_reviews.STATUSES)}")
    return extraction_reviews.list_reviews(ctx.tenant_id, ctx.project_id, status, source, batch,
                                           max(1, min(limit, 1000)), max(0, offset))


@router.get("/report")
def report(request: Request, batch: str = "") -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    return extraction_reviews.report(ctx.tenant_id, ctx.project_id, batch)


@router.get("/bulk-approve")
def bulk_approve_preview(request: Request, min_confidence: float = 0.9, batch: str = "",
                         source: str = "") -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    try:
        return extraction_reviews.bulk_approve(ctx.tenant_id, ctx.project_id, min_confidence, ctx.user_id,
                                               batch, source, dry_run=True)
    except extraction_reviews.ReviewError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bulk-approve")
def bulk_approve(body: BulkApprove, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    try:
        return extraction_reviews.bulk_approve(ctx.tenant_id, ctx.project_id, body.min_confidence, ctx.user_id,
                                               body.batch, body.source)
    except extraction_reviews.ReviewError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{review_id}")
def get_review(review_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    item = extraction_reviews.get(ctx.tenant_id, ctx.project_id, review_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return item


@router.get("/{review_id}/page")
def get_page(review_id: str, request: Request, page: Optional[int] = None) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    try:
        item = extraction_reviews.page(ctx.tenant_id, ctx.project_id, review_id, page)
    except extraction_reviews.ReviewError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if item is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return item


@router.post("/{review_id}/decision")
def decide(review_id: str, body: Decision, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    try:
        item = extraction_reviews.decide(ctx.tenant_id, ctx.project_id, review_id, body.decision, ctx.user_id,
                                         body.value, body.note)
    except extraction_reviews.ReviewError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if item is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return item


@router.post("/export")
def export(body: Export, request: Request) -> Dict[str, Any]:
    from routers.eval import DatasetCreate, _insert_cases, new_dataset

    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    if not body.dataset_id and not body.dataset_name.strip():
        raise HTTPException(status_code=400, detail="Pick a dataset or name a new one")
    cases = extraction_reviews.export_cases(ctx.tenant_id, ctx.project_id, body.batch, body.only_complete)
    if not cases:
        raise HTTPException(status_code=409, detail="No reviewed documents to export yet")
    scope = (ctx.tenant_id, ctx.project_id)
    dataset_id = body.dataset_id or new_dataset(DatasetCreate(
        name=body.dataset_name.strip(),
        description="Reviewed extractions: input = document, expected = the reviewed fields as JSON"), scope)["id"]
    return {**_insert_cases(dataset_id, cases, scope=scope), "documents": len(cases)}
