"""Review queue: cited pages, merged-part alternatives, bulk approval and prompt versions
(services/extraction_reviews.py).

* ``extraction_reviews.prompt_version``: id of the prompt that extracted the field
  (services/extraction.prompt_version), for the accuracy report.
* ``alternatives``: JSON list of other values a long document's parts found; ``conflict`` = 1 when
  one of them has a verified quote too.
* ``bulk``: 1 = approved by "approve verified above a threshold", not looked at one by one.
* ``extraction_review_pages``: the text of every page a review cites, as the model saw it, so the
  reviewer can read the quote in context without loading (or OCR'ing) the document again.

Revision ID: 0027_extraction_review_pages
Revises: 0026_extraction_reviews
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_extraction_review_pages"
down_revision = "0026_extraction_reviews"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    with op.batch_alter_table("extraction_reviews") as batch:
        batch.add_column(sa.Column("prompt_version", sa.Unicode(64), nullable=False, server_default=""))
        batch.add_column(sa.Column("alternatives", sa.UnicodeText, nullable=True))
        batch.add_column(sa.Column("conflict", sa.Boolean, nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("bulk", sa.Boolean, nullable=False, server_default=sa.false()))
    op.create_table(
        "extraction_review_pages",
        sa.Column("tenant_id", KEY, primary_key=True),
        sa.Column("project_id", KEY, primary_key=True),
        sa.Column("batch", sa.Unicode(200), primary_key=True),
        sa.Column("source", sa.Unicode(1000), primary_key=True),
        sa.Column("page", sa.Integer, primary_key=True),
        sa.Column("page_label", sa.Unicode(500), nullable=True),
        sa.Column("text", sa.UnicodeText, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("extraction_review_pages")
    with op.batch_alter_table("extraction_reviews") as batch:
        batch.drop_column("bulk")
        batch.drop_column("conflict")
        batch.drop_column("alternatives")
        batch.drop_column("prompt_version")
