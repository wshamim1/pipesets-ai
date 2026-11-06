"""Per-tool Python requirements for custom tools, installed into the tool's sandbox environment
(cached image or venv) instead of the backend.

Revision ID: 0011_custom_tool_requirements
Revises: 0010_audit_log
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_custom_tool_requirements"
down_revision = "0010_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("custom_tools") as batch:
        batch.add_column(sa.Column("requirements", sa.UnicodeText, nullable=False, server_default="[]"))   # JSON list


def downgrade() -> None:
    with op.batch_alter_table("custom_tools") as batch:
        batch.drop_column("requirements")
