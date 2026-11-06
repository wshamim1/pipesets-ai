"""
marketplace.py — publish pipelines for others, browse, try and import them.

GET    /api/marketplace/listings                 — browse (q, category, sort=popular|recent|name, mine=1)
GET    /api/marketplace/listings/{id}            — detail: versions, requirements, flow preview, bundled tool code
POST   /api/marketplace/listings                 — list one of your published apps          (marketplace:publish)
POST   /api/marketplace/listings/{id}/versions   — snapshot the source app again as vN+1    (marketplace:publish)
PUT    /api/marketplace/listings/{id}            — edit metadata, visibility, list/unlist   (marketplace:publish)
DELETE /api/marketplace/listings/{id}            — remove the listing (imported copies stay) (marketplace:publish)
POST   /api/marketplace/listings/{id}/try        — run a version without importing it
POST   /api/marketplace/listings/{id}/import     — copy a version into your project as a draft app (apps:write)
GET    /api/marketplace/imports                  — what this project imported, with update hints

Visibility: ``public`` listings are visible to every signed-in user; ``tenant`` listings
only to members of the publisher's tenant (an internal marketplace). Publishing and
managing happen from the publisher's tenant, with the ``marketplace:publish`` ACL
(tenant owners have it implicitly). Only published apps can be listed, and what gets
stored is a sanitised snapshot — see services/marketplace.py.
"""

import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_db_connection
from services import marketplace as mk
from services.acl import require_access
from services.pipeline_runner import ERROR_PREFIX, RunScope, current_scope, run_flow
from services.request_context import RequestContext, get_request_context

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])

Visibility = Literal["public", "tenant"]


class ListingCreate(BaseModel):
    app_id: str
    name: Optional[str] = Field(default=None, max_length=100)
    summary: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=10000)
    category: str = "general"
    tags: List[str] = Field(default_factory=list)
    visibility: Visibility = "public"
    changelog: str = Field(default="Initial release", max_length=2000)


class ListingUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    summary: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10000)
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    visibility: Optional[Visibility] = None
    status: Optional[Literal["listed", "unlisted"]] = None


class VersionCreate(BaseModel):
    changelog: str = Field(default="", max_length=2000)


class ImportRequest(BaseModel):
    version: Optional[int] = None
    name: Optional[str] = Field(default=None, max_length=100)


class TryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=20000)
    version: Optional[int] = None
    timeout_ms: int = Field(default=60000, ge=1000, le=180000)
    # provider -> key from the browser's key store; saved listings never hold keys
    provider_keys: Dict[str, str] = Field(default_factory=dict)


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_member(conn, tenant_id: str, user_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?", (tenant_id, user_id)
    ).fetchone() is not None


def _get_listing(conn, listing_id: str, ctx: RequestContext):
    """The listing if the caller may see it, else 404 (never reveals tenant listings)."""
    row = conn.execute("SELECT * FROM marketplace_listings WHERE id = ?", (listing_id,)).fetchone()
    if row:
        member = _is_member(conn, row["publisher_tenant_id"], ctx.user_id)
        if member or (row["status"] == "listed" and row["visibility"] == "public"):
            return row
    conn.close()
    raise HTTPException(status_code=404, detail="Listing not found")


def _require_manage(conn, row, ctx: RequestContext) -> None:
    if row["publisher_tenant_id"] != ctx.tenant_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Switch to the publishing tenant to manage this listing.")
    try:
        require_access(ctx, "marketplace", "publish")
    except HTTPException:
        conn.close()
        raise


