"""Seal credentials still stored in plain text: webhook signing secrets, notification channel
URLs, and credentials typed into nodes of saved flows (apps and app versions).

Idempotent — values already sealed ("enc://") or vault refs are left alone. Downgrade opens
the webhook / channel columns again; flows stay sealed (runs resolve sealed values anyway).

Revision ID: 0009_seal_credentials
Revises: 0008_llm_settings
Create Date: 2026-10-28
"""
import json

from alembic import context, op
import sqlalchemy as sa

revision = "0009_seal_credentials"
down_revision = "0008_llm_settings"
branch_labels = None
depends_on = None

COLUMNS = (("webhooks", "secret"), ("notification_channels", "url"))
FLOWS = (("apps", ("id",)), ("app_versions", ("app_id", "version")))


def _where(keys) -> str:
    return " AND ".join(f"{k} = :{k}" for k in keys)


def upgrade() -> None:
    if context.is_offline_mode():  # `manage.py db sql`: data can't be read, nothing to seal
        return
    from services import secret_store

    bind = op.get_bind()
    for table, col in COLUMNS:
        rows = bind.execute(sa.text(f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} <> ''"))
        for row_id, value in rows.fetchall():
            if not secret_store.is_sealed(value):
                bind.execute(sa.text(f"UPDATE {table} SET {col} = :v WHERE id = :id"),
                             {"v": secret_store.seal(value), "id": row_id})
    for table, keys in FLOWS:
        rows = bind.execute(sa.text(f"SELECT {', '.join(keys)}, flow_data FROM {table}")).mappings().fetchall()
        for row in rows:
            try:
                flow = json.loads(row["flow_data"] or "{}")
            except ValueError:
                continue
            if secret_store.seal_flow_credentials(flow):
                bind.execute(sa.text(f"UPDATE {table} SET flow_data = :flow WHERE {_where(keys)}"),
                             {"flow": json.dumps(flow), **{k: row[k] for k in keys}})


def downgrade() -> None:
    if context.is_offline_mode():
        return
    from services import secret_store

    bind = op.get_bind()
    for table, col in COLUMNS:
        rows = bind.execute(sa.text(f"SELECT id, {col} FROM {table} WHERE {col} LIKE 'enc://%'"))
        for row_id, value in rows.fetchall():
            bind.execute(sa.text(f"UPDATE {table} SET {col} = :v WHERE id = :id"),
                         {"v": secret_store.unseal(value), "id": row_id})
