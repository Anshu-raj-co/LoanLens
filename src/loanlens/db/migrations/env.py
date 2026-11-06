"""Alembic environment for LoanLens.

Run from the project root with ``alembic upgrade head`` (uses ``DATABASE_URL`` or the local
SQLite default). The app runs the same migrations itself through
:func:`loanlens.db.engine.ensure_schema`, passing an open connection.

Logging: alembic.ini's logging section is applied only when Alembic runs as its own
command-line tool. ``ensure_schema`` sets the ``skip_logging_config`` attribute so that running
migrations from code never changes the process's logging configuration, and even on the
command line existing loggers are left enabled (``disable_existing_loggers=False``).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from loanlens.db.engine import database_url, get_engine
from loanlens.db.models import Base

config = context.config
target_metadata = Base.metadata

SKIP_LOGGING_CONFIG = "skip_logging_config"


def configure_logging() -> None:
    """Apply alembic.ini's logging setup, but only for the command-line tool."""
    if config.attributes.get(SKIP_LOGGING_CONFIG) or config.config_file_name is None:
        return
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (``alembic upgrade head --sql``)."""
    configure_logging()
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations on a live connection."""
    configure_logging()
    connection = config.attributes.get("connection")
    if connection is not None:  # called from the app: reuse its connection
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    with get_engine(database_url()).connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        conn.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