def _get_version(conn, listing_id: str, version: Optional[int]):
    if version is None:
        row = conn.execute(
            "SELECT * FROM marketplace_versions WHERE listing_id = ? ORDER BY version DESC LIMIT 1", (listing_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM marketplace_versions WHERE listing_id = ? AND version = ?", (listing_id, version)
        ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Version not found")
    return row


def _validate_category(category: str) -> str:
    if category not in mk.CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of: {', '.join(mk.CATEGORIES)}")
    return category


def _listing_dict(conn, row, ctx: RequestContext, version_row=None) -> Dict[str, Any]:
    v = version_row or conn.execute(
        "SELECT * FROM marketplace_versions WHERE listing_id = ? AND version = ?", (row["id"], row["latest_version"])
    ).fetchone()
    flow = json.loads(v["flow_data"]) if v else {"nodes": [], "edges": []}
    requirements = json.loads(v["requirements"]) if v else []
    bundled = json.loads(v["bundled_tools"]) if v else []
    tryable, try_reason = mk.can_try(requirements, bundled)
    tenant = conn.execute("SELECT name FROM tenants WHERE id = ?", (row["publisher_tenant_id"],)).fetchone()
    user = conn.execute("SELECT display_name FROM users WHERE id = ?", (row["publisher_user_id"],)).fetchone()
    return {
        "id": row["id"],
        "name": row["name"],
        "summary": row["summary"],
        "description": row["description"],
        "category": row["category"],
        "tags": json.loads(row["tags"] or "[]"),
        "visibility": row["visibility"],
        "status": row["status"],
        "latest_version": row["latest_version"],
        "import_count": row["import_count"],
        "try_count": row["try_count"],
        "publisher": {
            "tenant_id": row["publisher_tenant_id"],
            "tenant_name": tenant["name"] if tenant else "",
            "user_name": user["display_name"] if user else "",
        },
        "is_mine": row["publisher_tenant_id"] == ctx.tenant_id,
        "source_app_id": row["source_app_id"] if row["publisher_tenant_id"] == ctx.tenant_id else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        **mk.node_summary(flow),
        "requirements": requirements,
        "bundled_tool_names": [t["name"] for t in bundled],
        "can_try": tryable,
        "try_blocked_reason": try_reason,
    }


def _snapshot_source(conn, ctx: RequestContext, app_id: str):
    app = conn.execute(
        "SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id)
    ).fetchone()
    if not app:
        conn.close()
        raise HTTPException(status_code=404, detail="App not found in your current project")
    if app["status"] != "published":
        conn.close()
        raise HTTPException(status_code=409, detail="Publish the app first — only published versions can go to the marketplace.")
    try:
        flow = json.loads(app["flow_data"] or "{}")
        sanitized, requirements, bundled = mk.prepare_snapshot(conn, flow, ctx.tenant_id, ctx.project_id)
    except HTTPException:
        conn.close()
        raise
    if not mk.node_summary(sanitized)["runnable"]:
        conn.close()
        raise HTTPException(status_code=400, detail="The pipeline needs an LLM or Master Agent node to be useful to others.")
    return app, sanitized, requirements, bundled


def _insert_version(conn, listing_id: str, version: int, app, flow, requirements, bundled, changelog: str, now: str):
    conn.execute(
        "INSERT INTO marketplace_versions (listing_id, version, source_app_version, flow_data, requirements, "
        "bundled_tools, changelog, docs, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (listing_id, version, app["version"] or 0, json.dumps(flow), json.dumps(requirements),
         json.dumps(bundled), changelog.strip(), app["docs"] or "", now),
    )


# ── browse ────────────────────────────────────────────────────────────────────

@router.get("/listings")
def list_listings(request: Request, q: str = "", category: str = "", sort: str = "popular", mine: bool = False):
    ctx = get_request_context(request)
    where = ["(l.visibility = 'public' AND l.status = 'listed'"
             " OR l.publisher_tenant_id IN (SELECT tenant_id FROM tenant_memberships WHERE user_id = ?))"]
    params: List[Any] = [ctx.user_id]
    if mine:
        where.append("l.publisher_tenant_id = ?")
        params.append(ctx.tenant_id)
    else:
        where.append("l.status = 'listed'")
    if category:
        where.append("l.category = ?")
        params.append(category)
    if q.strip():
        where.append("(l.name LIKE ? OR l.summary LIKE ? OR l.tags LIKE ?)")
        like = f"%{q.strip()}%"
        params += [like, like, like]
    order = {"recent": "l.updated_at DESC", "name": "l.name COLLATE NOCASE ASC"}.get(
        sort, "l.import_count DESC, l.try_count DESC, l.updated_at DESC")
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT l.* FROM marketplace_listings l WHERE {' AND '.join(where)} ORDER BY {order} LIMIT 200", params
        ).fetchall()
        listings = [_listing_dict(conn, r, ctx) for r in rows]
    finally:
        conn.close()
    return {"listings": listings, "categories": list(mk.CATEGORIES)}


@router.get("/listings/{listing_id}")
def get_listing(listing_id: str, request: Request, version: Optional[int] = None):
    ctx = get_request_context(request)
    conn = get_db_connection()
    row = _get_listing(conn, listing_id, ctx)
    v = _get_version(conn, listing_id, version)
    detail = _listing_dict(conn, row, ctx, v)
    versions = conn.execute(
        "SELECT version, changelog, created_at, source_app_version FROM marketplace_versions "
        "WHERE listing_id = ? ORDER BY version DESC", (listing_id,)
    ).fetchall()
    conn.close()
    return {
        **detail,
        "version": v["version"],
        "versions": [dict(r) for r in versions],
        # Safe to show: secrets and tenant-private references were stripped at publish time
        "flow_data": json.loads(v["flow_data"]),
        "bundled_tools": json.loads(v["bundled_tools"]),
        "docs": v["docs"] or "",
    }


