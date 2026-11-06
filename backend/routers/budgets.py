"""
Budgets API.

GET    /api/budgets        — all budgets with current spend / % used
PUT    /api/budgets        — create or update (keyed by scope + scope_id + period)
DELETE /api/budgets/{id}   — remove a budget
"""

from typing import Any, Dict, List, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from db import get_db_connection
from services.budget import list_budgets_with_spend, upsert_budget

router = APIRouter(tags=["budgets"])


class BudgetUpsert(BaseModel):
    scope: Literal["global", "app"] = "global"
    scope_id: str = Field(default="", description="app id when scope='app', else empty")
    period: Literal["daily", "monthly", "total"] = "monthly"
    limit_usd: float = Field(gt=0)
    action: Literal["block", "warn"] = "block"

    @model_validator(mode="after")
    def _check_scope(self):
        if self.scope == "app" and not self.scope_id:
            raise ValueError("scope_id is required when scope='app'")
        if self.scope == "global":
            self.scope_id = ""
        return self


@router.get("/api/budgets")
def get_budgets() -> List[Dict[str, Any]]:
    return list_budgets_with_spend()


@router.put("/api/budgets")
def put_budget(body: BudgetUpsert) -> Dict[str, Any]:
    budget_id = upsert_budget(body.scope, body.scope_id, body.period, body.limit_usd, body.action)
    return {"id": budget_id, **body.model_dump()}


@router.delete("/api/budgets/{budget_id}")
def delete_budget(budget_id: str) -> Dict[str, bool]:
    conn = get_db_connection()
    try:
        cur = conn.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Budget not found")
    finally:
        conn.close()
    return {"deleted": True}
