"""Extraction review queue: one row per extracted field waiting for a person (services/extraction_reviews.py).

* ``extraction_reviews``: what the model read (``value``, ``page``, ``quote``, ``confidence``,
  ``verified`` = the quote was found on that page) and what the reviewer decided (``status``
  pending / approved / corrected / rejected, ``final_value``, ``note``, ``reviewed_by``).
  Values are stored as JSON so numbers, dates and booleans keep their type.

Revision ID: 0026_extraction_reviews
Revises: 0025_chat_link_details
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_extraction_reviews"
down_revision = "0025_chat_link_details"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "extraction_reviews",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=False),
        sa.Column("batch", sa.Unicode(200), nullable=False, server_default=""),
        sa.Column("source", sa.Unicode(1000), nullable=False),
        sa.Column("field", sa.Unicode(128), nullable=False),
        sa.Column("description", sa.UnicodeText, nullable=False, server_default=""),
        sa.Column("field_type", sa.Unicode(32), nullable=False, server_default="text"),
        sa.Column("value", sa.UnicodeText, nullable=True),
        sa.Column("page", sa.Integer, nullable=True),
        sa.Column("page_label", sa.Unicode(500), nullable=True),
        sa.Column("quote", sa.UnicodeText, nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("status", sa.Unicode(32), nullable=False, server_default="pending"),
        sa.Column("final_value", sa.UnicodeText, nullable=True),
        sa.Column("note", sa.UnicodeText, nullable=False, server_default=""),
        sa.Column("model", sa.Unicode(200), nullable=False, server_default=""),
        sa.Column("created_by", KEY, nullable=False, server_default=""),
        sa.Column("reviewed_by", KEY, nullable=True),
        sa.Column("reviewed_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("idx_extraction_reviews_status", "extraction_reviews", ["tenant_id", "project_id", "status"])
    op.create_index("idx_extraction_reviews_source", "extraction_reviews", ["tenant_id", "project_id", "source"])


def downgrade() -> None:
    op.drop_index("idx_extraction_reviews_source", table_name="extraction_reviews")
    op.drop_index("idx_extraction_reviews_status", table_name="extraction_reviews")
    op.drop_table("extraction_reviews")
