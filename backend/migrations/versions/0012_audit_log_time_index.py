"""Index audit_log on created_at alone, for the retention purge across all tenants.

Revision ID: 0012_audit_log_time_index
Revises: 0011_custom_tool_requirements
Create Date: 2026-10-29
"""
from alembic import op

revision = "0012_audit_log_time_index"
down_revision = "0011_custom_tool_requirements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_audit_log_time", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_log_time", table_name="audit_log")
