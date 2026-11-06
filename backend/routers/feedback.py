"""
feedback.py — 👍 / 👎 on runs (see services/feedback.py).

GET    /api/feedback                 — ratings in the caller's tenant/project
                                       (?app_id=&rating=1|-1&version=&source=&days=&limit=&offset=)
GET    /api/feedback/summary         — 👍 / 👎 and satisfaction per pipeline and version (?app_id=&days=)
GET    /api/feedback/runs/{run_id}   — the caller's own rating of a run (null when none)
PUT    /api/feedback/runs/{run_id}   — rate a run from the Prompt Runner (replaces an earlier rating)
DELETE /api/feedback/runs/{run_id}   — take the rating back
POST   /api/feedback/export          — ratings → cases in an eval dataset (new or existing)

Visitors on chat links rate through ``/v1/chat/{token}/feedback`` and API callers through
``/v1/runs/{run_id}/feedback``.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from services import feedback
from services.acl import require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class Rating(BaseModel):
    rating: int = Field(..., description="1 = 👍, -1 = 👎")
    comment: str = Field(default="", max_length=feedback.MAX_COMMENT)
    correction: str = Field(default="", max_length=feedback.MAX_CORRECTION,
                            description="what the answer should have been (becomes the eval case's expected output)")


class Export(BaseModel):
    feedback_ids: List[str] = Field(..., min_length=1, max_length=1000)
    dataset_id: str = ""
    dataset_name: str = Field(default="", max_length=200)


def _rate(ctx, run_id: str, source: str, rater: str, body: Rating) -> Dict[str, Any]:
    try:
        return feedback.rate(ctx.tenant_id, ctx.project_id, run_id, source, rater, body.rating,
                             body.comment, body.correction)
    except feedback.FeedbackError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.get("")
def list_feedback(request: Request, app_id: str = "", rating: Optional[int] = None, version: Optional[int] = None,
                  source: str = "", days: int = Query(default=0, ge=0, le=3650),
                  limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    return feedback.list_feedback(ctx.tenant_id, ctx.project_id, app_id, rating, version, source, days, limit, offset)


@router.get("/summary")
def feedback_summary(request: Request, app_id: str = "", days: int = Query(default=0, ge=0, le=3650)) -> List[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    return feedback.summary(ctx.tenant_id, ctx.project_id, app_id, days)


@router.get("/runs/{run_id}")
def my_rating(run_id: str, request: Request) -> Optional[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    return feedback.mine(ctx.tenant_id, ctx.project_id, run_id, ctx.user_id)


@router.put("/runs/{run_id}")
def rate_run(run_id: str, body: Rating, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    return _rate(ctx, run_id, "runner", ctx.user_id, body)


@router.delete("/runs/{run_id}")
def unrate_run(run_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    if not feedback.remove(ctx.tenant_id, ctx.project_id, run_id, ctx.user_id):
        raise HTTPException(status_code=404, detail="You haven't rated this run")
    return {"removed": True, "run_id": run_id}


@router.post("/export")
def export(body: Export, request: Request) -> Dict[str, Any]:
    from routers.eval import DatasetCreate, _insert_cases, new_dataset

    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    if not body.dataset_id and not body.dataset_name.strip():
        raise HTTPException(status_code=400, detail="Pick a dataset or name a new one")
    cases = feedback.to_cases(ctx.tenant_id, ctx.project_id, body.feedback_ids)
    if not cases:
        raise HTTPException(status_code=409, detail="None of these ratings has a run prompt to export")
    scope = (ctx.tenant_id, ctx.project_id)
    dataset_id = body.dataset_id or new_dataset(DatasetCreate(
        name=body.dataset_name.strip(),
        description="From user feedback: expected = the rater's correction, or the answer for a 👍"), scope)["id"]
    result = _insert_cases(dataset_id, cases, scope=scope)
    feedback.mark_exported(ctx.tenant_id, ctx.project_id, [c["feedback_id"] for c in cases], dataset_id)
    return {**result, "exported": len(cases)}
