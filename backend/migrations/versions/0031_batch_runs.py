"""Batch runs (plan.md F5, services/batches.py): a published pipeline run once per input row.

* ``batch_runs``: the batch — pipeline, prompt template, how many rows may run at once
  (``concurrency``), retries and timeout per row, ``status`` running / done / cancelled.
* ``batch_items``: one row per input — the row itself (JSON), the prompt made from it, and the
  outcome like a schedule run's (status, attempts, output, error, latency, cost, version), plus
  the run id (its trace and checkpoint) and the job working it.

Revision ID: 0031_batch_runs
Revises: 0030_run_feedback
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_batch_runs"
down_revision = "0030_run_feedback"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "batch_runs",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=False),
        sa.Column("app_id", KEY, nullable=False),
        sa.Column("name", sa.Unicode(200), nullable=False, server_default=""),
        sa.Column("prompt_template", sa.UnicodeText, nullable=False),
        sa.Column("columns", sa.UnicodeText, nullable=False, server_default="[]"),
        sa.Column("concurrency", sa.Integer, nullable=False, server_default="2"),
        sa.Column("retries", sa.Integer, nullable=False, server_default="2"),
        sa.Column("timeout_ms", sa.Integer, nullable=False, server_default="120000"),
        sa.Column("status", sa.Unicode(32), nullable=False, server_default="running"),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", KEY, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("finished_at", TS, nullable=True),
    )
    op.create_index("idx_batch_runs_scope", "batch_runs", ["tenant_id", "project_id", "created_at"])
    op.create_index("idx_batch_runs_status", "batch_runs", ["status"])
    op.create_table(
        "batch_items",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("batch_id", KEY, sa.ForeignKey("batch_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idx", sa.Integer, nullable=False),
        sa.Column("input", sa.UnicodeText, nullable=False, server_default="{}"),
        sa.Column("prompt", sa.UnicodeText, nullable=False),
        sa.Column("status", sa.Unicode(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("job_id", KEY, nullable=True),
        sa.Column("run_id", KEY, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output", sa.UnicodeText, nullable=True),
        sa.Column("error", sa.UnicodeText, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("finished_at", TS, nullable=True),
    )
    op.create_index("idx_batch_items_batch", "batch_items", ["batch_id", "idx"])
    op.create_index("idx_batch_items_status", "batch_items", ["batch_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_batch_items_status", table_name="batch_items")
    op.drop_index("idx_batch_items_batch", table_name="batch_items")
    op.drop_table("batch_items")
    op.drop_index("idx_batch_runs_status", table_name="batch_runs")
    op.drop_index("idx_batch_runs_scope", table_name="batch_runs")
    op.drop_table("batch_runs")
