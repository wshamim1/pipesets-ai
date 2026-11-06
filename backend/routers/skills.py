"""
skills.py — Agent Skills: instructions an agent loads when a request needs them, with the tools they use.

A skill is
- ``name`` and ``when_to_use`` (stored as ``description``): all the model sees until it loads the
  skill — keep it under 300 characters, written as "when the user asks to…"
- ``instructions``: the body, returned when the model loads the skill (services/skills_runtime.py)
- ``required_tools`` (stored as ``tool_ids``): tools and MCP servers the skill uses. On an LLM node
  in on-demand mode, attached tools a skill lists stay hidden until that skill is loaded
- ``required_connections``: connection types its tools need (e.g. ``airflow``); informational for now
- ``version``: bumped on every save; ``skill_versions`` keeps each version's snapshot so a run can
  say which one it used and a Skill node can pin one

Built-in skills live in code, not the table, so no tenant can change them for everyone. The starter
skills cover the data-platform tool packages and are ``available`` once their tools are installed
(Settings → Tools & MCP packages). The first generic built-ins still load for flows that use them,
but aren't offered any more.

Endpoints
---------
GET    /api/skills                          — built-ins plus the project's skills
POST   /api/skills                          — create a skill (version 1)
GET    /api/skills/{id}                     — one skill
PUT    /api/skills/{id}                     — update it (next version)
DELETE /api/skills/{id}                     — delete it and its versions
GET    /api/skills/{id}/versions            — its versions, newest first
GET    /api/skills/{id}/versions/{version}  — the skill as it was at that version
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from db import get_db_connection
from models import SkillCreateRequest, SkillUpdateRequest, SkillResponse
from services.acl import require_access
from services.request_context import get_request_context

logger = logging.getLogger("pipesets-ai-backend")

router = APIRouter(prefix="/api/skills", tags=["skills"])

WHEN_TO_USE_MAX = 300


# ── Built-in skills ────────────────────────────────────────────────────────────

STARTER_SKILLS = [
    {
        "id": "skill_airflow_triage",
        "name": "Airflow DAG triage",
        "icon": "🌬️",
        "category": "data-platform",
        "tags": ["airflow", "on-call", "triage"],
        "description": "When the user asks why an Airflow DAG run failed, is stuck or didn't start, or wants a "
                       "failing pipeline diagnosed.",
        "instructions": (
            "You are triaging an Apache Airflow problem. Work from evidence, not guesses.\n"
            "1. Find the run: use `airflow` (action dag_runs) for the DAG's recent runs; note the failed or "
            "stuck run's id and start time. If the DAG isn't listed, check `airflow_import_errors` — a DAG "
            "that fails to import never runs.\n"
            "2. Find the task: use `airflow` (action task_instances) for that run and pick the first task in "
            "state failed / up_for_retry / upstream_failed.\n"
            "3. Read why: `airflow_task_logs` for that task and try number; quote the error lines.\n"
            "4. If many DAGs fail at once or nothing is scheduled, check `airflow_health` (scheduler, "
            "metadatabase, triggerer).\n"
            "5. Answer with: the failing task, the root cause in one sentence, the quoted error, and the "
            "next step (fix, clear and re-run, or who to page). Never trigger a DAG unless the user asks."
        ),
        "tool_ids": ["airflow", "airflow_task_logs", "airflow_import_errors", "airflow_health"],
        "required_connections": ["airflow"],
    },
    {
        "id": "skill_databricks_job_triage",
        "name": "Databricks job triage",
        "icon": "🧱",
        "category": "data-platform",
        "tags": ["databricks", "on-call", "triage"],
        "description": "When the user asks why a Databricks job or run failed, is slow, or its cluster didn't start.",
        "instructions": (
            "You are triaging a Databricks job. Work from evidence, not guesses.\n"
            "1. `databricks_job_status` / `databricks_job_runs` for the job: find the failed or slow run and "
            "its result state and state message.\n"
            "2. `databricks_job_logs` for that run: quote the exception or the last error lines.\n"
            "3. If the run never started or died with the cluster, check `databricks_cluster_events` "
            "(terminations, autoscaling, spot loss) and `databricks_cluster_logs` (driver errors, OOM).\n"
            "4. Answer with: the failing task, the root cause in one sentence, the quoted error, and the "
            "next step (code fix, cluster size / policy, retry). Don't start or cancel runs unless asked."
        ),
        "tool_ids": ["databricks_job_status", "databricks_job_runs", "databricks_job_logs",
                     "databricks_cluster_events", "databricks_cluster_logs"],
        "required_connections": ["databricks"],
    },
    {
        "id": "skill_snowflake_query_review",
        "name": "Snowflake slow or costly query review",
        "icon": "❄️",
        "category": "data-platform",
        "tags": ["snowflake", "cost", "performance"],
        "description": "When the user asks why Snowflake queries are slow or expensive, or which queries or "
                       "warehouses drive cost.",
        "instructions": (
            "You are reviewing Snowflake query performance and cost.\n"
            "1. `snowflake_query_history`: find the slow, failed or most expensive recent queries (duration, "
            "bytes scanned, warehouse, user).\n"
            "2. `snowflake_warehouses`: check the warehouse size, auto-suspend and whether it is oversized "
            "or always on.\n"
            "3. For a specific query, read its text and reason about full scans, missing filters on "
            "clustering keys, exploding joins and SELECT *; use `snowflake_reader` only for read-only "
            "checks (EXPLAIN, row counts).\n"
            "4. Answer with the top offenders, why each is slow or costly, and concrete fixes (rewrite, "
            "clustering, warehouse size / auto-suspend, result caching). Estimate savings when you can."
        ),
        "tool_ids": ["snowflake_query_history", "snowflake_warehouses", "snowflake_reader"],
        "required_connections": ["snowflake"],
    },
    {
        "id": "skill_kafka_lag",
        "name": "Kafka consumer lag investigation",
        "icon": "📨",
        "category": "data-platform",
        "tags": ["kafka", "on-call", "lag"],
        "description": "When the user asks why a Kafka consumer group is lagging, stuck or rebalancing, or a "
                       "connector stopped.",
        "instructions": (
            "You are investigating Kafka consumer lag.\n"
            "1. `kafka_consumer_lag` for the group: state (Stable / Rebalancing / Empty), total lag, and the "
            "worst partitions.\n"
            "2. `kafka_topics` for the topic: partition count versus the group's consumers — more consumers "
            "than partitions sit idle; one hot partition means key skew.\n"
            "3. If the consumer is a connector, `kafka_connectors`: failed tasks and their trace.\n"
            "4. Answer with: is lag growing or recovering, the likely cause (slow consumer, rebalancing "
            "loop, skew, failed task, producer burst) with the evidence, and the next step."
        ),
        "tool_ids": ["kafka_consumer_lag", "kafka_topics", "kafka_connectors"],
        "required_connections": ["kafka"],
    },
]

# The first built-ins: not offered any more, still loaded for flows and agents that use them
LEGACY_SKILLS = [
    {
        "id": "skill_data_analysis", "name": "Data Analysis & Statistics", "icon": "📊", "category": "analysis",
        "tags": ["statistics", "python", "data", "summary"],
        "description": "Analyze datasets, calculate statistical measures, summarize trends, and formulate analytical conclusions.",
        "instructions": (
            "You are a Senior Data Analyst.\n"
            "1. Clarify what metrics and statistical dimensions are relevant.\n"
            "2. When data is provided, perform systematic inspection (distribution, outliers, trends).\n"
            "3. Format outputs with markdown tables and bulleted key takeaways."
        ),
        "tool_ids": ["calculator", "custom_python_eval"],
    },
    {
        "id": "skill_code_reviewer", "name": "Code Review & Security Audit", "icon": "🛡️", "category": "engineering",
        "tags": ["code", "security", "best-practices", "refactoring"],
        "description": "Review code for performance bottlenecks, security vulnerabilities (OWASP top 10), and clean code standards.",
        "instructions": (
            "You are a Staff Software Engineer & Security Auditor.\n"
            "1. Review incoming code for correctness, performance, edge-cases, and security vulnerabilities.\n"
            "2. Provide specific line-by-line recommendations and improved code diffs.\n"
            "3. Rank findings by severity: Critical, High, Medium, Low, Info."
        ),
        "tool_ids": [],
    },
    {
        "id": "skill_research_synthesis", "name": "Deep Research & Synthesis", "icon": "🔬", "category": "research",
        "tags": ["research", "fact-checking", "synthesis", "citations"],
        "description": "Formulate search queries, cross-reference retrieved facts, and produce structured analytical reports.",
        "instructions": (
            "You are an Expert Research Specialist.\n"
            "1. Break ambiguous research questions into focused sub-queries.\n"
            "2. Cross-reference assertions against retrieved context.\n"
            "3. Cite sources explicitly and highlight any remaining uncertainties or contradictory data."
        ),
        "tool_ids": ["search_web", "wikipedia"],
    },
]

BUILTIN_SKILLS = STARTER_SKILLS   # offered in the list
_BUILTIN_BY_ID = {s["id"]: s for s in STARTER_SKILLS + LEGACY_SKILLS}
_BUILTIN_TS = "2026-01-01T00:00:00"


def _with_aliases(d: Dict[str, Any]) -> Dict[str, Any]:
    d["when_to_use"] = d.get("description") or ""
    d["required_tools"] = d.get("tool_ids") or []
    d.setdefault("required_connections", [])
    d.setdefault("version", 1)
    return d


def _builtin_dict(skill: Dict[str, Any], installed: Optional[set] = None) -> Dict[str, Any]:
    d = _with_aliases({**skill, "tenant_id": "*", "project_id": "*", "owner_user_id": "system",
                       "builtin": True, "created_at": _BUILTIN_TS, "updated_at": _BUILTIN_TS})
    d["available"] = installed is None or all(t in installed for t in d["required_tools"])
    return d


def _json_list(raw: Any) -> List[Any]:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    d["tool_ids"] = _json_list(d.get("tool_ids"))
    d["tags"] = _json_list(d.get("tags"))
    d["required_connections"] = _json_list(d.get("required_connections"))
    return _with_aliases(d)


def _own_row(conn, skill_id: str, tenant_id: str, project_id: str):
    return conn.execute(
        "SELECT * FROM skills WHERE id = ? AND tenant_id = ? AND project_id = ?",
        (skill_id, tenant_id, project_id),
    ).fetchone()


_SNAPSHOT_FIELDS = ("name", "icon", "description", "instructions", "tool_ids", "tags", "category", "required_connections")


def _snapshot(conn, skill: Dict[str, Any], author: str, now: str) -> None:
    conn.execute(
        "INSERT INTO skill_versions (skill_id, version, tenant_id, project_id, snapshot, author, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (skill["id"], skill["version"], skill["tenant_id"], skill["project_id"],
         json.dumps({k: skill.get(k) for k in _SNAPSHOT_FIELDS}), author, now),
    )


def load_skills(skill_ids: List[str], tenant_id: str, project_id: str,
                versions: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Built-ins plus the given project's own skills, in the order asked; unknown or foreign ids are
    skipped. ``versions`` pins a skill to an earlier version (its snapshot)."""
    versions = versions or {}
    found: Dict[str, Dict[str, Any]] = {i: _builtin_dict(_BUILTIN_BY_ID[i]) for i in skill_ids if i in _BUILTIN_BY_ID}
    custom = [i for i in skill_ids if i not in found]
    if custom:
        conn = get_db_connection()
        try:
            marks = ",".join("?" for _ in custom)
            rows = conn.execute(f"SELECT * FROM skills WHERE id IN ({marks}) AND tenant_id = ? AND project_id = ?",
                                (*custom, tenant_id, project_id)).fetchall()
            for r in rows:
                d = _row_to_dict(r)
                pinned = versions.get(d["id"])
                if pinned and pinned != d["version"]:
                    snap = conn.execute("SELECT snapshot FROM skill_versions WHERE skill_id = ? AND version = ? "
                                        "AND tenant_id = ? AND project_id = ?",
                                        (d["id"], pinned, tenant_id, project_id)).fetchone()
                    if snap:
                        d = _with_aliases({**d, **json.loads(snap["snapshot"]), "version": pinned})
                found[d["id"]] = d
        finally:
            conn.close()
    return [found[i] for i in skill_ids if i in found]


