"""Durable job queue (services/jobs.py) and named leases for singleton loops.

Revision ID: 0014_jobs
Revises: 0013_server_admin
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_jobs"
down_revision = "0013_server_admin"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("kind", sa.Unicode(64), nullable=False),                   # e.g. schedule.run, notify
        sa.Column("payload", sa.UnicodeText, nullable=False, server_default="{}"),
        sa.Column("status", sa.Unicode(16), nullable=False),                 # queued | running | done | dead
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default=sa.text("3")),
        sa.Column("run_after", TS, nullable=False),                          # not claimed before this
        sa.Column("locked_by", KEY, nullable=True),                          # worker id while running
        sa.Column("locked_until", TS, nullable=True),                        # lease; renewed by heartbeat
        sa.Column("last_error", sa.UnicodeText, nullable=True),
        sa.Column("dedupe_key", sa.Unicode(255), nullable=True),             # e.g. schedule:<id>
        sa.Column("tenant_id", KEY, nullable=False, server_default=""),
        sa.Column("project_id", KEY, nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("finished_at", TS, nullable=True),
    )
    op.create_index("idx_jobs_claim", "jobs", ["status", "run_after"])
    op.create_index("idx_jobs_dedupe", "jobs", ["dedupe_key", "status"])
    op.create_index("idx_jobs_scope", "jobs", ["tenant_id", "project_id", "status"])

    op.create_table(
        "leases",
        sa.Column("name", KEY, primary_key=True),                           # e.g. scheduler
        sa.Column("holder", KEY, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("leases")
    op.drop_index("idx_jobs_scope", table_name="jobs")
    op.drop_index("idx_jobs_dedupe", table_name="jobs")
    op.drop_index("idx_jobs_claim", table_name="jobs")
    op.drop_table("jobs")
