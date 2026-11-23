"""SCIM 2.0 provisioning (services/scim.py) and audit log streaming (services/audit_stream.py).

* ``sso_providers.scim_token_hash`` / ``scim_token_prefix``: the IdP's SCIM bearer token (SHA-256 only).
* ``scim_users``: a Pipesets user provisioned by a provider into its tenant — the IdP's view of them
  (externalId, userName, active). Deactivated users keep their row (``active = 0``) so the IdP can read them.
* ``scim_groups`` / ``scim_group_members``: IdP groups pushed over SCIM. Their display names are matched
  against the provider's role mappings to set the member's workspace role and Pipesets groups.
* ``audit_sinks``: where a tenant's audit log is streamed (webhook, Splunk HEC, Datadog). ``cursor_at`` /
  ``cursor_id`` is the last delivered entry; ``url`` and ``token`` are sealed.

Revision ID: 0040_scim_audit_streams
Revises: 0039_bind_sealed_values
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0040_scim_audit_streams"
down_revision = "0039_bind_sealed_values"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    with op.batch_alter_table("sso_providers") as batch:
        batch.add_column(sa.Column("scim_token_hash", sa.Unicode(64), nullable=True))
        batch.add_column(sa.Column("scim_token_prefix", sa.Unicode(16), nullable=True))
    op.create_index("idx_sso_providers_scim", "sso_providers", ["scim_token_hash"])

    op.create_table(
        "scim_users",
        sa.Column("provider_id", KEY, primary_key=True),
        sa.Column("user_id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("external_id", sa.Unicode(512), nullable=False, server_default=""),
        sa.Column("user_name", sa.Unicode(512), nullable=False),
        sa.Column("display_name", sa.Unicode(200), nullable=False, server_default=""),
        sa.Column("active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_user", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("idx_scim_users_name", "scim_users", ["provider_id", "user_name"])

    op.create_table(
        "scim_groups",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("provider_id", KEY, nullable=False),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("display_name", sa.Unicode(256), nullable=False),
        sa.Column("external_id", sa.Unicode(512), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("idx_scim_groups_provider", "scim_groups", ["provider_id", "display_name"])
    op.create_table(
        "scim_group_members",
        sa.Column("group_id", KEY, primary_key=True),
        sa.Column("user_id", KEY, primary_key=True),
    )
    op.create_index("idx_scim_group_members_user", "scim_group_members", ["user_id"])

    op.create_table(
        "audit_sinks",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("name", sa.Unicode(200), nullable=False),
        sa.Column("kind", sa.Unicode(32), nullable=False),
        sa.Column("url", sa.UnicodeText, nullable=False),
        sa.Column("token", sa.UnicodeText, nullable=False, server_default=""),
        sa.Column("enabled", sa.Integer, nullable=False, server_default="1"),
        sa.Column("cursor_at", TS, nullable=False, server_default=""),
        sa.Column("cursor_id", KEY, nullable=False, server_default=""),
        sa.Column("delivered", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_delivered_at", TS, nullable=True),
        sa.Column("last_error", sa.UnicodeText, nullable=False, server_default=""),
        sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_attempt_at", TS, nullable=False, server_default=""),
        sa.Column("created_by", KEY, nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("idx_audit_sinks_tenant", "audit_sinks", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_audit_sinks_tenant", table_name="audit_sinks")
    op.drop_table("audit_sinks")
    op.drop_index("idx_scim_group_members_user", table_name="scim_group_members")
    op.drop_table("scim_group_members")
    op.drop_index("idx_scim_groups_provider", table_name="scim_groups")
    op.drop_table("scim_groups")
    op.drop_index("idx_scim_users_name", table_name="scim_users")
    op.drop_table("scim_users")
    op.drop_index("idx_sso_providers_scim", table_name="sso_providers")
    with op.batch_alter_table("sso_providers") as batch:
        batch.drop_column("scim_token_prefix")
        batch.drop_column("scim_token_hash")
