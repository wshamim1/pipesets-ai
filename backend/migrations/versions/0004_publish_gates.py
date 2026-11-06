"""Eval-gated publishing: per-pipeline publish gates + the gate outcome on each version.

Revision ID: 0004_publish_gates
Revises: 0003_webhooks_notifications
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_publish_gates"
down_revision = "0003_webhooks_notifications"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)
TXT = sa.UnicodeText


def col(name, type_, default=None, nullable=False, foreign_key=None, **kw):
    if isinstance(default, (int, float)):
        default = sa.text(str(default))
    args = (foreign_key,) if foreign_key is not None else ()
    return sa.Column(name, type_, *args, nullable=nullable, server_default=default, **kw)


def upgrade() -> None:
    op.create_table(
        "publish_gates",
        col("app_id", KEY, primary_key=True),        # one gate per pipeline
        col("tenant_id", KEY, "tenant_demo"),
        col("project_id", KEY, "proj_research"),
        col("dataset_id", KEY),
        col("scorer", KEY, "contains"),               # exact | contains | llm_judge
        col("min_pass_rate", sa.Float, 0.8),          # 0..1; the draft must reach this
        col("no_regression", sa.Integer, 1),          # also fail when below the live version's pass rate …
        col("regression_tolerance", sa.Float, 0.0),   # … by more than this (0..1)
        col("mode", KEY, "block"),                    # block | warn
        col("enabled", sa.Integer, 1),
        col("timeout_ms", sa.Integer, 120000),        # per case
        col("updated_by", KEY, nullable=True),
        col("updated_at", TS),
        sa.Index("idx_publish_gates_scope", "tenant_id", "project_id"),
    )
    with op.batch_alter_table("app_versions") as batch:
        batch.add_column(col("published_by", KEY, nullable=True))
        batch.add_column(col("gate_status", KEY, nullable=True))       # passed | warned | overridden
        batch.add_column(col("gate_pass_rate", sa.Float, nullable=True))
        batch.add_column(col("gate_eval_run_id", KEY, nullable=True))  # eval_runs.id


def downgrade() -> None:
    with op.batch_alter_table("app_versions") as batch:
        batch.drop_column("gate_eval_run_id")
        batch.drop_column("gate_pass_rate")
        batch.drop_column("gate_status")
        batch.drop_column("published_by")
    op.drop_table("publish_gates")