def _fields(req: Any, current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The stored fields from a create / update request; ``when_to_use`` / ``required_tools`` win
    over their older names ``description`` / ``tool_ids``."""
    cur = current or {}

    def pick(*names: str, default: Any = None) -> Any:
        for n in names:
            v = getattr(req, n, None)
            if v is not None:
                return v
        return cur.get(names[-1], default)

    out = {
        "name": str(pick("name", default="")).strip(),
        "icon": str(pick("icon", default="⚡")).strip() or "⚡",
        "description": str(pick("when_to_use", "description", default="")).strip(),
        "instructions": str(pick("instructions", default="")).strip(),
        "tool_ids": list(pick("required_tools", "tool_ids", default=[]) or []),
        "tags": list(pick("tags", default=[]) or []),
        "category": str(pick("category", default="general")).strip() or "general",
        "required_connections": list(pick("required_connections", default=[]) or []),
    }
    if len(out["description"]) > WHEN_TO_USE_MAX:
        raise HTTPException(status_code=422, detail=f"Keep “when to use” under {WHEN_TO_USE_MAX} characters: "
                                                    "it's what the model reads to decide whether to load the skill")
    return out


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", response_model=List[SkillResponse])
def list_skills(request: Request) -> List[Dict[str, Any]]:
    from services import tool_packages

    ctx = get_request_context(request)
    require_access(ctx, "skills", "read")
    installed = tool_packages.installed_ids(ctx.tenant_id)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM skills WHERE tenant_id = ? AND project_id = ? ORDER BY created_at DESC",
            (ctx.tenant_id, ctx.project_id),
        ).fetchall()
        return [_row_to_dict(r) for r in rows] + [_builtin_dict(s, installed) for s in BUILTIN_SKILLS]
    finally:
        conn.close()


@router.post("", response_model=SkillResponse)
def create_skill(req: SkillCreateRequest, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "skills", "create")
    f = _fields(req)
    skill_id = f"skill_custom_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO skills (id, tenant_id, project_id, owner_user_id, name, icon, description, instructions, "
            "tool_ids, tags, category, required_connections, version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (skill_id, ctx.tenant_id, ctx.project_id, ctx.user_id, f["name"], f["icon"], f["description"],
             f["instructions"], json.dumps(f["tool_ids"]), json.dumps(f["tags"]), f["category"],
             json.dumps(f["required_connections"]), now, now),
        )
        skill = _row_to_dict(_own_row(conn, skill_id, ctx.tenant_id, ctx.project_id))
        _snapshot(conn, skill, ctx.user_id, now)
        conn.commit()
        return skill
    finally:
        conn.close()


@router.get("/{skill_id}", response_model=SkillResponse)
def get_skill(skill_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "skills", "read")
    if skill_id in _BUILTIN_BY_ID:
        return _builtin_dict(_BUILTIN_BY_ID[skill_id])
    conn = get_db_connection()
    try:
        row = _own_row(conn, skill_id, ctx.tenant_id, ctx.project_id)
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        return _row_to_dict(row)
    finally:
        conn.close()


@router.put("/{skill_id}", response_model=SkillResponse)
def update_skill(skill_id: str, req: SkillUpdateRequest, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "skills", "update")
    if skill_id in _BUILTIN_BY_ID:
        raise HTTPException(status_code=403, detail="Built-in skills can't be changed; save a copy instead")
    conn = get_db_connection()
    try:
        row = _own_row(conn, skill_id, ctx.tenant_id, ctx.project_id)
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        current = _row_to_dict(row)
        f = _fields(req, current)
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE skills SET name = ?, icon = ?, description = ?, instructions = ?, tool_ids = ?, tags = ?, "
            "category = ?, required_connections = ?, version = version + 1, updated_at = ? "
            "WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (f["name"], f["icon"], f["description"], f["instructions"], json.dumps(f["tool_ids"]), json.dumps(f["tags"]),
             f["category"], json.dumps(f["required_connections"]), now, skill_id, ctx.tenant_id, ctx.project_id),
        )
        skill = _row_to_dict(_own_row(conn, skill_id, ctx.tenant_id, ctx.project_id))
        _snapshot(conn, skill, ctx.user_id, now)
        conn.commit()
        return skill
    finally:
        conn.close()


@router.delete("/{skill_id}")
def delete_skill(skill_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "skills", "delete")
    if skill_id in _BUILTIN_BY_ID:
        raise HTTPException(status_code=403, detail="Built-in skills can't be deleted")
    conn = get_db_connection()
    try:
        row = _own_row(conn, skill_id, ctx.tenant_id, ctx.project_id)
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        conn.execute("DELETE FROM skills WHERE id = ? AND tenant_id = ? AND project_id = ?",
                     (skill_id, ctx.tenant_id, ctx.project_id))
        conn.execute("DELETE FROM skill_versions WHERE skill_id = ? AND tenant_id = ? AND project_id = ?",
                     (skill_id, ctx.tenant_id, ctx.project_id))
        conn.commit()
        return {"success": True, "deleted_id": skill_id}
    finally:
        conn.close()


@router.get("/{skill_id}/versions")
def list_versions(skill_id: str, request: Request) -> List[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "skills", "read")
    if skill_id in _BUILTIN_BY_ID:
        return [{"version": 1, "author": "system", "created_at": _BUILTIN_TS}]
    conn = get_db_connection()
    try:
        if not _own_row(conn, skill_id, ctx.tenant_id, ctx.project_id):
            raise HTTPException(status_code=404, detail="Skill not found")
        rows = conn.execute("SELECT version, author, created_at FROM skill_versions WHERE skill_id = ? AND tenant_id = ? "
                            "AND project_id = ? ORDER BY version DESC", (skill_id, ctx.tenant_id, ctx.project_id)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{skill_id}/versions/{version}")
def get_version(skill_id: str, version: int, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "skills", "read")
    found = load_skills([skill_id], ctx.tenant_id, ctx.project_id, {skill_id: version})
    if not found or found[0]["version"] != version:
        raise HTTPException(status_code=404, detail="Skill version not found")
    return found[0]
