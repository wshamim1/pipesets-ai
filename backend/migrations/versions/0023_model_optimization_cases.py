"""Per-case results of model optimizations (services/model_routing.py).

* ``model_optimization_cases``: one row per case of every config a study runs — the prompt, the
  pipeline's answer (first 2000 characters), its score and cost — written as each case finishes,
  so the Optimize tab can show a running config's cases live and any config's cases afterwards.
  ``config_index`` is the config's position in the study's ``tried`` list.

Revision ID: 0023_model_optimization_cases
Revises: 0022_model_optimizations
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_model_optimization_cases"
down_revision = "0022_model_optimizations"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "model_optimization_cases",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("study_id", KEY, nullable=False),
        sa.Column("config_index", sa.Integer, nullable=False),
        sa.Column("case_id", KEY, nullable=False),
        sa.Column("prompt", sa.UnicodeText, nullable=False),
        sa.Column("expected_output", sa.UnicodeText, nullable=False),
        sa.Column("output", sa.UnicodeText, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("passed", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("error", sa.UnicodeText, nullable=True),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("idx_model_optimization_cases_study", "model_optimization_cases", ["study_id", "config_index"])


def downgrade() -> None:
    op.drop_index("idx_model_optimization_cases_study", table_name="model_optimization_cases")
    op.drop_table("model_optimization_cases")
