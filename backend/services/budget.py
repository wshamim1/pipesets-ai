"""
Spend budgets.

Spend is computed from the existing `traces` table (cost_usd), so there is no
second source of truth to drift. A budget is scoped to the whole deployment
("global") or a single app ("app") and covers a "daily", "monthly" or "total"
window (UTC). `action` is "block" (refuse real LLM calls once the limit is
reached) or "warn" (let the call through and surface a warning).

check_budget() is called by the run paths before any paid LLM call.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from db import get_db_connection


def _period_start(period: str) -> Optional[str]:
    now = datetime.utcnow()
    if period == "daily":
        return now.strftime("%Y-%m-%d")
    if period == "monthly":
        return now.strftime("%Y-%m-01")
    return None  # total


def spend_for(conn, scope: str, scope_id: str, period: str) -> float:
    sql = "SELECT COALESCE(SUM(cost_usd), 0) FROM traces WHERE 1=1"
    params: List[Any] = []
    if scope == "app":
        sql += " AND app_id = ?"
        params.append(scope_id)
    start = _period_start(period)
    if start:
        sql += " AND created_at >= ?"
        params.append(start)
    return float(conn.execute(sql, params).fetchone()[0] or 0.0)


def list_budgets_with_spend() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM budgets ORDER BY scope, scope_id, period").fetchall()
        out = []
        for r in rows:
            spent = spend_for(conn, r["scope"], r["scope_id"], r["period"])
            limit = float(r["limit_usd"])
            out.append({
                "id": r["id"],
                "scope": r["scope"],
                "scope_id": r["scope_id"],
                "period": r["period"],
                "limit_usd": limit,
                "action": r["action"],
                "spent_usd": round(spent, 6),
                "pct_used": round(spent / limit * 100, 1) if limit > 0 else 0.0,
                "exceeded": limit > 0 and spent >= limit,
            })
        return out
    finally:
        conn.close()


def check_budget(app_id: Optional[str]) -> Dict[str, Any]:
    """Return {"blocked": bool, "message": str|None, "warnings": [str]}."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM budgets WHERE scope = 'global' OR (scope = 'app' AND scope_id = ?)",
            (app_id or "",),
        ).fetchall()
        blocked_msg: Optional[str] = None
        warnings: List[str] = []
        for r in rows:
            limit = float(r["limit_usd"])
            if limit <= 0:
                continue
            spent = spend_for(conn, r["scope"], r["scope_id"], r["period"])
            if spent < limit:
                continue
            target = "global" if r["scope"] == "global" else f"app {r['scope_id']}"
            msg = f"{r['period']} budget for {target} reached: ${spent:.4f} of ${limit:.4f}"
            if r["action"] == "block":
                blocked_msg = blocked_msg or msg
            else:
                warnings.append(msg)
        return {"blocked": blocked_msg is not None, "message": blocked_msg, "warnings": warnings}
    finally:
        conn.close()


def upsert_budget(scope: str, scope_id: str, period: str, limit_usd: float, action: str) -> str:
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id FROM budgets WHERE scope = ? AND scope_id = ? AND period = ?",
            (scope, scope_id, period),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE budgets SET limit_usd = ?, action = ?, updated_at = ? WHERE id = ?",
                (limit_usd, action, now, row["id"]),
            )
            budget_id = row["id"]
        else:
            budget_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO budgets (id, scope, scope_id, period, limit_usd, action, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (budget_id, scope, scope_id, period, limit_usd, action, now, now),
            )
        conn.commit()
        return budget_id
    finally:
        conn.close()
