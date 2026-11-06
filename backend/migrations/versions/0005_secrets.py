"""Encrypted secrets vault (API keys and tokens referenced by tool configs).

Revision ID: 0005_secrets
Revises: 0004_publish_gates
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_secrets"
down_revision = "0004_publish_gates"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)
TXT = sa.UnicodeText


def col(name, type_, default=None, nullable=False, foreign_key=None, **kw):
    if isinstance(default, (int, float)):
        default = sa.text(str(default))
    args = (foreign_key,) if foreign_key is not None else ()
    return sa.Column(name, type_, *args, nullable=nullable, server_default=default, **kw)


def upgrade() -> None:
    op.create_table(
        "secrets",
        col("id", KEY, primary_key=True),
        col("tenant_id", KEY),
        col("project_id", KEY, nullable=True),     # NULL = shared with every project in the tenant
        col("name", sa.Unicode(200)),
        col("provider", KEY, ""),                  # e.g. serper, tavily, openai — UI grouping/suggestions
        col("ciphertext", TXT),                    # Fernet token (AES-128-CBC + HMAC-SHA256)
        col("last4", sa.Unicode(8), ""),           # shown masked in the UI; the value is never returned
        col("created_by", KEY),
        col("created_at", TS),
        col("updated_at", TS),
        col("last_used_at", TS, nullable=True),
        sa.Index("idx_secrets_scope", "tenant_id", "project_id"),
    )


def downgrade() -> None:
    op.drop_table("secrets")
