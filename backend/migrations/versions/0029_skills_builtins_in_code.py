"""Built-in skills move out of the ``skills`` table into code (routers/skills.py BUILTIN_SKILLS).

They were seeded once, under whichever tenant listed skills first, and every tenant could then edit
or delete them for everyone. Remove those rows; the API serves the built-ins read-only from code.

Revision ID: 0029_skills_builtins_in_code
Revises: 0028_tool_packages
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0029_skills_builtins_in_code"
down_revision = "0028_tool_packages"
branch_labels = None
depends_on = None

BUILTIN_IDS = ("skill_data_analysis", "skill_code_reviewer", "skill_research_synthesis")


def upgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM skills WHERE id IN :ids").bindparams(
        sa.bindparam("ids", expanding=True)), {"ids": list(BUILTIN_IDS)})


def downgrade() -> None:
    pass   # the API no longer reads built-ins from the table
