import os
import sys

from alembic import context

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import DATABASE_URL, migration_connection  # noqa: E402

config = context.config


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # db.migrate() hands over its connection; the `alembic` CLI opens its own.
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return
    with migration_connection() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
