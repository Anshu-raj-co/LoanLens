"""Database engine and session handling (SQLAlchemy 2.x; SQLite or PostgreSQL).

The database is chosen by the ``DATABASE_URL`` environment variable. Without it LoanLens
uses a local SQLite file, ``sqlite:///data/loanlens.sqlite`` (relative to the project root).
PostgreSQL URLs (``postgresql://...``) are used through the psycopg driver.

Every connection problem is turned into a :class:`DatabaseError` whose message is plain
English and never contains the URL, a password or a stack trace.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from loanlens.config import PROJECT_ROOT

ENV_VAR = "DATABASE_URL"
DEFAULT_URL = "sqlite:///data/loanlens.sqlite"
CONNECT_TIMEOUT_SECONDS = 5
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

FRIENDLY_MESSAGE = (
    "The results database could not be reached, so the batch summary was not saved or read. "
    "Ask the administrator to check the DATABASE_URL setting and that the database is running."
)


class DatabaseError(RuntimeError):
    """A database problem, with a message that is safe to show to a user."""

    def __init__(self, message: str = FRIENDLY_MESSAGE) -> None:
        super().__init__(message)


def sqlite_url(path: Path) -> str:
    """SQLite URL for a file path (relative paths are under the project root)."""
    path = path if path.is_absolute() else PROJECT_ROOT / path
    return f"sqlite:///{path.as_posix()}"


def normalise_url(url: str) -> str:
    """Make a URL usable: absolute SQLite paths and the psycopg driver for PostgreSQL."""
    try:
        parsed = make_url(url)
    except ArgumentError:
        raise DatabaseError(
            "The DATABASE_URL setting is not a valid database address. Ask the administrator "
            "to check it."
        ) from None
    backend = parsed.get_backend_name()
    if backend == "sqlite":
        db = parsed.database
        if db and db != ":memory:" and not Path(db).is_absolute():
            return sqlite_url(Path(db))
        return url
    if backend == "postgresql" and parsed.drivername in {"postgresql", "postgresql+psycopg2"}:
        return parsed.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    return url


def database_url(default: str | None = None) -> str:
    """The configured database URL: ``DATABASE_URL``, else ``default``, else SQLite."""
    return normalise_url(os.environ.get(ENV_VAR) or default or DEFAULT_URL)


def is_sqlite(url: str) -> bool:
    """True for a SQLite URL."""
    return make_url(url).get_backend_name() == "sqlite"


def sqlite_file(url: str) -> Path | None:
    """The file behind a SQLite URL (None for other databases or in-memory SQLite)."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or parsed.database in (None, "", ":memory:"):
        return None
    return Path(parsed.database)


_engines: dict[str, Engine] = {}


def get_engine(url: str) -> Engine:
    """A shared engine per URL (SQLite files get their folder created first)."""
    url = normalise_url(url)
    if url in _engines:
        return _engines[url]
    file = sqlite_file(url)
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
    # A short connect timeout so an unreachable server gives a quick, friendly error.
    connect_args = {} if is_sqlite(url) else {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    if is_sqlite(url):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    _engines[url] = engine
    return engine


_migrated: set[str] = set()
_migrate_lock = threading.Lock()


def ensure_schema(url: str) -> None:
    """Bring the database up to the latest Alembic migration (once per URL per process)."""
    url = normalise_url(url)
    if url in _migrated:
        return
    from alembic import command
    from alembic.config import Config

    with _migrate_lock:
        if url in _migrated:
            return
        cfg = Config()
        cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
        cfg.attributes["skip_logging_config"] = True  # never touch the process's logging
        try:
            with get_engine(url).begin() as conn:
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "head")
        except SQLAlchemyError:
            raise DatabaseError() from None
        _migrated.add(url)


@contextmanager
def session_scope(url: str) -> Iterator[Session]:
    """A session that commits on success, rolls back on error and hides driver errors."""
    url = normalise_url(url)
    ensure_schema(url)
    factory = sessionmaker(get_engine(url), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise DatabaseError() from None
    finally:
        session.close()


def reset_caches() -> None:
    """Dispose cached engines and forget migrated URLs (tests use this)."""
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
    _migrated.clear()
