"""Tenant / project scope for traces and evals, which were shared by every workspace.

traces / eval_datasets / eval_runs gain tenant_id + project_id. Existing rows take the scope of
the app they belong to; rows whose app is gone (or that never had one) stay NULL, which no
workspace can see.

Revision ID: 0036_scope_traces_evals
Revises: 0035_agent_packages
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0036_scope_traces_evals"
down_revision = "0035_agent_packages"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TABLES = ("traces", "eval_datasets", "eval_runs")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("tenant_id", KEY, nullable=True))
            batch.add_column(sa.Column("project_id", KEY, nullable=True))
        op.execute(
            f"UPDATE {table} SET "
            f"tenant_id = (SELECT a.tenant_id FROM apps a WHERE a.id = {table}.app_id), "
            f"project_id = (SELECT a.project_id FROM apps a WHERE a.id = {table}.app_id) "
            f"WHERE app_id IS NOT NULL"
        )
        op.create_index(f"idx_{table}_scope", table, ["tenant_id", "project_id", "created_at"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"idx_{table}_scope", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("project_id")
            batch.drop_column("tenant_id")
