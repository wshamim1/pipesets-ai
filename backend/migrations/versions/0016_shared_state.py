"""Shared state for several replicas (services/shared_state.py, PIPESETS_SHARED_STATE=database):
sliding-window hits for rate limits and login lockouts, and expiring flags for cancel signals.

Revision ID: 0016_shared_state
Revises: 0015_run_retries
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_shared_state"
down_revision = "0015_run_retries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shared_hits",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("bucket", sa.Unicode(255), nullable=False),  # e.g. rl:key:<id>, login:<email>
        sa.Column("at", sa.Float, nullable=False),              # unix time of the hit
    )
    op.create_index("idx_shared_hits_bucket_at", "shared_hits", ["bucket", "at"])
    op.create_index("idx_shared_hits_at", "shared_hits", ["at"])

    op.create_table(
        "shared_flags",
        sa.Column("name", sa.Unicode(255), primary_key=True),   # e.g. cancel:job:<id>
        sa.Column("expires_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("shared_flags")
    op.drop_index("idx_shared_hits_at", table_name="shared_hits")
    op.drop_index("idx_shared_hits_bucket_at", table_name="shared_hits")
    op.drop_table("shared_hits")
