"""
publish_gate.py — run a pipeline's eval dataset before it is published.

A pipeline can have one gate (``publish_gates`` table): an eval dataset, a scorer and the
bar the draft has to clear. ``POST /api/apps/{id}/publish`` runs the draft against the
dataset first and checks two rules:

* pass rate >= ``min_pass_rate``
* with ``no_regression``: pass rate >= the live version's pass rate - ``regression_tolerance``.
  The live version's rate is its latest eval run on the same dataset and scorer — the gate
  run that published it, or any later run of that version from the Lab.

In ``block`` mode a failing gate stops the publish (409) unless the caller forces it, which is
recorded on the version as ``overridden``. In ``warn`` mode the version publishes with
``warned``. The gate's eval run is re-labelled with the new version number, so it shows up in
the Lab's history and becomes the baseline for the next publish.
"""

from typing import Any, Dict, List, Optional

from db import get_db_connection
from services.pipeline_runner import RunScope

MODES = ("block", "warn")
SCORERS = ("exact", "contains", "llm_judge")


def get_gate(app_id: str, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT g.*, d.name AS dataset_name, "
            "(SELECT COUNT(*) FROM eval_cases c WHERE c.dataset_id = g.dataset_id) AS case_count "
            "FROM publish_gates g LEFT JOIN eval_datasets d ON d.id = g.dataset_id "
            "WHERE g.app_id = ? AND g.tenant_id = ? AND g.project_id = ?",
            (app_id, tenant_id, project_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    d["no_regression"] = bool(d["no_regression"])
    return d


def baseline(app_id: str, version: int, dataset_id: str, scorer: str) -> Optional[Dict[str, Any]]:
    """The live version's latest eval run on this dataset + scorer, if any."""
    if not version:
        return None
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, total, passed FROM eval_runs WHERE app_id = ? AND app_version = ? AND dataset_id = ? "
            "AND scorer = ? AND total > 0 ORDER BY created_at DESC",
            (app_id, version, dataset_id, scorer),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"eval_run_id": row["id"], "version": version, "pass_rate": row["passed"] / row["total"]}


def judge(gate: Dict[str, Any], run: Dict[str, Any], base: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply the gate's rules to an eval run. Pure — no I/O."""
    total, passed = run["total"], run["passed"]
    rate = passed / total if total else 0.0
    reasons: List[str] = []
    if rate + 1e-9 < gate["min_pass_rate"]:
        reasons.append(f"Pass rate {rate:.0%} is below the required {gate['min_pass_rate']:.0%}")
    if gate["no_regression"] and base and rate + 1e-9 < base["pass_rate"] - gate["regression_tolerance"]:
        tol = f" (tolerance {gate['regression_tolerance']:.0%})" if gate["regression_tolerance"] else ""
        reasons.append(f"Pass rate {rate:.0%} regressed from v{base['version']}'s {base['pass_rate']:.0%}{tol}")
    return {
        "status": "failed" if reasons else "passed",
        "mode": gate["mode"],
        "reasons": reasons,
        "pass_rate": round(rate, 4),
        "passed": passed,
        "total": total,
        "min_pass_rate": gate["min_pass_rate"],
        "baseline": base,
        "eval_run_id": run["id"],
        "dataset_id": gate["dataset_id"],
        "dataset_name": gate.get("dataset_name"),
        "scorer": gate["scorer"],
    }


async def check(app_id: str, live_version: int, gate: Dict[str, Any], scope: RunScope) -> Dict[str, Any]:
    """Run the gate's dataset against the draft and judge it. Raises LookupError / ValueError
    when the dataset is missing or empty — a gate that can't run is a failed gate."""
    from routers.eval import run_pipeline_eval   # lazy: routers import services

    run = await run_pipeline_eval(app_id, 0, gate["dataset_id"], gate["scorer"], scope, gate["timeout_ms"])
    return judge(gate, run, baseline(app_id, live_version, gate["dataset_id"], gate["scorer"]))


def label_run(eval_run_id: str, version: int) -> None:
    """Attach the gate's eval run (recorded against the draft, version 0) to the version it published."""
    conn = get_db_connection()
    try:
        conn.execute("UPDATE eval_runs SET app_version = ? WHERE id = ?", (version, eval_run_id))
        conn.commit()
    finally:
        conn.close()
