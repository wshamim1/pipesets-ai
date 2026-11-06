"""
audit.py — append-only log of admin actions (``audit_log`` table, migration 0010).

``AuditMiddleware`` records every request to a route in ``AUDITED`` once the response is sent:
who (the signed-in user), where (tenant / project), what (action name + target id), and how it
ended (``success`` for 2xx/3xx, ``denied`` for 403). Other failures (validation errors, 404s,
unauthenticated calls) are not recorded. Request bodies are never read or stored, so secret
values and keys can't end up in the log.

Recording at the route level instead of in each handler means a handler can't forget to
log; ``tests/security/test_audit_log.py`` fails when a new mutating route under an audited prefix is
neither in ``AUDITED`` nor in ``NOT_AUDITED``.

The target id is the route's path parameter (``/api/secrets/{secret_id}``) or, for a create,
the ``id`` in the JSON response.

Retention is the operator's call, not a tenant's: ``AUDIT_RETENTION_DAYS`` (default 365, 0 keeps
everything). A daily periodic loop (services/jobs.py, one process per day) purges older entries; each purge
leaves an ``audit.purge`` entry in every tenant it touched, so the trail shows when it was trimmed.
Exports (``audit.export``) are logged the same way.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional, Tuple

from db import get_db_connection
from services import jobs

log = logging.getLogger(__name__)

# (method, route template) → action name
AUDITED: Dict[Tuple[str, str], str] = {
    ("POST", "/api/api-keys"): "api_key.create",
    ("DELETE", "/api/api-keys/{key_id}"): "api_key.revoke",
    ("POST", "/api/secrets"): "secret.create",
    ("PUT", "/api/secrets/{secret_id}"): "secret.update",
    ("DELETE", "/api/secrets/{secret_id}"): "secret.delete",
    ("POST", "/api/iam/tenants"): "tenant.create",
    ("PUT", "/api/iam/tenants/{tenant_id}"): "tenant.update",
    ("DELETE", "/api/iam/tenants/{tenant_id}"): "tenant.delete",
    ("POST", "/api/iam/users"): "user.add",
    ("PUT", "/api/iam/users/{user_id}"): "user.update",
    ("DELETE", "/api/iam/users/{user_id}"): "user.remove",
    ("POST", "/api/iam/groups"): "group.create",
    ("PUT", "/api/iam/groups/{group_id}"): "group.update",
    ("DELETE", "/api/iam/groups/{group_id}"): "group.delete",
    ("POST", "/api/iam/groups/{group_id}/members"): "group.member_add",
    ("DELETE", "/api/iam/groups/{group_id}/members/{user_id}"): "group.member_remove",
    ("POST", "/api/iam/projects"): "project.create",
    ("PUT", "/api/iam/projects/{project_id}"): "project.update",
    ("DELETE", "/api/iam/projects/{project_id}"): "project.delete",
    ("POST", "/api/iam/acls"): "acl.create",
    ("PUT", "/api/iam/acls/{acl_id}"): "acl.update",
    ("DELETE", "/api/iam/acls/{acl_id}"): "acl.delete",
    ("POST", "/api/apps/{app_id}/publish"): "app.publish",
    ("POST", "/api/apps/{app_id}/edit"): "app.unpublish",
    ("PUT", "/api/apps/{app_id}/publish-gate"): "publish_gate.update",
    ("DELETE", "/api/apps/{app_id}/publish-gate"): "publish_gate.delete",
    ("DELETE", "/api/apps/{app_id}"): "app.delete",
    ("DELETE", "/api/apps"): "app.delete_all",
    ("PUT", "/api/llm-settings/{provider}"): "llm_settings.update",
    ("PUT", "/api/tools/packages"): "tool_package.update",
    ("DELETE", "/api/tools/packages"): "tool_package.reset",
    ("POST", "/api/tools/reload"): "tool_registry.reload",
    ("PUT", "/api/agent-catalog/packages"): "agent_package.update",
    ("DELETE", "/api/agent-catalog/packages"): "agent_package.reset",
    ("POST", "/api/saved-agents"): "saved_agent.create",
    ("PUT", "/api/saved-agents/{agent_id}"): "saved_agent.update",
    ("DELETE", "/api/saved-agents/{agent_id}"): "saved_agent.delete",
    ("DELETE", "/api/llm-settings/{provider}"): "llm_settings.reset",
    ("POST", "/api/llm-settings/migrate-litellm"): "llm_settings.migrate_litellm",
    ("POST", "/api/webhooks"): "webhook.create",
    ("PATCH", "/api/webhooks/{webhook_id}"): "webhook.update",
    ("DELETE", "/api/webhooks/{webhook_id}"): "webhook.delete",
    ("POST", "/api/webhooks/{webhook_id}/rotate"): "webhook.rotate_secret",
    ("POST", "/api/chat-links"): "chat_link.create",
    ("PATCH", "/api/chat-links/{link_id}"): "chat_link.update",
    ("POST", "/api/chat-links/{link_id}/rotate"): "chat_link.rotate",
    ("DELETE", "/api/chat-links/{link_id}"): "chat_link.revoke",
    ("POST", "/api/reviews/{review_id}/decision"): "review.decide",
    ("POST", "/api/reviews/export"): "review.export",
    ("POST", "/api/reviews/bulk-approve"): "review.bulk_approve",
    ("POST", "/api/notifications"): "channel.create",
    ("PATCH", "/api/notifications/{channel_id}"): "channel.update",
    ("DELETE", "/api/notifications/{channel_id}"): "channel.delete",
    ("POST", "/api/connections"): "connection.create",
    ("PUT", "/api/connections/{conn_id}"): "connection.update",
    ("DELETE", "/api/connections/{conn_id}"): "connection.delete",
    ("POST", "/api/custom-tools"): "custom_tool.create",
    ("PUT", "/api/custom-tools/{tool_id}"): "custom_tool.update",
    ("DELETE", "/api/custom-tools/{tool_id}"): "custom_tool.delete",
    ("POST", "/api/custom-tools/upload"): "custom_tool.upload",
    ("POST", "/api/custom-tools/{tool_id}/rollback"): "custom_tool.rollback",
    ("POST", "/api/custom-tools/{tool_id}/fork"): "custom_tool.fork",
    ("POST", "/api/custom-mcp"): "mcp_server.create",
    ("PUT", "/api/custom-mcp/{server_id}"): "mcp_server.update",
    ("DELETE", "/api/custom-mcp/{server_id}"): "mcp_server.delete",
    ("POST", "/api/custom-mcp/{server_id}/oauth/start"): "mcp_server.oauth_connect",
    ("DELETE", "/api/custom-mcp/{server_id}/oauth"): "mcp_server.oauth_disconnect",
    ("POST", "/api/marketplace/listings"): "listing.create",
    ("POST", "/api/marketplace/listings/{listing_id}/versions"): "listing.version_add",
    ("PUT", "/api/marketplace/listings/{listing_id}"): "listing.update",
    ("DELETE", "/api/marketplace/listings/{listing_id}"): "listing.delete",
    ("PUT", "/api/budgets"): "budget.update",
    ("DELETE", "/api/budgets/{budget_id}"): "budget.delete",
    ("POST", "/api/middleware"): "middleware.create",
    ("PUT", "/api/middleware/{mw_id}"): "middleware.update",
    ("DELETE", "/api/middleware/{mw_id}"): "middleware.delete",
    ("POST", "/api/schedules"): "schedule.create",
    ("PATCH", "/api/schedules/{schedule_id}"): "schedule.update",
    ("DELETE", "/api/schedules/{schedule_id}"): "schedule.delete",
    ("POST", "/api/system/database/setup"): "database.configure",
    ("PATCH", "/api/admin/users/{user_id}"): "admin.user_update",
    ("POST", "/api/admin/users/{user_id}/password"): "admin.user_password",
    ("POST", "/api/admin/users/{user_id}/sign-out"): "admin.user_sign_out",
    ("DELETE", "/api/admin/users/{user_id}"): "admin.user_delete",
    ("POST", "/api/admin/workspaces/{tenant_id}/join"): "admin.workspace_join",
    ("DELETE", "/api/admin/workspaces/{tenant_id}"): "admin.workspace_delete",
    ("POST", "/api/jobs/{job_id}/retry"): "job.retry",
    ("PUT", "/api/memory/long-term/settings"): "memory.settings",
    ("POST", "/api/memory/long-term/facts"): "memory.add_fact",
    ("DELETE", "/api/memory/long-term/facts/{fact_id}"): "memory.delete_fact",
    ("DELETE", "/api/memory/long-term/users/{user}"): "memory.forget_user",
    ("PUT", "/api/memory/store/entries"): "memory.store_put",
    ("DELETE", "/api/memory/store/entries"): "memory.store_delete",
    ("DELETE", "/api/memory/{session_id}"): "memory.clear_session",
    ("DELETE", "/api/memory/{session_id}/messages/{message_idx}"): "memory.delete_message",
    ("POST", "/api/jobs/{job_id}/cancel"): "job.cancel",
    ("DELETE", "/api/jobs/{job_id}"): "job.discard",
}

# Mutating routes under the audited prefixes that change nothing worth auditing: test calls,
# previews, executions and checks.
NOT_AUDITED = {
    ("POST", "/api/iam/access-check"),
    ("POST", "/api/llm-settings/{provider}/test"),
    ("POST", "/api/webhooks/{webhook_id}/test"),
    ("POST", "/api/notifications/{channel_id}/test"),
    ("POST", "/api/connections/test"),
    ("POST", "/api/connections/{conn_id}/test"),
    ("POST", "/api/custom-tools/{tool_id}/execute"),
    ("POST", "/api/custom-tools/execute-code"),
    ("POST", "/api/custom-tools/signature"),
    ("POST", "/api/custom-mcp/test"),
    ("POST", "/api/custom-mcp/{server_id}/discover"),
    ("POST", "/api/custom-mcp/{server_id}/execute"),
    ("POST", "/api/marketplace/listings/{listing_id}/try"),
    ("POST", "/api/marketplace/listings/{listing_id}/import"),
    ("POST", "/api/middleware/evaluate"),
    ("POST", "/api/schedules/preview"),
    ("POST", "/api/schedules/{schedule_id}/run"),
    ("POST", "/api/apps/{app_id}/publish-gate/check"),
    ("POST", "/api/system/database/test"),
    ("POST", "/api/memory/{session_id}/add"),
}

# Route prefixes whose mutating routes must each be in AUDITED or NOT_AUDITED
AUDITED_PREFIXES = ("/api/api-keys", "/api/secrets", "/api/iam", "/api/llm-settings", "/api/webhooks",
                    "/api/chat-links", "/api/reviews", "/api/notifications", "/api/connections", "/api/custom-tools", "/api/custom-mcp",
                    "/api/marketplace", "/api/budgets", "/api/middleware", "/api/schedules", "/api/system", "/api/admin",
                    "/api/jobs", "/api/memory")

# Written outside the route middleware: by this module, and by the MCP write tools (routers/v1_mcp.py),
# which record app.create / app.update / app.publish under the key's owner, naming the key in ``path``
SYSTEM_ACTIONS = ("audit.export", "audit.purge", "app.create", "app.update", "custom_tool.deploy",
                  "custom_tool.rollback")

MAX_CAPTURED_BODY = 64 * 1024
DEFAULT_RETENTION_DAYS = 365
PURGE_INTERVAL_SECONDS = 24 * 3600


def _now() -> str:
    return datetime.utcnow().isoformat()


def record(*, tenant_id: str, project_id: str, actor: str, action: str, target_id: str, outcome: str,
           status: int, method: str, path: str, ip: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO audit_log (id, tenant_id, project_id, actor, action, target_id, outcome, status, "
            "method, path, ip, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"aud_{uuid.uuid4().hex[:16]}", tenant_id, project_id, actor, action, target_id, outcome,
             status, method, path[:512], ip, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _filters(tenant_id: str, *, action: Optional[str] = None, actor: Optional[str] = None,
             outcome: Optional[str] = None, since: Optional[str] = None,
             until: Optional[str] = None) -> Tuple[str, List[Any]]:
    sql = "tenant_id = ?"
    args: List[Any] = [tenant_id]
    if action:
        sql += " AND action LIKE ?"
        args.append(action.replace("%", "") + "%")
    if actor:
        sql += " AND actor = ?"
        args.append(actor)
    if outcome:
        sql += " AND outcome = ?"
        args.append(outcome)
    if since:
        sql += " AND created_at >= ?"
        args.append(since)
    if until:
        sql += " AND created_at < ?"
        args.append(until)
    return sql, args


def list_entries(tenant_id: str, *, limit: int = 100, before: Optional[str] = None,
                 **filters: Optional[str]) -> List[Dict[str, Any]]:
    """Newest first. ``before`` is a created_at from a previous page; ``action`` matches a
    prefix ("secret." → every secret action); ``since`` / ``until`` are ISO times (UTC)."""
    where, args = _filters(tenant_id, **filters)
    if before:
        where += " AND created_at < ?"
        args.append(before)
    conn = get_db_connection()
    try:
        rows = conn.execute(f"SELECT * FROM audit_log WHERE {where} ORDER BY created_at DESC LIMIT ?",
                            tuple(args + [limit])).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def iter_entries(tenant_id: str, batch: int = 1000, **filters: Optional[str]) -> Iterator[Dict[str, Any]]:
    """Every matching entry, newest first, read in batches (for exports). Pages on
    (created_at, id), so entries sharing a timestamp are never skipped."""
    where, args = _filters(tenant_id, **filters)
    cursor: Optional[Tuple[str, str]] = None
    while True:
        sql, page_args = where, list(args)
        if cursor:
            sql += " AND (created_at < ? OR (created_at = ? AND id < ?))"
            page_args += [cursor[0], cursor[0], cursor[1]]
        conn = get_db_connection()
        try:
            rows = [dict(r) for r in conn.execute(
                f"SELECT * FROM audit_log WHERE {sql} ORDER BY created_at DESC, id DESC LIMIT ?",
                tuple(page_args + [batch])).fetchall()]
        finally:
            conn.close()
        yield from rows
        if len(rows) < batch:
            return
        cursor = (rows[-1]["created_at"], rows[-1]["id"])


# ── Retention ─────────────────────────────────────────────────────────────────

def retention_days() -> int:
    """Days entries are kept; 0 = forever. An unreadable value keeps the default."""
    raw = os.getenv("AUDIT_RETENTION_DAYS", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_RETENTION_DAYS
    except ValueError:
        log.warning("AUDIT_RETENTION_DAYS=%r is not a number; keeping %d days", raw, DEFAULT_RETENTION_DAYS)
        return DEFAULT_RETENTION_DAYS


def purge_expired(now: Optional[datetime] = None) -> Dict[str, int]:
    """Delete entries older than the retention period. Returns {tenant_id: entries deleted}."""
    days = retention_days()
    if not days:
        return {}
    cutoff = ((now or datetime.utcnow()) - timedelta(days=days)).isoformat()
    conn = get_db_connection()
    try:
        counts = {r["tenant_id"]: r["n"] for r in conn.execute(
            "SELECT tenant_id, COUNT(*) AS n FROM audit_log WHERE created_at < ? GROUP BY tenant_id",
            (cutoff,)).fetchall()}
        if counts:
            conn.execute("DELETE FROM audit_log WHERE created_at < ?", (cutoff,))
            conn.commit()
    finally:
        conn.close()
    for tenant_id, n in counts.items():
        record(tenant_id=tenant_id, project_id="", actor="system", action="audit.purge",
               target_id=f"{n} entries before {cutoff[:10]}", outcome="success", status=200,
               method="", path=f"retention {days} days", ip="")
    if counts:
        log.info("Audit log retention (%d days): deleted %d entries", days, sum(counts.values()))
    return counts


@jobs.periodic("audit.purge", PURGE_INTERVAL_SECONDS)
async def _purge() -> None:
    await asyncio.to_thread(purge_expired)


def _header(scope, name: bytes) -> str:
    for k, v in scope.get("headers") or []:
        if k == name:
            return v.decode("latin-1").strip()
    return ""


class AuditMiddleware:
    """Plain ASGI, so streamed responses pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)

        status = 0
        body = bytearray()

        async def capture(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and len(body) < MAX_CAPTURED_BODY:
                body.extend(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, capture)

        # Routing fills scope["route"] / ["path_params"] in place, so they're here now
        route = scope.get("route")
        action = AUDITED.get((scope["method"], getattr(route, "path", "")))
        if not action or not (200 <= status < 400 or status == 403):
            return
        try:
            await asyncio.to_thread(self._record, scope, action, status, bytes(body))
        except Exception:
            log.exception("Couldn't write audit log entry for %s", action)

    @staticmethod
    def _record(scope, action: str, status: int, body: bytes) -> None:
        state = scope.get("state") or {}
        ctx = state.get("ctx")
        params = scope.get("path_params") or {}
        actor = getattr(ctx, "user_id", None) or state.get("user_id") or ""
        tenant = (getattr(ctx, "tenant_id", None) or params.get("tenant_id")
                  or _header(scope, b"x-tenant-id"))
        project = getattr(ctx, "project_id", None) or _header(scope, b"x-project-id")
        # e.g. "grp_1/user_2" for a group member; a tenant route's own id when it has nothing else
        target = "/".join(str(v) for k, v in params.items() if k != "tenant_id") or params.get("tenant_id", "")
        if not target and status < 300:
            try:
                parsed = json.loads(body)
                target = str(parsed.get("id", "")) if isinstance(parsed, dict) else ""
            except ValueError:
                pass
        client = scope.get("client")
        record(tenant_id=tenant, project_id=project, actor=actor, action=action, target_id=target,
               outcome="denied" if status == 403 else "success", status=status, method=scope["method"],
               path=scope.get("path", ""), ip=client[0] if client else "")
