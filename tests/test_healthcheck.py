"""Container health checks (python -m loanlens.healthcheck)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from loanlens import healthcheck, jobs, storage
from loanlens.db.engine import session_scope
from loanlens.db.models import BatchWorker


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self.send_response(200 if self.path in ("/health", "/_stcore/health") else 404)
        self.end_headers()

    def log_message(self, *args) -> None:  # silence
        pass


@pytest.fixture
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


@pytest.mark.parametrize("service,port_env", [("api", "LOANLENS_API_PORT"),
                                              ("app", "STREAMLIT_SERVER_PORT")])  # fmt: skip
def test_http_services(local_server, monkeypatch, service, port_env, capsys) -> None:
    monkeypatch.setenv(port_env, str(local_server))
    assert healthcheck.main([service]) == 0
    assert f"{service}: healthy" in capsys.readouterr().out


def test_http_service_down(monkeypatch) -> None:
    monkeypatch.setenv("LOANLENS_API_PORT", "1")
    assert healthcheck.main(["api"]) == 1
    assert not healthcheck.check_http("http://127.0.0.1:1/health", timeout=0.5)


def test_unknown_service(monkeypatch, capsys) -> None:
    monkeypatch.delenv(healthcheck.ENV_SERVICE, raising=False)
    assert healthcheck.main([]) == 1
    assert "Unknown service" in capsys.readouterr().err


def _add_worker(worker_id: str, seconds_ago: float) -> None:
    seen = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    with session_scope(storage.resolve_url()) as session:
        session.add(BatchWorker(id=worker_id, kind=jobs.EXTERNAL, started_at=seen, last_seen=seen))


def test_worker_check_uses_this_hosts_workers(monkeypatch) -> None:
    monkeypatch.setenv(healthcheck.ENV_SERVICE, "worker")
    assert not healthcheck.check_worker(host="box1")
    _add_worker("external-box2-1-aaaa", 1)  # another host
    _add_worker("external-box1-1-bbbb", 600)  # this host, but stale
    assert not healthcheck.check_worker(host="box1")
    _add_worker("external-box1-2-cccc", 1)
    assert healthcheck.check_worker(host="box1")


def test_worker_check_database_down(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/none")
    assert not healthcheck.check_worker()


def test_worker_heartbeat_continues_during_a_job(monkeypatch) -> None:
    """The worker reports in every poll interval, also while a job is running."""
    from loanlens import worker as worker_mod

    settings = jobs.load_job_settings().model_copy(update={"poll_seconds": 0.05})
    w = worker_mod.Worker(jobs.EXTERNAL, storage.resolve_url(), settings)
    seen = []
    real_touch = jobs.touch_worker

    def counting_touch(url, worker_id, kind):
        seen.append(datetime.now(UTC))
        real_touch(url, worker_id, kind)

    def slow_job(url, *, worker_id, settings, artifact):
        threading.Event().wait(0.6)  # a "job" that takes several poll intervals
        w.stop()
        return None

    monkeypatch.setattr(jobs, "touch_worker", counting_touch)
    monkeypatch.setattr(worker_mod, "work_once", slow_job)
    monkeypatch.setattr(worker_mod.model_mod, "load_artifact", lambda: {})
    w.run()
    assert len(seen) >= 4  # start, loop, and heartbeats during the slow job
