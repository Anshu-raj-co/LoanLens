"""Alembic environment for LoanLens.

Run from the project root with ``alembic upgrade head`` (uses ``DATABASE_URL`` or the local
SQLite default). The app runs the same migrations itself through
:func:`loanlens.db.engine.ensure_schema`, passing an open connection.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from loanlens.db.engine import database_url, get_engine
from loanlens.db.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (``alembic upgrade head --sql``)."""
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations on a live connection."""
    connection = config.attributes.get("connection")
    if connection is not None:  # called from the app: reuse its connection
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    if config.config_file_name is not None:  # CLI only: never reconfigure the app's logging
        fileConfig(config.config_file_name)
    with get_engine(database_url()).connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        conn.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
