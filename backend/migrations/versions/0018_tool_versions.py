"""Custom tool versions and parameter schemas (services/tool_store.py).

* ``custom_tools`` gains ``version`` (the latest), ``source`` (ui | sdk) and ``signature`` (JSON:
  entry point and parameter schema, read from the code — services/tool_signature.py).
* ``custom_tool_versions``: every saved code change, so apps can pin one and a tool can roll back.
  Existing tools become version 1; their signature is read the first time they are used.

Revision ID: 0018_tool_versions
Revises: 0017_long_term_memory
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_tool_versions"
down_revision = "0017_long_term_memory"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    with op.batch_alter_table("custom_tools") as batch:
        batch.add_column(sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")))
        batch.add_column(sa.Column("source", KEY, nullable=False, server_default="ui"))
        batch.add_column(sa.Column("signature", sa.UnicodeText, nullable=True))

    op.create_table(
        "custom_tool_versions",
        sa.Column("tool_id", KEY, primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=False),
        sa.Column("name", sa.UnicodeText, nullable=False),
        sa.Column("description", sa.UnicodeText, nullable=False, server_default=""),
        sa.Column("code", sa.UnicodeText, nullable=False),
        sa.Column("signature", sa.UnicodeText, nullable=True),
        sa.Column("config_keys", sa.UnicodeText, nullable=False, server_default="[]"),
        sa.Column("requirements", sa.UnicodeText, nullable=False, server_default="[]"),
        sa.Column("source", KEY, nullable=False, server_default="ui"),
        sa.Column("checksum", sa.Unicode(64), nullable=False, server_default=""),
        sa.Column("note", sa.UnicodeText, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("created_by", KEY, nullable=True),
    )
    op.execute(
        "INSERT INTO custom_tool_versions (tool_id, version, tenant_id, project_id, name, description, code, "
        "config_keys, requirements, source, created_at, created_by) "
        "SELECT id, 1, COALESCE(tenant_id, ''), COALESCE(project_id, ''), COALESCE(name, ''), COALESCE(description, ''), "
        "COALESCE(code, ''), COALESCE(config_keys, '[]'), COALESCE(requirements, '[]'), 'ui', "
        "COALESCE(updated_at, created_at, ''), owner_user_id FROM custom_tools")


def downgrade() -> None:
    op.drop_table("custom_tool_versions")
    with op.batch_alter_table("custom_tools") as batch:
        batch.drop_column("signature")
        batch.drop_column("source")
        batch.drop_column("version")
