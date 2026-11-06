"""Feedback on runs (plan.md F2, services/feedback.py): a 👍 / 👎 and an optional comment per run.

* ``run_feedback``: one row per (run, rater). ``rater`` is who gave it — a builder's user id, a
  chat-link visitor (``link:<link id>:<session>``) or an API caller's end user (``key:<key id>:<user>``);
  rating again replaces the row. ``app_version`` is the pipeline's version when the rating was
  given. The run's prompt and answer are read from ``agent_runs``, not copied here.
  ``dataset_id`` is the eval dataset it was exported to, once someone does.

Revision ID: 0030_run_feedback
Revises: 0029_skills_builtins_in_code
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_run_feedback"
down_revision = "0029_skills_builtins_in_code"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "run_feedback",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=False),
        sa.Column("app_id", KEY, nullable=True),
        sa.Column("app_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_id", KEY, nullable=False),
        sa.Column("source", sa.Unicode(32), nullable=False),            # runner | chat_link | api
        sa.Column("rater", sa.Unicode(400), nullable=False),
        sa.Column("rating", sa.Integer, nullable=False),                # 1 | -1
        sa.Column("comment", sa.UnicodeText, nullable=False, server_default=""),
        sa.Column("correction", sa.UnicodeText, nullable=False, server_default=""),
        sa.Column("dataset_id", KEY, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("run_id", "rater", name="uq_run_feedback_run_rater"),
    )
    op.create_index("idx_run_feedback_app", "run_feedback", ["tenant_id", "project_id", "app_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_run_feedback_app", table_name="run_feedback")
    op.drop_table("run_feedback")
