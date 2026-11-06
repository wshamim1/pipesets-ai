"""Per-project default LLM provider keys in the secrets vault.

Revision ID: 0006_secret_provider_defaults
Revises: 0005_secrets
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_secret_provider_defaults"
down_revision = "0005_secrets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Provider (openai, anthropic, …) this secret is the default key for; NULL = not a default.
    # At most one per provider at each scope level (project, or tenant-wide) — enforced in code.
    with op.batch_alter_table("secrets") as batch:
        batch.add_column(sa.Column("default_for", sa.Unicode(64), nullable=True))
        batch.create_index("idx_secrets_default", ["tenant_id", "default_for"])


def downgrade() -> None:
    with op.batch_alter_table("secrets") as batch:
        batch.drop_index("idx_secrets_default")
        batch.drop_column("default_for")
