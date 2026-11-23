"""Tenant / project scope for saved connections, which every workspace could list, edit, test and use.

``connections`` gains tenant_id + project_id. An existing connection takes the scope of the pipelines whose
Connection nodes use it (``data.connection_id``) when they all sit in one workspace (the first of their projects,
by id, if several). On a server with a single workspace, unused ones go to its oldest project. A connection used
by several workspaces (or an unused one on a server with several workspaces) stays NULL, which no workspace can
see (as in 0036_scope_traces_evals); ``python manage.py connections`` lists those and assigns them. Pipelines keep working either way: each Connection node carries its own (sealed) config.

Revision ID: 0038_scope_connections
Revises: 0037_sso
Create Date: 2026-11-23
"""
import json
import logging

from alembic import op
import sqlalchemy as sa

revision = "0038_scope_connections"
down_revision = "0037_sso"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)


def _users(bind) -> dict:
    """connection id → {(tenant_id, project_id)} of the apps whose flows reference it."""
    found: dict = {}
    for app_id, tenant_id, project_id, flow in bind.execute(
            sa.text("SELECT id, tenant_id, project_id, flow_data FROM apps")).fetchall():
        try:
            nodes = (json.loads(flow or "{}") or {}).get("nodes", [])
        except (ValueError, AttributeError):
            continue
        for node in nodes if isinstance(nodes, list) else []:
            data = node.get("data") if isinstance(node, dict) else None
            if isinstance(data, dict) and node.get("type") == "connection" and data.get("connection_id"):
                found.setdefault(data["connection_id"], set()).add((tenant_id, project_id))
    return found


def upgrade() -> None:
    with op.batch_alter_table("connections") as batch:
        batch.add_column(sa.Column("tenant_id", KEY, nullable=True))
        batch.add_column(sa.Column("project_id", KEY, nullable=True))

    bind = op.get_bind()
    users = _users(bind)
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    fallback = None
    if len(tenants) == 1:
        row = bind.execute(sa.text("SELECT id FROM projects WHERE tenant_id = :t ORDER BY created_at LIMIT 1"),
                           {"t": tenants[0][0]}).fetchone()
        fallback = (tenants[0][0], row[0]) if row else None
    hidden = 0
    for (conn_id,) in bind.execute(sa.text("SELECT id FROM connections")).fetchall():
        scopes = sorted(s for s in users.get(conn_id, set()) if s[0] and s[1])
        if not scopes:
            scope = fallback
        elif len({t for t, _ in scopes}) == 1:
            scope = scopes[0]
        else:
            scope = None
        if scope:
            bind.execute(sa.text("UPDATE connections SET tenant_id = :t, project_id = :p WHERE id = :id"),
                         {"t": scope[0], "p": scope[1], "id": conn_id})
        else:
            hidden += 1
    if hidden:
        logging.getLogger("alembic").warning(
            "%d saved connection(s) couldn't be matched to one workspace and are hidden until assigned: "
            "run `python manage.py connections` to list and assign them.", hidden)
    op.create_index("idx_connections_scope", "connections", ["tenant_id", "project_id"])


def downgrade() -> None:
    op.drop_index("idx_connections_scope", table_name="connections")
    with op.batch_alter_table("connections") as batch:
        batch.drop_column("project_id")
        batch.drop_column("tenant_id")
