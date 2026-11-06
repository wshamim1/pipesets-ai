"""Retries for scheduled and webhook runs, which now run as jobs (services/jobs.py).

schedules / webhooks.retries: retries after a failed or crashed run (0–10; -1 = until it succeeds).
schedule_runs / webhook_runs: the job that runs them and how many attempts it has made.

Revision ID: 0015_run_retries
Revises: 0014_jobs
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_run_retries"
down_revision = "0014_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("schedules", "webhooks"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("retries", sa.Integer, nullable=False, server_default=sa.text("2")))
    for table in ("schedule_runs", "webhook_runs"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("job_id", sa.Unicode(128), nullable=True))
            batch.add_column(sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    for table in ("schedule_runs", "webhook_runs"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("attempts")
            batch.drop_column("job_id")
    for table in ("schedules", "webhooks"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("retries")
