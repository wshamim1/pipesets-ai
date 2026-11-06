"""Baseline schema (everything db.init_db() used to create with raw SQLite DDL).

On a fresh database this creates every table and index. On a SQLite database made by the
old init_db() (no alembic_version table yet) it adds whatever columns/indexes are missing
and runs the two old one-off data fixes, then Alembic records this revision as applied.

Types are chosen to work on SQLite, Postgres and SQL Server: ids, enums, timestamps and
anything indexed are bounded Unicode (SQL Server cannot index NVARCHAR(MAX)); the rest is
UnicodeText.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-25
"""
from alembic import context, op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)   # ids, foreign keys, short enums, anything indexed
TS = sa.Unicode(64)     # ISO-8601 timestamps (stored as text, as before)
TXT = sa.UnicodeText    # free text / JSON


def col(name, type_, default=None, nullable=False, foreign_key=None, **kw):
    if isinstance(default, (int, float)):
        default = sa.text(str(default))
    args = (foreign_key,) if foreign_key is not None else ()
    return sa.Column(name, type_, *args, nullable=nullable, server_default=default, **kw)


def fk(target, ondelete="CASCADE"):
    return sa.ForeignKey(target, ondelete=ondelete)


SCOPE = [  # tenant_id / project_id / owner_user_id columns shared by the scoped resources
    lambda: col("tenant_id", KEY, "tenant_demo"),
    lambda: col("project_id", KEY, "proj_research"),
    lambda: col("owner_user_id", KEY, "user_admin"),
]

metadata = sa.MetaData()

