"""Chat links: a public URL that opens a chat with one published pipeline (services/chat_links.py).

* ``chat_links``: one row per link. ``token_hash`` finds the link from its URL; ``token_sealed`` is
  the same token encrypted under the master key, so the builder can copy the link again.
  ``access`` is ``public`` (anyone with the link) for now; passcode / sign-in come later (plan.md C9).

Revision ID: 0024_chat_links
Revises: 0023_model_optimization_cases
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_chat_links"
down_revision = "0023_model_optimization_cases"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "chat_links",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=False),
        sa.Column("app_id", KEY, nullable=False),
        sa.Column("created_by", KEY, nullable=False),
        sa.Column("name", sa.Unicode(200), nullable=False),
        sa.Column("title", sa.Unicode(200), nullable=False, server_default=""),
        sa.Column("greeting", sa.UnicodeText, nullable=False, server_default=""),
        sa.Column("access", sa.Unicode(32), nullable=False, server_default="public"),
        sa.Column("token_hash", sa.Unicode(64), nullable=False, unique=True),
        sa.Column("token_prefix", sa.Unicode(16), nullable=False),
        sa.Column("token_sealed", sa.UnicodeText, nullable=False),
        sa.Column("rate_limit_per_min", sa.Integer, nullable=False, server_default="10"),
        sa.Column("max_turns", sa.Integer, nullable=False, server_default="50"),
        sa.Column("max_message_chars", sa.Integer, nullable=False, server_default="4000"),
        sa.Column("daily_message_cap", sa.Integer, nullable=False, server_default="500"),
        sa.Column("message_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("revoked_at", TS, nullable=True),
    )
    op.create_index("idx_chat_links_app", "chat_links", ["tenant_id", "project_id", "app_id"])


def downgrade() -> None:
    op.drop_index("idx_chat_links_app", table_name="chat_links")
    op.drop_table("chat_links")
