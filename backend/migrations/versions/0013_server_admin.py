"""Server admins: users who manage the server itself (its database), above any one workspace.

Existing installs get one right away — the oldest account with a password, plus the seeded demo
admin — so the next sign-up on a public server can't claim the role.

Revision ID: 0013_server_admin
Revises: 0012_audit_log_time_index
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_server_admin"
down_revision = "0012_audit_log_time_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("server_admin", sa.Integer, nullable=False, server_default=sa.text("0")))
    op.execute("UPDATE users SET server_admin = 1 WHERE id = 'user_admin'")
    op.execute(
        "UPDATE users SET server_admin = 1 WHERE id = ("
        "SELECT id FROM (SELECT id FROM users WHERE password_hash IS NOT NULL "
        "ORDER BY created_at, id LIMIT 1) AS oldest)"
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("server_admin")
