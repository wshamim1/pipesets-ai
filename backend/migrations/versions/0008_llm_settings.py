"""Per-project / workspace-wide model backend settings (Settings → Model backends).

Revision ID: 0008_llm_settings
Revises: 0007_secret_kinds
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_llm_settings"
down_revision = "0007_secret_kinds"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    # One row per provider per scope; project_id NULL = every project in the tenant.
    # Uniqueness per scope is enforced in code (NULL project_id defeats a unique index).
    op.create_table(
        "llm_settings",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=True),
        sa.Column("provider", sa.Unicode(64), nullable=False),
        sa.Column("backend", sa.Unicode(64), nullable=False, server_default="auto"),   # auto | litellm | openai_compat
        sa.Column("base_url", sa.Unicode(1024), nullable=False, server_default=""),    # "" = provider default
        sa.Column("updated_by", KEY, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("idx_llm_settings_scope", "llm_settings", ["tenant_id", "provider"])


def downgrade() -> None:
    op.drop_index("idx_llm_settings_scope", table_name="llm_settings")
    op.drop_table("llm_settings")