# ── Tenant / IAM foundation ─────────────────────────────────────────────────
sa.Table(
    "tenants", metadata,
    col("id", KEY, primary_key=True),
    col("name", TXT),
    col("slug", KEY, unique=True),
    col("status", KEY, "active"),
    col("created_at", TS),
    col("updated_at", TS),
)
sa.Table(
    "users", metadata,
    col("id", KEY, primary_key=True),
    col("email", sa.Unicode(255), unique=True),
    col("display_name", TXT),
    col("status", KEY, "active"),
    col("created_at", TS),
    col("updated_at", TS),
    col("password_hash", TXT, nullable=True),
)
sa.Table(
    "tenant_memberships", metadata,
    col("tenant_id", KEY, foreign_key=fk("tenants.id"), primary_key=True),
    col("user_id", KEY, foreign_key=fk("users.id"), primary_key=True),
    col("role", KEY, "viewer"),
    col("created_at", TS),
)
sa.Table(
    "groups", metadata,
    col("id", KEY, primary_key=True),
    col("tenant_id", KEY, foreign_key=fk("tenants.id")),
    col("name", TXT),
    col("description", TXT, ""),
    col("created_at", TS),
    col("updated_at", TS),
)
sa.Table(
    "group_memberships", metadata,
    col("group_id", KEY, foreign_key=fk("groups.id"), primary_key=True),
    col("user_id", KEY, foreign_key=fk("users.id"), primary_key=True),
    col("tenant_id", KEY, foreign_key=fk("tenants.id")),
    col("created_at", TS),
)
sa.Table(
    "projects", metadata,
    col("id", KEY, primary_key=True),
    col("tenant_id", KEY, foreign_key=fk("tenants.id")),
    col("name", TXT),
    col("description", TXT, ""),
    col("status", KEY, "active"),
    col("created_by", KEY, foreign_key=fk("users.id", ondelete="RESTRICT")),
    col("created_at", TS),
    col("updated_at", TS),
)
sa.Table(
    "acl_entries", metadata,
    col("id", KEY, primary_key=True),
    col("tenant_id", KEY, foreign_key=fk("tenants.id")),
    col("project_id", KEY, foreign_key=fk("projects.id"), nullable=True),
    col("principal_type", KEY),
    col("principal_id", KEY),
    col("resource", KEY),
    col("action", KEY),
    col("effect", KEY, "allow"),
    col("created_at", TS),
    sa.Index("idx_acl_lookup", "tenant_id", "principal_type", "principal_id", "resource", "action"),
)
# ── Login: server-side sessions ─────────────────────────────────────────────
sa.Table(
    "auth_sessions", metadata,
    col("id", KEY, primary_key=True),
    col("user_id", KEY, foreign_key=fk("users.id")),
    col("token_hash", KEY, unique=True),
    col("user_agent", TXT, ""),
    col("created_at", TS),
    col("last_seen_at", TS),
    col("expires_at", TS),
    col("revoked_at", TS, nullable=True),
    sa.Index("idx_auth_sessions_user", "user_id", "revoked_at"),
)
# ── Apps and their immutable published versions ────────────────────────────
sa.Table(
    "apps", metadata,
    col("id", KEY, primary_key=True),
    *[c() for c in SCOPE],
    col("name", TXT),
    col("description", TXT, nullable=True),
    col("flow_data", TXT),
    col("status", KEY, "draft"),
    col("version", sa.Integer, 0),
    col("docs", TXT, ""),
    col("created_at", TS),
    col("updated_at", TS),
    sa.Index("idx_apps_tenant_project", "tenant_id", "project_id", "updated_at"),
)
sa.Table(
    "app_versions", metadata,
    col("app_id", KEY, primary_key=True),
    col("version", sa.Integer, primary_key=True, autoincrement=False),
    col("tenant_id", KEY),
    col("project_id", KEY),
    col("name", TXT),
    col("description", TXT, ""),
    col("flow_data", TXT),
    col("docs", TXT, ""),
    col("created_at", TS),
)
sa.Table(
    "memory_sessions", metadata,
    col("session_id", KEY),
    col("role", KEY),
    col("content", TXT),
    col("token_count", sa.Integer, 0),
    col("created_at", TS),
    sa.Index("idx_memory_session", "session_id", "created_at"),
)
# ── Conversational workflow runs (paused/resumable) ─────────────────────────
sa.Table(
    "workflow_runs", metadata,
    col("run_id", KEY, primary_key=True),
    col("app_id", KEY),
    col("app_version", sa.Integer, 0),
    col("tenant_id", KEY),
    col("project_id", KEY),
    col("user_id", KEY),
    col("status", KEY),
    col("flow_data", TXT, "{}"),
    col("current_node", KEY, nullable=True),
    col("variables", TXT, "{}"),
    col("history", TXT, "[]"),
    col("created_at", TS),
    col("updated_at", TS),
    sa.Index("idx_workflow_runs_scope", "tenant_id", "project_id", "user_id", "updated_at"),
)
sa.Table(
    "cache_entries", metadata,
    col("cache_key", KEY, primary_key=True),
    col("scope", KEY, "prompt"),
    col("prompt_hash", KEY),
    col("output", TXT),
    col("model", KEY),
    col("provider", KEY),
    col("hit_count", sa.Integer, 0),
    col("created_at", TS),
    col("expires_at", TS),
    sa.Index("idx_cache_expires", "expires_at"),
)
# ── Custom tools / MCP servers / skills ─────────────────────────────────────
sa.Table(
    "custom_tools", metadata,
    col("id", KEY, primary_key=True),
    *[c() for c in SCOPE],
    col("name", TXT),
    col("icon", KEY, "🔧"),
    col("description", TXT, ""),
    col("code", TXT),
    col("config_keys", TXT, "[]"),
    col("created_at", TS),
    col("updated_at", TS),
    sa.Index("idx_custom_tools_tenant_project", "tenant_id", "project_id", "created_at"),
)
sa.Table(
    "custom_mcp_servers", metadata,
    col("id", KEY, primary_key=True),
    *[c() for c in SCOPE],
    col("name", TXT),
    col("icon", KEY, "🔌"),
    col("description", TXT, ""),
    col("transport", KEY, "stdio"),
    col("command", TXT, ""),
    col("args", TXT, "[]"),
    col("env_vars", TXT, "{}"),
    col("url", TXT, ""),
    col("headers", TXT, "{}"),
    col("tools_cache", TXT, "[]"),
    col("created_at", TS),
    col("updated_at", TS),
    sa.Index("idx_custom_mcp_tenant_project", "tenant_id", "project_id", "created_at"),
)
sa.Table(
    "skills", metadata,
    col("id", KEY, primary_key=True),
    *[c() for c in SCOPE],
    col("name", TXT),
    col("icon", KEY, "⚡"),
    col("description", TXT, ""),
    col("instructions", TXT, ""),
    col("tool_ids", TXT, "[]"),
    col("tags", TXT, "[]"),
    col("category", KEY, "general"),
    col("created_at", TS),
    col("updated_at", TS),
    sa.Index("idx_skills_tenant_project", "tenant_id", "project_id", "created_at"),
)
# ── Connections (data sources & services) ───────────────────────────────────
sa.Table(
    "connections", metadata,
    col("id", KEY, primary_key=True),
    col("name", TXT),
    col("type", KEY),
    col("icon", KEY, "🔗"),
    col("description", TXT, ""),
    col("config", TXT, "{}"),
    col("status", KEY, "untested"),
    col("status_msg", TXT, ""),
    col("created_at", TS),
    col("updated_at", TS),
)
# ── Traces ──────────────────────────────────────────────────────────────────
sa.Table(
    "traces", metadata,
    col("id", KEY, primary_key=True),
    col("run_id", KEY),
    col("app_id", KEY, nullable=True),
    col("node_id", KEY, nullable=True),
    col("node_type", KEY, "llm"),
    col("provider", KEY, ""),
    col("model", KEY, ""),
    col("prompt_tokens", sa.Integer, 0),
    col("completion_tokens", sa.Integer, 0),
    col("total_tokens", sa.Integer, 0),
    col("latency_ms", sa.Integer, 0),
    col("cost_usd", sa.Float, 0.0),
    col("attempt_count", sa.Integer, 1),
    col("used_fallback", sa.Integer, 0),
    col("effective_provider", KEY, nullable=True),
    col("effective_model", KEY, nullable=True),
    col("status", KEY, "success"),
    col("error", TXT, nullable=True),
    col("prompt_preview", TXT, nullable=True),
    col("output_preview", TXT, nullable=True),
    col("metadata_json", TXT, nullable=True),
    col("spans_json", TXT, nullable=True),
    col("created_at", TS),
    sa.Index("idx_traces_run_id", "run_id", "created_at"),
    sa.Index("idx_traces_created_at", "created_at"),
)
# ── Spend budgets ───────────────────────────────────────────────────────────
sa.Table(
    "budgets", metadata,
    col("id", KEY, primary_key=True),
    col("scope", KEY, "global"),
    col("scope_id", KEY, ""),
    col("period", KEY, "monthly"),
    col("limit_usd", sa.Float),
    col("action", KEY, "block"),
    col("created_at", TS),
    col("updated_at", TS),
    sa.UniqueConstraint("scope", "scope_id", "period"),
)
# ── Knowledge bases ─────────────────────────────────────────────────────────
sa.Table(
    "knowledge_bases", metadata,
    col("id", KEY, primary_key=True),
    col("name", TXT),
    col("icon", KEY, "📚"),
    col("description", TXT, ""),
    col("source_type", KEY, "text"),
    col("source_detail", TXT, ""),
    col("embedding_provider", KEY, "local"),
    col("embedding_model", sa.Unicode(255), "sentence-transformers/all-MiniLM-L6-v2"),
    col("chunk_count", sa.Integer, 0),
    col("created_at", TS),
    col("updated_at", TS),
)
# ── Middleware ──────────────────────────────────────────────────────────────
sa.Table(
    "middleware", metadata,
    col("id", KEY, primary_key=True),
    col("name", TXT),
    col("type", KEY),
    col("icon", KEY, "🛡️"),
    col("description", TXT, ""),
    col("config", TXT, "{}"),
    col("enabled", sa.Integer, 1),
    col("created_at", TS),
    col("updated_at", TS),
    sa.Index("idx_middleware_type", "type", "created_at"),
)
# ── Eval ────────────────────────────────────────────────────────────────────
sa.Table(
    "eval_datasets", metadata,
    col("id", KEY, primary_key=True),
    col("name", TXT),
    col("description", TXT, ""),
    col("app_id", KEY, nullable=True),
    col("app_version", sa.Integer, 0),
    col("created_at", TS),
    col("updated_at", TS),
)
sa.Table(
    "eval_cases", metadata,
    col("id", KEY, primary_key=True),
    col("dataset_id", KEY),
    col("prompt", TXT),
    col("expected_output", TXT, ""),
    col("tags", TXT, "[]"),
    col("source", KEY, "manual"),  # manual | ai | traces
    col("created_at", TS),
    sa.Index("idx_eval_cases_dataset", "dataset_id"),
)
sa.Table(
    "eval_runs", metadata,
    col("id", KEY, primary_key=True),
    col("app_id", KEY),
    col("app_version", sa.Integer, 0),
    col("dataset_id", KEY),
    col("dataset_name", TXT, ""),
    col("scorer", KEY, "contains"),
    col("total", sa.Integer, 0),
    col("passed", sa.Integer, 0),
    col("failed", sa.Integer, 0),
    col("avg_latency_ms", sa.Float, 0.0),
    col("total_cost_usd", sa.Float, 0.0),
    col("created_at", TS),
)
sa.Table(
    "eval_results", metadata,
    col("id", KEY, primary_key=True),
    col("run_id", KEY),
    col("case_id", KEY),
    col("prompt", TXT),
    col("actual_output", TXT, ""),
    col("expected_output", TXT, ""),
    col("score", sa.Float, 0.0),
    col("scorer", KEY, "contains"),
    col("pass", sa.Integer, 0),
    col("latency_ms", sa.Integer, 0),
    col("cost_usd", sa.Float, 0.0),
    col("error", TXT, nullable=True),
    col("created_at", TS),
    sa.Index("idx_eval_results_run", "run_id"),
)
# ── Master-agent runs (checkpointed: see services/checkpoint.py) ────────────
# status: running | paused | completed | failed | rejected | interrupted | cancelled.
# checkpoint holds finished steps + gate decisions; never provider keys.
sa.Table(
    "agent_runs", metadata,
    col("run_id", KEY, primary_key=True),
    col("goal", TXT),
    col("strategy", KEY),
    col("final_answer", TXT),
    col("steps", TXT),
    col("success", sa.Integer, 1),
    col("error", TXT, nullable=True),
    col("created_at", TS),
    col("status", KEY, "completed"),
    col("app_id", KEY, nullable=True),
    col("tenant_id", KEY, "tenant_demo"),
    col("project_id", KEY, "proj_research"),
    col("user_id", KEY, "user_admin"),
    col("fingerprint", KEY, nullable=True),
    col("checkpoint", TXT, "{}"),
    col("pending_gate", TXT, nullable=True),
    col("updated_at", TS, nullable=True),
    sa.Index("idx_agent_runs_scope", "tenant_id", "project_id", "status", "created_at"),
)
# ── API keys (public /v1 API) ───────────────────────────────────────────────
# Only the SHA-256 of a key is stored; the plaintext is shown once at creation.
# A key acts as created_by inside tenant_id/project_id, so ACLs still apply.
sa.Table(
    "api_keys", metadata,
    col("id", KEY, primary_key=True),
    col("tenant_id", KEY),
    col("project_id", KEY),
    col("created_by", KEY),
    col("name", TXT),
    col("key_prefix", KEY),
    col("key_hash", KEY, unique=True),
    col("scopes", TXT, '["apps:read","apps:run"]'),
    col("rate_limit_rpm", sa.Integer, 60),
    col("request_count", sa.Integer, 0),
    col("created_at", TS),
    col("last_used_at", TS, nullable=True),
    col("expires_at", TS, nullable=True),
    col("revoked_at", TS, nullable=True),
    sa.Index("idx_api_keys_scope", "tenant_id", "project_id", "created_at"),
)
# ── Marketplace: published pipelines others can try and import ─────────────
sa.Table(
    "marketplace_listings", metadata,
    col("id", KEY, primary_key=True),
    col("publisher_tenant_id", KEY, foreign_key=fk("tenants.id")),
    col("publisher_project_id", KEY),
    col("publisher_user_id", KEY),
    col("source_app_id", KEY),
    col("name", TXT),
    col("summary", TXT, ""),
    col("description", TXT, ""),
    col("category", KEY, "general"),
    col("tags", TXT, "[]"),
    col("visibility", KEY, "public"),
    col("status", KEY, "listed"),
    col("latest_version", sa.Integer, 1),
    col("import_count", sa.Integer, 0),
    col("try_count", sa.Integer, 0),
    col("created_at", TS),
    col("updated_at", TS),
    sa.Index("idx_marketplace_source", "source_app_id", unique=True),
)
sa.Table(
    "marketplace_versions", metadata,
    col("listing_id", KEY, foreign_key=fk("marketplace_listings.id"), primary_key=True),
    col("version", sa.Integer, primary_key=True, autoincrement=False),
    col("source_app_version", sa.Integer, 0),
    col("flow_data", TXT),
    col("requirements", TXT, "[]"),
    col("bundled_tools", TXT, "[]"),
    col("changelog", TXT, ""),
    col("docs", TXT, ""),
    col("created_at", TS),
)
sa.Table(
    "marketplace_imports", metadata,
    col("id", KEY, primary_key=True),
    col("listing_id", KEY),
    col("version", sa.Integer),
    col("tenant_id", KEY),
    col("project_id", KEY),
    col("user_id", KEY),
    col("app_id", KEY),
    col("created_at", TS),
    sa.Index("idx_marketplace_imports_scope", "tenant_id", "project_id", "created_at"),
)


