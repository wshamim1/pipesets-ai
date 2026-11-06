"""Agent skills, step 1 (plan.md C10): versions and what a skill needs.

* ``skills.version``: bumped on every save; ``skills.required_connections``: connection types the
  skill's tools need (e.g. ``airflow``), JSON. The skill's "when to use" text stays in
  ``description`` and its tools in ``tool_ids`` (the API also names them ``when_to_use`` and
  ``required_tools``).
* ``skill_versions``: a snapshot of the skill at each version, so a run can say which version it
  used and a Skill node can pin one. Existing skills get their version 1 snapshot here.

Revision ID: 0033_agent_skills
Revises: 0032_batch_documents
Create Date: 2026-11-03
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "0033_agent_skills"
down_revision = "0032_batch_documents"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)


def upgrade() -> None:
    with op.batch_alter_table("skills") as batch:
        batch.add_column(sa.Column("version", sa.Integer, nullable=False, server_default="1"))
        batch.add_column(sa.Column("required_connections", sa.UnicodeText, nullable=False, server_default="[]"))
    op.create_table(
        "skill_versions",
        sa.Column("skill_id", KEY, primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("tenant_id", KEY, nullable=False),
        sa.Column("project_id", KEY, nullable=False),
        sa.Column("snapshot", sa.UnicodeText, nullable=False),
        sa.Column("author", KEY, nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("idx_skill_versions_scope", "skill_versions", ["tenant_id", "project_id", "skill_id"])
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT * FROM skills")).mappings().fetchall()
    for r in rows:
        snap = {k: r[k] for k in ("name", "icon", "description", "instructions", "tool_ids", "tags", "category")}
        conn.execute(sa.text(
            "INSERT INTO skill_versions (skill_id, version, tenant_id, project_id, snapshot, author, created_at) "
            "VALUES (:id, 1, :t, :p, :s, :a, :c)"),
            {"id": r["id"], "t": r["tenant_id"], "p": r["project_id"], "s": json.dumps(snap),
             "a": r.get("owner_user_id") or "", "c": r["updated_at"] or r["created_at"] or ""})


def downgrade() -> None:
    op.drop_index("idx_skill_versions_scope", table_name="skill_versions")
    op.drop_table("skill_versions")
    with op.batch_alter_table("skills") as batch:
        batch.drop_column("required_connections")
        batch.drop_column("version")
