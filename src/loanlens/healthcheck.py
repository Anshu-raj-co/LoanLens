"""Container health checks: ``python -m loanlens.healthcheck api|app|worker``.

Used by the Docker image's ``HEALTHCHECK`` (the service is taken from
``LOANLENS_SERVICE`` when no argument is given). Exit code 0 means healthy, 1 unhealthy.

* ``api``: ``GET /health`` on the local API answers 200.
* ``app``: Streamlit's ``/_stcore/health`` answers 200.
* ``worker``: a worker process on this host reported in to the database recently (workers
  report every poll interval, also while a job runs).
"""

from __future__ import annotations

import os
import socket
import sys
import urllib.request
from datetime import UTC, datetime, timedelta

ENV_SERVICE = "LOANLENS_SERVICE"
ENDPOINTS = {
    "api": "http://127.0.0.1:{port}/health",
    "app": "http://127.0.0.1:{port}/_stcore/health",
}
DEFAULT_PORTS = {"api": 8000, "app": 8501}
PORT_ENV = {"api": "LOANLENS_API_PORT", "app": "STREAMLIT_SERVER_PORT"}
WORKER_WITHIN_SECONDS = 60
TIMEOUT_SECONDS = 4


def check_http(url: str, timeout: float = TIMEOUT_SECONDS) -> bool:
    """True when ``url`` answers 200."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - local
            return response.status == 200
    except (OSError, ValueError):
        return False


def check_worker(within_seconds: float = WORKER_WITHIN_SECONDS, host: str | None = None) -> bool:
    """True when a worker on this host reported in during the last ``within_seconds``."""
    from sqlalchemy import select

    from loanlens import jobs, storage
    from loanlens.db.engine import session_scope
    from loanlens.db.models import BatchWorker

    prefix = f"{jobs.EXTERNAL}-{(host or socket.gethostname())[:20]}-"
    cutoff = datetime.now(UTC) - timedelta(seconds=within_seconds)
    try:
        with session_scope(storage.resolve_url()) as session:
            seen = session.execute(
                select(BatchWorker.last_seen).where(BatchWorker.id.startswith(prefix))
            ).scalars().all()  # fmt: skip
    except Exception:  # noqa: BLE001 - database unreachable means unhealthy
        return False
    return any(_aware(t) >= cutoff for t in seen)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def check(service: str) -> bool:
    """Run the check for one service."""
    if service == "worker":
        return check_worker()
    if service in ENDPOINTS:
        port = os.environ.get(PORT_ENV[service], "").strip() or DEFAULT_PORTS[service]
        return check_http(ENDPOINTS[service].format(port=port))
    raise ValueError(f"Unknown service {service!r}; use api, app or worker.")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    service = (args[0] if args else os.environ.get(ENV_SERVICE, "")).strip().lower()
    try:
        healthy = check(service)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{service}: {'healthy' if healthy else 'unhealthy'}")
    return 0 if healthy else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
