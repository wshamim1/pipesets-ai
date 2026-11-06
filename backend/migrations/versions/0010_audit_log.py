"""Audit log of admin actions: API keys, secrets, IAM, publishing and other configuration changes.

Revision ID: 0010_audit_log
Revises: 0009_seal_credentials
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_audit_log"
down_revision = "0009_seal_credentials"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    # Append-only: no route updates or deletes rows. Request bodies are never stored.
    op.create_table(
        "audit_log",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False, server_default=""),
        sa.Column("project_id", KEY, nullable=False, server_default=""),
        sa.Column("actor", KEY, nullable=False, server_default=""),           # user id
        sa.Column("action", sa.Unicode(64), nullable=False),                  # e.g. api_key.create
        sa.Column("target_id", KEY, nullable=False, server_default=""),
        sa.Column("outcome", sa.Unicode(16), nullable=False),                 # success | denied
        sa.Column("status", sa.Integer, nullable=False),                      # HTTP status
        sa.Column("method", sa.Unicode(8), nullable=False),
        sa.Column("path", sa.Unicode(512), nullable=False),
        sa.Column("ip", sa.Unicode(64), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("idx_audit_log_tenant_time", "audit_log", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_log_tenant_time", table_name="audit_log")
    op.drop_table("audit_log")
