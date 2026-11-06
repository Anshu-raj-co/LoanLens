"""Database layer: engine and sessions (``engine``) and tables (``models``)."""

from loanlens.db.engine import (
    DEFAULT_URL,
    ENV_VAR,
    DatabaseError,
    database_url,
    ensure_schema,
    get_engine,
    session_scope,
    sqlite_url,
)
from loanlens.db.models import AuthEvent, Base, BatchSummary, User, batch_rows

__all__ = [
    "DEFAULT_URL",
    "ENV_VAR",
    "AuthEvent",
    "Base",
    "BatchSummary",
    "DatabaseError",
    "batch_rows",
    "database_url",
    "ensure_schema",
    "get_engine",
    "session_scope",
    "sqlite_url",
    "User",
]
