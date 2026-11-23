"""Bind every stored sealed value that pipelines decrypt to its tenant (services/secret_store.py, ``_BIND``).

From now on ``resolve_refs`` opens a sealed value only in the tenant it is bound to, and refuses unbound ones.
This re-seals, for the owning tenant, the sealed values in connection configs, saved flows and published
versions, and model-optimization requests. Rows with no tenant (connections 0038 couldn't place) stay unbound:
``python manage.py connections --assign`` binds them when it gives them a workspace. Server-owned columns
(webhook secrets, channel URLs, OAuth tokens, chat link tokens) don't need it: they are read with ``unseal``.

Downgrade re-seals the values unbound, since older code can't read the binding.

Revision ID: 0039_bind_sealed_values
Revises: 0038_scope_connections
Create Date: 2026-11-23
"""
import json
import logging

from alembic import op
import sqlalchemy as sa

revision = "0039_bind_sealed_values"
down_revision = "0038_scope_connections"
branch_labels = None
depends_on = None

# (select returning key columns…, json column, tenant), update statement
TARGETS = (
    ("SELECT id, config AS doc, tenant_id FROM connections", "UPDATE connections SET config = :doc WHERE id = :id"),
    ("SELECT id, flow_data AS doc, tenant_id FROM apps", "UPDATE apps SET flow_data = :doc WHERE id = :id"),
    ("SELECT v.app_id AS id, v.version, v.flow_data AS doc, a.tenant_id FROM app_versions v "
     "JOIN apps a ON a.id = v.app_id",
     "UPDATE app_versions SET flow_data = :doc WHERE app_id = :id AND version = :version"),
    ("SELECT id, request AS doc, tenant_id FROM model_optimizations",
     "UPDATE model_optimizations SET request = :doc WHERE id = :id"),
)


def _apply(bind_to_tenant: bool) -> int:
    from services import secret_store

    bind = op.get_bind()
    changed = 0
    for select, update in TARGETS:
        for row in bind.execute(sa.text(select)).mappings().fetchall():
            if "enc://" not in (row["doc"] or ""):
                continue
            try:
                doc = json.loads(row["doc"])
            except ValueError:
                continue
            if bind_to_tenant:
                if not row["tenant_id"]:
                    continue
                doc, n = secret_store.rebind(doc, row["tenant_id"])
            else:
                doc, n = _unbind(doc, secret_store)
            if n:
                params = {"doc": json.dumps(doc), "id": row["id"]}
                if "version" in row:
                    params["version"] = row["version"]
                bind.execute(sa.text(update), params)
                changed += n
    return changed


def _unbind(value, secret_store):
    if secret_store.is_sealed(value):
        if secret_store.sealed_tenant(value) is None:
            return value, 0
        return secret_store.seal(secret_store.unseal(value), tenant_id=""), 1
    if isinstance(value, dict):
        out, n = {}, 0
        for k, v in value.items():
            out[k], c = _unbind(v, secret_store)
            n += c
        return out, n
    if isinstance(value, list):
        pairs = [_unbind(v, secret_store) for v in value]
        return [v for v, _ in pairs], sum(c for _, c in pairs)
    return value, 0


def upgrade() -> None:
    n = _apply(bind_to_tenant=True)
    if n:
        logging.getLogger("alembic").info("Bound %d sealed credential(s) to their workspace.", n)


def downgrade() -> None:
    _apply(bind_to_tenant=False)
