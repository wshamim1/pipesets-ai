"""OAuth for remote custom MCP servers (services/mcp_oauth.py).

custom_mcp_servers.oauth: the server's OAuth state — endpoints, registered client, tokens and a
pending sign-in — as one sealed (``enc://``) JSON document; empty when the server doesn't use OAuth.

Revision ID: 0021_mcp_oauth
Revises: 0020_run_kind
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_mcp_oauth"
down_revision = "0020_run_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("custom_mcp_servers") as batch:
        batch.add_column(sa.Column("oauth", sa.UnicodeText(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("custom_mcp_servers") as batch:
        batch.drop_column("oauth")
