"""REST API batch jobs: upload, status, list, cancel and downloads (managers only)."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pandas as pd
import pytest
from app_support import new_session
from fastapi.testclient import TestClient

from loanlens import auth, batch, jobs, worker
from loanlens.api import create_app
from loanlens.api.settings import ApiSettings

FIXTURE = Path(__file__).parent / "fixtures" / "batch_1000.csv"


@pytest.fixture
def client(artifact):
    app = create_app(ApiSettings(auth_limit_per_client=1000, auth_limit_per_account=1000))
    with TestClient(app) as c:
        yield c


def _headers(role: str = auth.MANAGER) -> dict[str, str]:
    return {"Authorization": f"Bearer {new_session(role).token}"}


def _upload(client, headers, data: bytes = b"", name: str = "applicants.csv", **form):
    data = data or FIXTURE.read_bytes()
    return client.post("/v1/batches", headers=headers, files={"file": (name, data, "text/csv")},
                       data=form)  # fmt: skip


def _error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()["error"]
    assert body["code"] == code and body["request_id"] == response.headers["X-Request-ID"]
    return body


def test_batch_endpoints_need_a_manager(client) -> None:
    job_id = str(uuid.uuid4())
    paths = [("get", "/v1/batches"), ("get", f"/v1/batches/{job_id}"),
             ("get", f"/v1/batches/{job_id}/result"), ("get", f"/v1/batches/{job_id}/errors"),
             ("post", f"/v1/batches/{job_id}/cancel")]  # fmt: skip
    applicant = _headers(auth.APPLICANT)
    for method, path in paths:
        _error(getattr(client, method)(path), 401, "not_authenticated")
        _error(getattr(client, method)(path, headers=applicant), 403, "forbidden")
    _error(_upload(client, {}), 401, "not_authenticated")
    _error(_upload(client, applicant), 403, "forbidden")


def test_upload_run_and_download(client, artifact) -> None:
    headers = _headers()
    response = _upload(client, headers, name="../../applicants.csv", product="vehicle")
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["status"] == "queued" and job["filename"] == "applicants.csv"
    assert job["profile"] == "vehicle" and job["result_url"] is None
    assert "upload_path" not in job and "created_by" not in job
    _error(client.get(f"/v1/batches/{job['id']}/result", headers=headers), 409,
           "file_unavailable")  # fmt: skip
    worker.work_once(artifact=artifact)
    done = client.get(f"/v1/batches/{job['id']}", headers=headers).json()
    assert done["status"] == "completed" and done["progress"] == 1.0
    assert (done["rows_processed"], done["rows_skipped"], done["rows_audited"]) == (1000, 20, 980)
    parquet = client.get(done["result_url"], headers=headers)
    assert parquet.status_code == 200
    results = pd.read_parquet(io.BytesIO(parquet.content))
    assert len(results) == 980 and set(results["product"]) == {"vehicle"}
    csv = client.get(done["result_csv_url"], headers=headers)
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert len(pd.read_csv(io.BytesIO(csv.content))) == 980
    errors = client.get(done["errors_url"], headers=headers)
    assert len(pd.read_csv(io.BytesIO(errors.content))) == 20
    listed = client.get("/v1/batches", headers=_headers()).json()  # any manager sees it
    assert listed["count"] == 1 and listed["items"][0]["id"] == job["id"]


def test_cancel_and_unknown_jobs(client) -> None:
    headers = _headers()
    job = _upload(client, headers).json()
    cancelled = client.post(f"/v1/batches/{job['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    _error(client.get(f"/v1/batches/{uuid.uuid4()}", headers=headers), 404, "job_not_found")
    _error(client.get("/v1/batches/not-a-job-id", headers=headers), 422, "validation_error")
    _error(client.get("/v1/batches/..%2F..%2Fetc/result", headers=headers), 404, "not_found")


def test_bad_uploads(client, monkeypatch) -> None:
    headers = _headers()
    _error(_upload(client, headers, product="boat"), 422, "unknown_profile")
    empty = client.post("/v1/batches", headers=headers, files={"file": ("e.csv", b"", "text/csv")})
    _error(empty, 422, "invalid_file")
    monkeypatch.setenv(jobs.ENV_MAX_UPLOAD_MB, "1")
    big = _upload(client, headers, data=b"x" * (1024 * 1024 + 10))
    _error(big, 413, "upload_too_large")
    assert list(Path(jobs.load_job_settings().jobs_dir).iterdir()) == []
    _error(client.post("/v1/batches", headers=headers), 422, "validation_error")


def test_failed_job_reports_its_message(client, artifact) -> None:
    headers = _headers()
    job = _upload(client, headers, data=b"cibil_score\n700\n").json()
    worker.work_once(artifact=artifact)
    done = client.get(f"/v1/batches/{job['id']}", headers=headers).json()
    assert done["status"] == "failed" and "Required columns are missing" in done["error_message"]
    assert done["result_url"] is None


def test_api_starts_an_embedded_worker_when_enabled(monkeypatch, artifact) -> None:
    monkeypatch.setenv(jobs.ENV_EMBEDDED, "1")
    monkeypatch.setenv(jobs.ENV_POLL, "0.05")
    app = create_app(ApiSettings(auth_limit_per_client=1000, auth_limit_per_account=1000))
    with TestClient(app) as c:
        headers = _headers()
        job = _upload(c, headers, data=batch.template_csv()).json()
        for _ in range(600):
            status = c.get(f"/v1/batches/{job['id']}", headers=headers).json()["status"]
            if status == "completed":
                break
            __import__("time").sleep(0.05)
        assert status == "completed"
    assert not worker._embedded  # stopped on shutdown
