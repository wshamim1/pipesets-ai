"""Checkpointed single-LLM runs share agent_runs with Master Agent runs (services/llm_checkpoint.py).

agent_runs.kind: "master" (Master Agent flow) or "llm" (a single LLM node, streamed). For "llm"
runs ``goal`` holds the prompt and ``strategy`` is "single".

Revision ID: 0020_run_kind
Revises: 0019_kv_store
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_run_kind"
down_revision = "0019_kv_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("kind", sa.Unicode(128), nullable=False, server_default="master"))


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("kind")
