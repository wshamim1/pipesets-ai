"""Secret kinds: LLM provider keys vs tool/integration keys, enforced at resolution.

Revision ID: 0007_secret_kinds
Revises: 0006_secret_provider_defaults
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_secret_kinds"
down_revision = "0006_secret_provider_defaults"
branch_labels = None
depends_on = None

LLM_PROVIDERS = ("openai", "anthropic", "groq", "gemini", "mistral", "cohere", "together", "fireworks",
                 "deepseek", "xai", "cerebras", "perplexity", "typesafe", "azure", "bedrock", "voyage", "nomic")


def upgrade() -> None:
    # llm  = model provider key: only model / embedding calls may decrypt it
    # tool = tool & integration key (Serper, Slack webhook, …): only tools may decrypt it
    with op.batch_alter_table("secrets") as batch:
        batch.add_column(sa.Column("kind", sa.Unicode(16), nullable=False, server_default="tool"))
    marks = ", ".join(f"'{p}'" for p in LLM_PROVIDERS)
    op.execute(f"UPDATE secrets SET kind = 'llm' WHERE default_for IS NOT NULL OR provider IN ({marks})")


def downgrade() -> None:
    with op.batch_alter_table("secrets") as batch:
        batch.drop_column("kind")
