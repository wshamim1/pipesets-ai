"""Batch runs over documents (plan.md F5, services/batches.py).

batch_runs.source: what the rows came from, as JSON — ``{"kind": "rows"}`` for a table (CSV, JSONL,
Excel, …) or ``{"kind": "documents", "loader": ..., "ocr_engine": ..., "max_chars": ...}`` for
uploaded files, kept under ``<data dir>/uploads/batches/<batch id>/`` and read when their row runs.

Revision ID: 0032_batch_documents
Revises: 0031_batch_runs
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_batch_documents"
down_revision = "0031_batch_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("batch_runs") as batch:
        batch.add_column(sa.Column("source", sa.UnicodeText, nullable=False, server_default='{"kind": "rows"}'))


def downgrade() -> None:
    with op.batch_alter_table("batch_runs") as batch:
        batch.drop_column("source")
