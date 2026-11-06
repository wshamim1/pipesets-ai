"""Scheduled pipeline runs: schedules + their run history.

Revision ID: 0002_schedules
Revises: 0001_baseline
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_schedules"
down_revision = "0001_baseline"
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
        "schedules",
        col("id", KEY, primary_key=True),
        col("tenant_id", KEY, "tenant_demo"),
        col("project_id", KEY, "proj_research"),
        col("owner_user_id", KEY, "user_admin"),   # scheduled runs act as this user
        col("app_id", KEY),
        col("name", TXT),
        col("cron", sa.Unicode(128)),
        col("timezone", sa.Unicode(64), "UTC"),
        col("prompt", TXT),
        col("enabled", sa.Integer, 1),
        col("timeout_ms", sa.Integer, 120000),
        col("max_failures", sa.Integer, 3),         # auto-pause after this many failures in a row
        col("consecutive_failures", sa.Integer, 0),
        col("next_run_at", TS, nullable=True),      # UTC, "YYYY-MM-DDTHH:MM:SSZ" (sorts as text)
        col("last_run_at", TS, nullable=True),
        col("last_status", KEY, nullable=True),
        col("last_error", TXT, nullable=True),
        col("created_at", TS),
        col("updated_at", TS),
        sa.Index("idx_schedules_due", "enabled", "next_run_at"),
        sa.Index("idx_schedules_scope_app", "tenant_id", "project_id", "app_id"),
    )
    op.create_table(
        "schedule_runs",
        col("id", KEY, primary_key=True),
        col("schedule_id", KEY, foreign_key=sa.ForeignKey("schedules.id", ondelete="CASCADE")),
        col("tenant_id", KEY),
        col("project_id", KEY),
        col("app_id", KEY),
        col("app_version", sa.Integer, 0),
        col("trigger", KEY, "schedule"),          # schedule | manual
        col("status", KEY, "running"),            # running | completed | failed | paused | skipped | interrupted
        col("run_id", KEY, nullable=True),        # traces.run_id / agent_runs.run_id
        col("output_preview", TXT, nullable=True),
        col("error", TXT, nullable=True),
        col("latency_ms", sa.Integer, 0),
        col("cost_usd", sa.Float, 0.0),
        col("started_at", TS),
        col("finished_at", TS, nullable=True),
        sa.Index("idx_schedule_runs_schedule", "schedule_id", "started_at"),
    )


def downgrade() -> None:
    op.drop_table("schedule_runs")
    op.drop_table("schedules")
