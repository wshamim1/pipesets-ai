"""Conversation memory scoped by tenant / project, and long-term memory.

* ``memory_sessions`` (keyed by session id alone, so equal session ids in two tenants shared one
  history, and without a primary key) becomes ``memory_messages`` with tenant_id / project_id and an
  id. Existing rows move over to the project of the app whose Memory node names their session id;
  failing that, to the only project when the install has one. Sessions whose owner can't be told
  (e.g. ids chosen by /v1 callers, used in several projects) are kept unscoped: no run or
  inspector reaches them.
* ``memories``: facts remembered about an end user across sessions (services/long_term_memory.py).
* ``tenant_features``: per-tenant opt-ins, starting with long-term memory.

Revision ID: 0017_long_term_memory
Revises: 0016_shared_state
Create Date: 2026-10-29
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "0017_long_term_memory"
down_revision = "0016_shared_state"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "memory_messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", KEY, nullable=False, server_default=""),
        sa.Column("project_id", KEY, nullable=False, server_default=""),
        sa.Column("session_id", KEY, nullable=False),
        sa.Column("role", KEY, nullable=False),
        sa.Column("content", sa.UnicodeText, nullable=False, server_default=""),
        sa.Column("token_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("idx_memory_messages_session", "memory_messages", ["tenant_id", "project_id", "session_id"])

    conn = op.get_bind()
    projects = conn.execute(sa.text("SELECT tenant_id, id FROM projects")).fetchall()
    only = (projects[0][0], projects[0][1]) if len(projects) == 1 else ("", "")
    sessions = [r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT session_id FROM memory_sessions WHERE session_id IS NOT NULL")).fetchall()]
    for sid in sessions:
        # Flows are saved with json.dumps: a Memory node holds '"session_id": "<sid>"'
        owners = {(r[0], r[1]) for r in conn.execute(sa.text(
            "SELECT tenant_id, project_id FROM apps WHERE flow_data LIKE :pat"),
            {"pat": "%" + '"session_id": ' + json.dumps(sid) + "%"}).fetchall()}
        tenant, project = owners.pop() if len(owners) == 1 else only
        conn.execute(sa.text(
            "INSERT INTO memory_messages (tenant_id, project_id, session_id, role, content, token_count, created_at) "
            "SELECT :t, :p, session_id, role, COALESCE(content, ''), COALESCE(token_count, 0), created_at "
            "FROM memory_sessions WHERE session_id = :sid ORDER BY created_at"), {"t": tenant, "p": project, "sid": sid})
    op.drop_table("memory_sessions")

    op.create_table(
        "memories",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=False),
        sa.Column("subject", sa.Unicode(255), nullable=False),        # the end user the fact is about
        sa.Column("content", sa.UnicodeText, nullable=False),         # one short fact, PII redacted
        sa.Column("fact_key", sa.Unicode(255), nullable=False),      # normalized content: one row per fact
        sa.Column("source", KEY, nullable=False, server_default="extracted"),   # extracted | manual
        sa.Column("app_id", KEY, nullable=True),                      # where it was learned
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("last_used_at", TS, nullable=True),
    )
    op.create_index("idx_memories_subject", "memories", ["tenant_id", "project_id", "subject"])
    op.create_index("uq_memories_fact", "memories", ["tenant_id", "project_id", "subject", "fact_key"], unique=True)

    op.create_table(
        "tenant_features",
        sa.Column("tenant_id", KEY, primary_key=True),
        sa.Column("feature", KEY, primary_key=True),                  # e.g. long_term_memory
        sa.Column("enabled", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("updated_by", KEY, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tenant_features")
    op.drop_index("uq_memories_fact", table_name="memories")
    op.drop_index("idx_memories_subject", table_name="memories")
    op.drop_table("memories")
    op.create_table(
        "memory_sessions",
        sa.Column("session_id", KEY),
        sa.Column("role", KEY),
        sa.Column("content", sa.UnicodeText),
        sa.Column("token_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", TS),
    )
    op.create_index("idx_memory_session", "memory_sessions", ["session_id", "created_at"])
    op.execute("INSERT INTO memory_sessions (session_id, role, content, token_count, created_at) "
               "SELECT session_id, role, content, token_count, created_at FROM memory_messages")
    op.drop_index("idx_memory_messages_session", table_name="memory_messages")
    op.drop_table("memory_messages")
