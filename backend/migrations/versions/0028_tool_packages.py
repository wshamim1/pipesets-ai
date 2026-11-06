"""Settings → Tools & MCP packages: which built-in tools and MCP servers a workspace has installed,
so only those are offered as nodes in the builder (services/tool_packages.py).

One row per tool the workspace has decided on; ``installed`` = 0 records an uninstall, so a tool
in the default set stays hidden once removed. A tool with no row falls back to the defaults.

Revision ID: 0028_tool_packages
Revises: 0027_extraction_review_pages
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_tool_packages"
down_revision = "0027_extraction_review_pages"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "tool_packages",
        sa.Column("tenant_id", KEY, primary_key=True),
        sa.Column("tool_id", KEY, primary_key=True),
        sa.Column("installed", sa.Boolean, nullable=False),
        sa.Column("updated_by", KEY, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tool_packages")
