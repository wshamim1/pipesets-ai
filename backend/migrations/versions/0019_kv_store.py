"""Key-value store for agents (services/kv_store.py, the ``key_value_store`` tool).

* ``kv_entries``: JSON values by (tenant, project, namespace, subject, key). ``subject`` is the end
  user an entry belongs to, "" for entries shared across the project. ``expires_at`` is NULL for
  entries that never expire.

Revision ID: 0019_kv_store
Revises: 0018_tool_versions
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_kv_store"
down_revision = "0018_tool_versions"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "kv_entries",
        sa.Column("tenant_id", KEY, primary_key=True),
        sa.Column("project_id", KEY, primary_key=True),
        sa.Column("namespace", KEY, primary_key=True),
        sa.Column("subject", sa.Unicode(255), primary_key=True),
        sa.Column("key", sa.Unicode(255), primary_key=True),
        sa.Column("value", sa.UnicodeText, nullable=False),
        sa.Column("expires_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("idx_kv_entries_expires", "kv_entries", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_kv_entries_expires", table_name="kv_entries")
    op.drop_table("kv_entries")
