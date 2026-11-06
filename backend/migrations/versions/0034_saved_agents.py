"""Saved agents (plan.md C11 step 2): a child agent saved from the canvas, with the tool and skill nodes
wired to it, so it can be dropped into other pipelines.

* ``saved_agents``: one row per agent in a project; ``spec`` is JSON (the child's settings, its tool /
  toolkit nodes and its skill nodes, credentials stripped); ``version`` is bumped on every save.
* ``saved_agent_versions``: the spec at each version, so a canvas node can say which one it came from.

Revision ID: 0034_saved_agents
Revises: 0033_agent_skills
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0034_saved_agents"
down_revision = "0033_agent_skills"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "saved_agents",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=False),
        sa.Column("owner_user_id", KEY, nullable=False, server_default=""),
        sa.Column("name", sa.Unicode(200), nullable=False),
        sa.Column("icon", sa.Unicode(32), nullable=False, server_default="🤖"),
        sa.Column("description", sa.UnicodeText, nullable=False, server_default=""),
        sa.Column("spec", sa.UnicodeText, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("idx_saved_agents_scope", "saved_agents", ["tenant_id", "project_id"])
    op.create_table(
        "saved_agent_versions",
        sa.Column("agent_id", KEY, primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=False),
        sa.Column("snapshot", sa.UnicodeText, nullable=False),
        sa.Column("author", KEY, nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("idx_saved_agent_versions_scope", "saved_agent_versions", ["tenant_id", "project_id", "agent_id"])


def downgrade() -> None:
    op.drop_index("idx_saved_agent_versions_scope", table_name="saved_agent_versions")
    op.drop_table("saved_agent_versions")
    op.drop_index("idx_saved_agents_scope", table_name="saved_agents")
    op.drop_table("saved_agents")
