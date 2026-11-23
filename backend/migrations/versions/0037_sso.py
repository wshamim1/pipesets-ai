"""Single sign-on (services/sso.py): OIDC and SAML identity providers per workspace, with role mapping.

* ``sso_providers``: one row per identity provider of a tenant. ``config`` is JSON; the OIDC client
  secret inside it is sealed (``enc://``). ``role_mappings`` is a JSON list of
  ``{"value", "role", "group_id"}`` matched against the ``role_claim`` claim / attribute.
* ``sso_identities``: the IdP subject (OIDC ``sub`` / SAML NameID) → Pipesets user link.
* ``sso_states``: single-use, short-lived records — a pending sign-in (``login``: nonce, PKCE verifier,
  SAML request id, where to return) and the one-time code that hands a new session to the UI
  (``handoff``). ``data`` is sealed.
* ``auth_sessions.tenant_id``: set on sessions created by SSO. Such a session only reaches that tenant
  and never carries server-admin rights, so one workspace's IdP can't vouch for anything outside it.

Revision ID: 0037_sso
Revises: 0036_scope_traces_evals
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0037_sso"
down_revision = "0036_scope_traces_evals"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    op.create_table(
        "sso_providers",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("name", sa.Unicode(200), nullable=False),
        sa.Column("protocol", sa.Unicode(16), nullable=False),
        sa.Column("enabled", sa.Integer, nullable=False, server_default="1"),
        sa.Column("config", sa.UnicodeText, nullable=False, server_default="{}"),
        sa.Column("email_domains", sa.UnicodeText, nullable=False, server_default="[]"),
        sa.Column("role_claim", sa.Unicode(200), nullable=False, server_default=""),
        sa.Column("role_mappings", sa.UnicodeText, nullable=False, server_default="[]"),
        sa.Column("default_role", sa.Unicode(32), nullable=False, server_default="viewer"),
        sa.Column("auto_provision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("sync_roles", sa.Integer, nullable=False, server_default="1"),
        sa.Column("enforce", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", KEY, nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("idx_sso_providers_tenant", "sso_providers", ["tenant_id"])

    op.create_table(
        "sso_identities",
        sa.Column("provider_id", KEY, primary_key=True),
        sa.Column("subject", sa.Unicode(512), primary_key=True),
        sa.Column("user_id", KEY, nullable=False),
        sa.Column("email", sa.Unicode(254), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_login_at", TS, nullable=True),
    )
    op.create_index("idx_sso_identities_user", "sso_identities", ["user_id"])

    op.create_table(
        "sso_states",
        sa.Column("id", KEY, primary_key=True),
        sa.Column("provider_id", KEY, nullable=False),
        sa.Column("kind", sa.Unicode(16), nullable=False),
        sa.Column("data", sa.UnicodeText, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
    )
    op.create_index("idx_sso_states_expires", "sso_states", ["expires_at"])

    with op.batch_alter_table("auth_sessions") as batch:
        batch.add_column(sa.Column("tenant_id", KEY, nullable=True))
        batch.add_column(sa.Column("sso_provider_id", KEY, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_column("sso_provider_id")
        batch.drop_column("tenant_id")
    op.drop_index("idx_sso_states_expires", table_name="sso_states")
    op.drop_table("sso_states")
    op.drop_index("idx_sso_identities_user", table_name="sso_identities")
    op.drop_table("sso_identities")
    op.drop_index("idx_sso_providers_tenant", table_name="sso_providers")
    op.drop_table("sso_providers")
