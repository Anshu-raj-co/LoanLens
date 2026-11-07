"""Database commands: ``python -m loanlens.db upgrade`` and ``python -m loanlens.db current``.

``upgrade`` runs Alembic's ``upgrade head`` on ``DATABASE_URL`` (SQLite by default) with
the migrations shipped inside the package, so it works from an installed package (Docker)
as well as from a clone. ``alembic upgrade head`` from the project root does the same.
The database address is never printed, because it can contain a password.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from loanlens.db.engine import DatabaseError, database_url, ensure_schema, get_engine, is_sqlite


def current_revision(url: str) -> str | None:
    """The Alembic revision the database is at (None before the first migration)."""
    with get_engine(url).connect() as conn:
        try:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:  # noqa: BLE001 - no table yet
            return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m loanlens.db", description=__doc__)
    parser.add_argument("command", choices=["upgrade", "current"])
    args = parser.parse_args(argv)
    url = database_url()
    kind = "SQLite" if is_sqlite(url) else "PostgreSQL"
    try:
        if args.command == "upgrade":
            ensure_schema(url)
        revision = current_revision(url)
    except DatabaseError as exc:
        print(f"Database {args.command} failed ({kind}): {exc}", file=sys.stderr)
        return 1
    print(f"{kind} database at revision {revision or 'none'}.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