# ── publish / manage ──────────────────────────────────────────────────────────

@router.post("/listings", status_code=201)
def create_listing(req: ListingCreate, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "marketplace", "publish")
    category = _validate_category(req.category)
    conn = get_db_connection()
    if conn.execute("SELECT 1 FROM marketplace_listings WHERE source_app_id = ?", (req.app_id,)).fetchone():
        conn.close()
        raise HTTPException(status_code=409, detail="This app is already listed. Publish a new version of its listing instead.")
    app, flow, requirements, bundled = _snapshot_source(conn, ctx, req.app_id)

    listing_id = f"mkt_{uuid.uuid4().hex[:10]}"
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO marketplace_listings (id, publisher_tenant_id, publisher_project_id, publisher_user_id, "
        "source_app_id, name, summary, description, category, tags, visibility, status, latest_version, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'listed', 1, ?, ?)",
        (listing_id, ctx.tenant_id, ctx.project_id, ctx.user_id, req.app_id,
         (req.name or app["name"]).strip(), req.summary.strip(),
         (req.description or app["description"] or "").strip(), category,
         json.dumps(mk.parse_tags(req.tags)), req.visibility, now, now),
    )
    _insert_version(conn, listing_id, 1, app, flow, requirements, bundled, req.changelog, now)
    conn.commit()
    row = conn.execute("SELECT * FROM marketplace_listings WHERE id = ?", (listing_id,)).fetchone()
    result = _listing_dict(conn, row, ctx)
    conn.close()
    return result