def _column_copy(column: sa.Column) -> sa.Column:
    default = column.server_default.arg if column.server_default is not None else None
    return sa.Column(column.name, column.type, nullable=column.nullable, server_default=default)


def upgrade() -> None:
    if context.is_offline_mode():  # `alembic upgrade head --sql`: plain DDL for a fresh database
        for table in metadata.sorted_tables:
            op.execute(sa.schema.CreateTable(table))
            for index in table.indexes:
                op.execute(sa.schema.CreateIndex(index))
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    added_columns = set()

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            table.create(bind)  # also creates its indexes
            continue
        # Legacy database from the pre-Alembic init_db(): fill in what is missing.
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in have:
                op.add_column(table.name, _column_copy(column))
                added_columns.add((table.name, column.name))
        have_indexes = {ix["name"] for ix in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in have_indexes:
                index.create(bind)

    # One-off: datasets saved by the AI generator before sources were tracked hold AI cases.
    if ("eval_cases", "source") in added_columns:
        op.execute(
            "UPDATE eval_cases SET source = 'ai' WHERE dataset_id IN "
            "(SELECT id FROM eval_datasets WHERE description LIKE 'Generated by %')"
        )
    # Backfill: apps published before version history existed keep their current version.
    op.execute("""
        INSERT INTO app_versions
            (app_id, version, tenant_id, project_id, name, description, flow_data, docs, created_at)
        SELECT a.id, a.version, a.tenant_id, a.project_id, a.name, COALESCE(a.description, ''),
               a.flow_data, a.docs, a.updated_at
        FROM apps a
        WHERE a.status = 'published' AND a.version > 0
          AND NOT EXISTS (SELECT 1 FROM app_versions v WHERE v.app_id = a.id AND v.version = a.version)
    """)


def downgrade() -> None:
    for table in reversed(metadata.sorted_tables):
        table.drop(op.get_bind(), checkfirst=True)
