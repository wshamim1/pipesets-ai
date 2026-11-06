"""Chat links: what the chat page shows about the pipeline (services/chat_links.py).

* ``show_details``: 1 = the page shows the pipeline's description, models, tools, MCP servers and
  agents (names only); 0 = only the title and greeting.
* ``starter_prompts``: JSON list of example prompts visitors can tap to start.

Revision ID: 0025_chat_link_details
Revises: 0024_chat_links
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_chat_link_details"
down_revision = "0024_chat_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_links") as batch:
        batch.add_column(sa.Column("show_details", sa.Integer, nullable=False, server_default="1"))
        batch.add_column(sa.Column("starter_prompts", sa.UnicodeText, nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("chat_links") as batch:
        batch.drop_column("starter_prompts")
        batch.drop_column("show_details")
