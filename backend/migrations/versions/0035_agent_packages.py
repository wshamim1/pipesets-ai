"""Settings → Agents: which built-in agents a workspace has installed (services/agent_packages.py),
one row per agent the workspace has decided on, like ``tool_packages``.

Revision ID: 0035_agent_packages
Revises: 0034_saved_agents
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0035_agent_packages"
down_revision = "0034_saved_agents"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "agent_packages",
        sa.Column("tenant_id", KEY, primary_key=True),
        sa.Column("agent_id", KEY, primary_key=True),
        sa.Column("installed", sa.Boolean, nullable=False),
        sa.Column("updated_by", KEY, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_packages")
