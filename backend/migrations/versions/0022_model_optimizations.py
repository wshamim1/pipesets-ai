"""Model optimizations (Evaluate → Optimize models, services/model_routing.py).

* ``model_optimizations``: one search for the cheapest (or fastest) model per LLM node of a pipeline
  that keeps its eval pass rate. ``request`` is the JSON the search was started with (provider keys
  sealed), ``result`` the configs tried so far and the recommendation; both JSON. ``status`` is
  queued | running | done | failed.

Revision ID: 0022_model_optimizations
Revises: 0021_mcp_oauth
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_model_optimizations"
down_revision = "0021_mcp_oauth"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "model_optimizations",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=False),
        sa.Column("user_id", KEY, nullable=False),
        sa.Column("app_id", KEY, nullable=False),
        sa.Column("app_version", sa.Integer, nullable=False),
        sa.Column("dataset_id", KEY, nullable=False),
        sa.Column("status", sa.Unicode(16), nullable=False),
        sa.Column("request", sa.UnicodeText, nullable=False),
        sa.Column("result", sa.UnicodeText, nullable=True),
        sa.Column("error", sa.UnicodeText, nullable=True),
        sa.Column("job_id", KEY, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("idx_model_optimizations_app", "model_optimizations",
                    ["tenant_id", "project_id", "app_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_model_optimizations_app", table_name="model_optimizations")
    op.drop_table("model_optimizations")