@router.post("/listings/{listing_id}/versions", status_code=201)
def publish_version(listing_id: str, req: VersionCreate, request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    row = _get_listing(conn, listing_id, ctx)
    _require_manage(conn, row, ctx)
    if row["publisher_project_id"] != ctx.project_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Switch to the project the listing was published from.")
    app, flow, requirements, bundled = _snapshot_source(conn, ctx, row["source_app_id"])
    latest = conn.execute(
        "SELECT source_app_version FROM marketplace_versions WHERE listing_id = ? AND version = ?",
        (listing_id, row["latest_version"]),
    ).fetchone()
    if latest and latest["source_app_version"] == (app["version"] or 0):
        conn.close()
        raise HTTPException(status_code=409, detail=(
            f"v{app['version']} of the app is already listed. Edit and re-publish the app, then publish a new version."))

    version = row["latest_version"] + 1
    now = datetime.utcnow().isoformat()
    _insert_version(conn, listing_id, version, app, flow, requirements, bundled, req.changelog, now)
    conn.execute("UPDATE marketplace_listings SET latest_version = ?, updated_at = ? WHERE id = ?",
                 (version, now, listing_id))
    conn.commit()
    row = conn.execute("SELECT * FROM marketplace_listings WHERE id = ?", (listing_id,)).fetchone()
    result = _listing_dict(conn, row, ctx)
    conn.close()
    return result


@router.put("/listings/{listing_id}")
def update_listing(listing_id: str, req: ListingUpdate, request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    row = _get_listing(conn, listing_id, ctx)
    _require_manage(conn, row, ctx)
    fields: Dict[str, Any] = {}
    if req.name is not None:
        if not req.name.strip():
            conn.close()
            raise HTTPException(status_code=400, detail="Name can't be empty")
        fields["name"] = req.name.strip()
    if req.summary is not None:
        fields["summary"] = req.summary.strip()
    if req.description is not None:
        fields["description"] = req.description.strip()
    if req.category is not None:
        fields["category"] = _validate_category(req.category)
    if req.tags is not None:
        fields["tags"] = json.dumps(mk.parse_tags(req.tags))
    if req.visibility is not None:
        fields["visibility"] = req.visibility
    if req.status is not None:
        fields["status"] = req.status
    if fields:
        fields["updated_at"] = datetime.utcnow().isoformat()
        conn.execute(
            f"UPDATE marketplace_listings SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            (*fields.values(), listing_id),
        )
        conn.commit()
    row = conn.execute("SELECT * FROM marketplace_listings WHERE id = ?", (listing_id,)).fetchone()
    result = _listing_dict(conn, row, ctx)
    conn.close()
    return result


@router.delete("/listings/{listing_id}")
def delete_listing(listing_id: str, request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    row = _get_listing(conn, listing_id, ctx)
    _require_manage(conn, row, ctx)
    conn.execute("DELETE FROM marketplace_versions WHERE listing_id = ?", (listing_id,))
    conn.execute("DELETE FROM marketplace_listings WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()
    return {"deleted": True, "id": listing_id}


# ── try / import ──────────────────────────────────────────────────────────────

@router.post("/listings/{listing_id}/try")
async def try_listing(listing_id: str, req: TryRequest, request: Request):
    """Run a listing in the caller's scope without saving anything."""
    ctx = get_request_context(request)
    conn = get_db_connection()
    row = _get_listing(conn, listing_id, ctx)
    v = _get_version(conn, listing_id, req.version)
    requirements = json.loads(v["requirements"])
    tryable, reason = mk.can_try(requirements, json.loads(v["bundled_tools"]))
    if not tryable:
        conn.close()
        raise HTTPException(status_code=409, detail=f"This pipeline can't be tried without importing. {reason}")

    keys = {k.lower(): val for k, val in req.provider_keys.items() if val}
    # Trial runs come from any signed-in user, so they don't spend the server's own
    # provider keys unless the operator opts in.
    if os.getenv("MARKETPLACE_TRY_SERVER_KEYS", "0") != "1":
        missing = sorted({r["provider"] for r in requirements if r["kind"] == "provider_key"} - set(keys))
        if missing:
            conn.close()
            raise HTTPException(status_code=400, detail=(
                f"Add your own {', '.join(missing)} API key (top bar → API keys) to try this pipeline."))
    conn.execute("UPDATE marketplace_listings SET try_count = try_count + 1 WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()

    flow = mk.fresh_session_ids(json.loads(v["flow_data"]))
    token = current_scope.set(RunScope(tenant_id=ctx.tenant_id, project_id=ctx.project_id,
                                       user_id=ctx.user_id, provider_keys=keys))
    t0 = time.monotonic()
    try:
        output, telemetry = await run_flow(f"market:{listing_id}", row["name"], flow, req.prompt.strip(), "", req.timeout_ms)
    finally:
        current_scope.reset(token)
    failed = output.startswith(ERROR_PREFIX)
    return {
        "ok": not failed,
        "listing": row["name"],
        "version": v["version"],
        "output": output,
        "error": output if failed else None,
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "provider": telemetry.get("effective_provider", ""),
    }


@router.post("/listings/{listing_id}/import", status_code=201)
def import_listing(listing_id: str, req: ImportRequest, request: Request):
    """Copy a listing version into the caller's current project as a draft app."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    conn = get_db_connection()
    row = _get_listing(conn, listing_id, ctx)
    v = _get_version(conn, listing_id, req.version)
    bundled = json.loads(v["bundled_tools"])
    if bundled:
        try:
            require_access(ctx, "tools", "write")
        except HTTPException:
            conn.close()
            raise HTTPException(status_code=403, detail="This pipeline brings custom tools; you need tools:write to import it.")

    flow, created_tools = mk.materialize_import(conn, json.loads(v["flow_data"]), bundled,
                                                ctx.tenant_id, ctx.project_id, ctx.user_id)
    app_id = f"app-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()
    name = (req.name or row["name"]).strip()
    description = (row["summary"] or row["description"] or "").strip()
    conn.execute(
        "INSERT INTO apps (id, tenant_id, project_id, owner_user_id, name, description, flow_data, status, version, "
        "docs, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', 0, ?, ?, ?)",
        (app_id, ctx.tenant_id, ctx.project_id, ctx.user_id, name,
         f"{description}\n\nImported from the marketplace: {row['name']} v{v['version']}".strip(),
         json.dumps(flow), v["docs"] or "", now, now),
    )
    conn.execute(
        "INSERT INTO marketplace_imports (id, listing_id, version, tenant_id, project_id, user_id, app_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (f"imp_{uuid.uuid4().hex[:10]}", listing_id, v["version"], ctx.tenant_id, ctx.project_id, ctx.user_id, app_id, now),
    )
    conn.execute("UPDATE marketplace_listings SET import_count = import_count + 1 WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()
    return {
        "app_id": app_id,
        "name": name,
        "version": v["version"],
        "created_tools": created_tools,
        "requirements": json.loads(v["requirements"]),
        "next_steps": "Open the app, complete the requirements, then publish it in your project to run it.",
    }


@router.get("/imports")
def list_imports(request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT i.listing_id, i.version, i.app_id, i.created_at,
               l.name AS listing_name, l.latest_version, a.name AS app_name
        FROM marketplace_imports i
        LEFT JOIN marketplace_listings l ON l.id = i.listing_id
        LEFT JOIN apps a ON a.id = i.app_id
        WHERE i.tenant_id = ? AND i.project_id = ?
        ORDER BY i.created_at DESC
        """,
        (ctx.tenant_id, ctx.project_id),
    ).fetchall()
    conn.close()
    return {"imports": [{
        **dict(r),
        "app_exists": r["app_name"] is not None,
        "listing_exists": r["listing_name"] is not None,
        "update_available": r["latest_version"] is not None and r["latest_version"] > r["version"],
    } for r in rows]}
