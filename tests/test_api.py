"""REST API (httpx test client): auth, roles, identical results, audit, limits, logs."""

from __future__ import annotations

import logging
import uuid

import pytest
from app_support import TEST_PASSWORD, new_email, new_session
from fastapi.testclient import TestClient

from loanlens import auth, services
from loanlens import model as model_mod
from loanlens.api import create_app
from loanlens.api.ratelimit import RateLimiter
from loanlens.api.settings import ApiSettings, load_api_settings
from loanlens.auth import settings as auth_settings
from loanlens.config import list_profiles
from loanlens.decision import decide
from loanlens.examples import EXAMPLES

STRONG = EXAMPLES[0][1]
PROTECTED = [
    ("get", "/v1/auth/me", None),
    ("post", "/v1/score", STRONG),
    ("post", "/v1/score/batch", [STRONG]),
    ("get", "/v1/audit", None),
]
PUBLIC = ["/health", "/v1/policies", "/v1/policies/home", "/v1/model", "/docs",
          "/openapi.json"]  # fmt: skip


def _client(settings: ApiSettings | None = None, host: str | None = None) -> TestClient:
    app = create_app(settings or ApiSettings(auth_limit_per_client=1000,
                                             auth_limit_per_account=1000))  # fmt: skip
    if host is None:
        return TestClient(app)

    async def with_host(scope, receive, send):  # simulate another client address
        if scope["type"] == "http":
            scope = {**scope, "client": (host, 50000)}
        await app(scope, receive, send)

    return TestClient(with_host)


@pytest.fixture
def client(artifact):
    with _client() as c:
        yield c


def _headers(role: str = auth.APPLICANT, **kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {new_session(role, **kwargs).token}"}


def _error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()["error"]
    assert body["code"] == code and body["message"]
    assert body["request_id"] == response.headers["X-Request-ID"]
    return body


# ---- Authentication and roles ----------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), PROTECTED)
def test_authentication_required(client, method, path, body) -> None:
    response = getattr(client, method)(path, **({"json": body} if body else {}))
    _error(response, 401, "not_authenticated")
    assert response.headers["WWW-Authenticate"] == "Bearer"
    bad = {"Authorization": "Bearer not-a-token"}
    _error(getattr(client, method)(path, headers=bad, **({"json": body} if body else {})),
           401, "not_authenticated")  # fmt: skip


@pytest.mark.parametrize(
    ("method", "path", "body", "applicant_status"),
    [("get", "/v1/auth/me", None, 200), ("post", "/v1/score", STRONG, 200),
     ("post", "/v1/score/batch", [STRONG], 403), ("get", "/v1/audit", None, 403)],
)  # fmt: skip
def test_roles_for_every_endpoint(client, method, path, body, applicant_status) -> None:
    kwargs = {"json": body} if body else {}
    as_applicant = getattr(client, method)(path, headers=_headers(), **kwargs)
    assert as_applicant.status_code == applicant_status, as_applicant.text
    if applicant_status == 403:
        _error(as_applicant, 403, "forbidden")
    as_manager = getattr(client, method)(path, headers=_headers(auth.MANAGER), **kwargs)
    assert as_manager.status_code == 200, as_manager.text


@pytest.mark.parametrize("path", PUBLIC)
def test_public_endpoints(client, path) -> None:
    assert client.get(path).status_code == 200


def test_must_change_password_blocks_all_but_me(client) -> None:
    headers = _headers(auth.MANAGER, must_change_password=True)
    assert client.get("/v1/auth/me", headers=headers).json()["must_change_password"] is True
    _error(client.post("/v1/score", headers=headers, json=STRONG), 403,
           "password_change_required")  # fmt: skip


def test_register_login_me(client) -> None:
    email = new_email()
    created = client.post("/v1/auth/register", json={"email": email.upper(),
                                                     "password": TEST_PASSWORD})  # fmt: skip
    assert created.status_code == 201
    assert created.json()["user"] == {"email": email, "role": "applicant",
                                      "must_change_password": False}  # fmt: skip
    _error(client.post("/v1/auth/register", json={"email": email, "password": TEST_PASSWORD}),
           409, "account_conflict")  # fmt: skip
    weak = client.post("/v1/auth/register", json={"email": new_email(), "password": "short"})
    assert any("at least 10" in d["message"] for d in _error(weak, 422, "invalid_input")["details"])
    login = client.post("/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200 and login.json()["token_type"] == "bearer"
    me = client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert me.json()["email"] == email
    for creds in ({"email": email, "password": "wrong-password"},
                  {"email": "nobody@example.com", "password": TEST_PASSWORD}):  # fmt: skip
        body = _error(client.post("/v1/auth/login", json=creds), 401, "login_failed")
        assert body["message"] == "Incorrect email or password"


def test_password_change_invalidates_api_token(client) -> None:
    signed_in = new_session()
    headers = {"Authorization": f"Bearer {signed_in.token}"}
    assert client.get("/v1/auth/me", headers=headers).status_code == 200
    auth.change_password(signed_in.principal, TEST_PASSWORD, "a new long passphrase")
    _error(client.get("/v1/auth/me", headers=headers), 401, "not_authenticated")


# ---- Scoring ---------------------------------------------------------------------------------

DECISION_FIELDS = ("status", "probability", "borderline", "reasons", "positive_factors",
                   "what_would_change", "rule_results", "warnings", "model_version", "profile",
                   "policy_version", "policy_hash")  # fmt: skip


@pytest.mark.parametrize("profile", list_profiles())
@pytest.mark.parametrize("index", range(len(EXAMPLES)))
def test_api_result_identical_to_service_layer(client, artifact, profile, index) -> None:
    values = EXAMPLES[index][1]
    response = client.post("/v1/score", headers=_headers(), json={**values, "product": profile})
    assert response.status_code == 200, response.text
    body = response.json()
    expected = decide(values, profile=profile, artifact=artifact).model_dump(mode="json")
    for field in DECISION_FIELDS:
        assert body[field] == expected[field], field
    for field in ("likelihood_band", "likelihood", "request_id", "audit_id"):
        assert body[field]
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_batch_results_match_single_results(client, artifact) -> None:
    items = [{**values, "product": p} for _t, values, _ in EXAMPLES for p in list_profiles()]
    response = client.post("/v1/score/batch", headers=_headers(auth.MANAGER), json=items)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == len(items) == len(body["results"])
    for item, result in zip(items, body["results"], strict=True):
        values = {k: v for k, v in item.items() if k != "product"}
        expected = decide(values, profile=item["product"], artifact=artifact)
        assert result["status"] == expected.status and result["profile"] == item["product"]
        assert result["probability"] == pytest.approx(expected.probability, abs=1e-6)
        assert [r["code"] for r in result["reasons"]] == [r.code for r in expected.reasons]
        assert result["request_id"] == body["request_id"]


def test_score_validation_and_unknown_product(client) -> None:
    body = _error(client.post("/v1/score", headers=_headers(), json={"cibil_score": "abc"}),
                  422, "validation_error")  # fmt: skip
    fields = {d["field"] for d in body["details"]}
    assert {"cibil_score", "income_annum"} <= fields
    assert "abc" not in str(body)  # submitted values are not echoed
    _error(client.post("/v1/score", headers=_headers(), json={**STRONG, "product": "boat"}),
           422, "unknown_profile")  # fmt: skip


def test_batch_limits(artifact) -> None:
    with _client(ApiSettings(max_batch=2)) as client:
        headers = _headers(auth.MANAGER)
        _error(client.post("/v1/score/batch", headers=headers, json=[STRONG] * 3), 413,
               "batch_too_large")  # fmt: skip
        _error(client.post("/v1/score/batch", headers=headers, json=[]), 422, "validation_error")
        assert client.post("/v1/score/batch", headers=headers, json=[STRONG] * 2).status_code == 200


def test_default_max_batch(monkeypatch) -> None:
    assert load_api_settings({}).max_batch == 1000
    assert load_api_settings({"LOANLENS_API_MAX_BATCH": "50"}).max_batch == 50
    with pytest.raises(auth.ConfigurationError, match="LOANLENS_API_MAX_BATCH"):
        load_api_settings({"LOANLENS_API_MAX_BATCH": "0"})


# ---- Audit -----------------------------------------------------------------------------------


def test_api_decisions_are_audited_with_request_id(client) -> None:
    applicant = new_session()
    headers = {"Authorization": f"Bearer {applicant.token}", "X-Request-ID": "req-123.abc"}
    response = client.post("/v1/score", headers=headers, json=STRONG)
    assert response.headers["X-Request-ID"] == "req-123.abc"
    [record] = services.my_history(applicant.principal)
    assert record["request_id"] == "req-123.abc" and record["channel"] == "api"
    assert record["id"] == response.json()["audit_id"]
    assert record["user_ref"] == applicant.principal.audit_ref
    unsafe = client.post("/v1/score", headers={**headers, "X-Request-ID": "bad id\n!"},
                         json=STRONG)  # fmt: skip
    assert unsafe.headers["X-Request-ID"] != "bad id\n!"  # replaced by a generated one


def test_api_batch_is_audited(client) -> None:
    manager = new_session(auth.MANAGER)
    response = client.post("/v1/score/batch", headers={"Authorization": f"Bearer {manager.token}"},
                           json=[STRONG, {**STRONG, "product": "home"}])  # fmt: skip
    rows = services.audit_export(manager.principal)
    assert len(rows) == 2 and {r["batch_id"] for r in rows} == {response.json()["batch_id"]}
    assert {r["channel"] for r in rows} == {"api"}


def test_audit_endpoint_pagination_and_filters(client, artifact) -> None:
    applicant = new_session().principal
    for _t, values, _ in EXAMPLES:
        services.score_applicant(applicant, values, artifact=artifact)
    headers = _headers(auth.MANAGER)
    first = client.get("/v1/audit", params={"page_size": 4}, headers=headers).json()
    assert first["total"] == 6 and len(first["items"]) == 4 and first["page"] == 1
    second = client.get("/v1/audit", params={"page_size": 4, "page": 2}, headers=headers).json()
    assert len(second["items"]) == 2
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    rejected = client.get("/v1/audit", params={"status": "Rejected"}, headers=headers).json()
    assert rejected["total"] == rejected["counts"]["rejected"] == 4
    for params in ({"channel": "batch"}, {"profile": "home"}, {"model_version": "0.0.1"},
                   {"policy_version": "9.9.9"}, {"date_from": "2999-01-01"}):  # fmt: skip
        assert client.get("/v1/audit", params=params, headers=headers).json()["total"] == 0
    item = first["items"][0]
    assert set(item["inputs"]) == {"cibil_score", "income_annum", "loan_amount", "loan_term",
                                   "residential_assets_value", "commercial_assets_value",
                                   "luxury_assets_value", "bank_asset_value"}  # fmt: skip
    for params in ({"page_size": 501}, {"page": 0}, {"status": "Maybe"}, {"channel": "email"},
                   {"date_from": "2026-02-02", "date_to": "2026-01-01"}):  # fmt: skip
        _error(client.get("/v1/audit", params=params, headers=headers), 422, "validation_error")


# ---- Reference, health, docs -----------------------------------------------------------------


def test_policies_and_model(client) -> None:
    profiles = client.get("/v1/policies").json()
    assert [p["profile"] for p in profiles] == list_profiles()
    assert all(len(p["policy_hash"]) == 64 for p in profiles)
    home = client.get("/v1/policies/HOME").json()
    assert home["profile"] == "home" and home["rules"]["max_loan_term_years"]["value"] == 30
    _error(client.get("/v1/policies/boat"), 404, "unknown_profile")
    model_info = client.get("/v1/model").json()
    assert model_info["version"] == "1.0.0" and model_info["cv_metrics"]["roc_auc"] > 0.99


def test_model_unavailable(client, monkeypatch) -> None:
    from loanlens import registry

    def missing(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(registry, "resolve_artifact", missing)
    _error(client.get("/v1/model"), 503, "model_unavailable")


def test_openapi_schema(client) -> None:
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])
    assert {"/v1/auth/register", "/v1/auth/login", "/v1/auth/me", "/v1/score",
            "/v1/score/batch", "/v1/policies", "/v1/policies/{profile}", "/v1/model",
            "/v1/audit", "/health", "/ready"} <= paths  # fmt: skip
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    assert "ScoreResponse" in schema["components"]["schemas"]
    assert client.get("/docs").status_code == 200


def test_health_and_ready(client, monkeypatch) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json()["checks"] == {"database": "ok", "model": "ok"}

    def missing():
        raise FileNotFoundError

    monkeypatch.setattr(model_mod, "load_artifact", missing)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/none")
    not_ready = client.get("/ready")
    assert not_ready.status_code == 503
    unavailable = {"database": "unavailable", "model": "unavailable"}
    assert not_ready.json() == {"status": "not_ready", "checks": unavailable}


def test_errors_have_one_shape(client, monkeypatch) -> None:
    _error(client.get("/v1/nothing"), 404, "not_found")
    _error(client.put("/v1/score"), 405, "method_not_allowed")
    monkeypatch.setattr(services, "score_applicant", lambda *a, **k: 1 / 0)
    body = _error(client.post("/v1/score", headers=_headers(), json=STRONG), 500,
                  "internal_error")  # fmt: skip
    assert "ZeroDivision" not in str(body)  # no stack trace or exception detail


def test_database_down_is_503(client, monkeypatch) -> None:
    headers = _headers()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/none")
    body = _error(client.get("/v1/auth/me", headers=headers), 503, "database_unavailable")
    assert "127.0.0.1" not in body["message"]


def test_production_without_secret_refuses_to_start(monkeypatch) -> None:
    monkeypatch.delenv(auth_settings.ENV_SECRET)
    monkeypatch.setenv(auth_settings.ENV_MODE, "production")
    with pytest.raises(auth.ConfigurationError, match="will not start"), _client():
        pass


# ---- CORS ------------------------------------------------------------------------------------


def test_cors_off_by_default(client) -> None:
    response = client.get("/health", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("LOANLENS_API_CORS_ORIGINS", "https://app.example.com, https://b.example")
    settings = load_api_settings()
    assert settings.cors_origins == ("https://app.example.com", "https://b.example")
    with _client(settings) as client:
        allowed = client.get("/health", headers={"Origin": "https://app.example.com"})
        assert allowed.headers["access-control-allow-origin"] == "https://app.example.com"
        other = client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in other.headers


# ---- Rate limiting ---------------------------------------------------------------------------


def test_rate_limit_per_client_address(artifact) -> None:
    settings = ApiSettings(auth_limit_per_client=3, auth_limit_per_account=100)
    with _client(settings, host="10.0.0.1") as client:
        for _ in range(3):  # three different accounts from one client
            creds = {"email": new_email(), "password": "wrong-password-1"}
            assert client.post("/v1/auth/login", json=creds).status_code == 401
        blocked = client.post("/v1/auth/login", json={"email": new_email(),
                                                      "password": "x" * 12})  # fmt: skip
        _error(blocked, 429, "rate_limited")
        assert int(blocked.headers["Retry-After"]) >= 1
        _error(client.post("/v1/auth/register", json={"email": new_email(),
                                                      "password": TEST_PASSWORD}),
               429, "rate_limited")  # fmt: skip
    app_settings = settings
    with _client(app_settings, host="10.0.0.2") as other:  # a fresh server process: reset
        assert (
            other.post(
                "/v1/auth/login", json={"email": new_email(), "password": "x" * 12}
            ).status_code
            == 401
        )


def test_rate_limit_per_account(artifact) -> None:
    settings = ApiSettings(auth_limit_per_client=100, auth_limit_per_account=2)
    app = create_app(settings)
    email = new_session().principal.email

    def from_host(host):
        async def wrapped(scope, receive, send):
            if scope["type"] == "http":
                scope = {**scope, "client": (host, 50000)}
            await app(scope, receive, send)

        return TestClient(wrapped)

    with from_host("10.0.0.1") as a, from_host("10.0.0.2") as b, from_host("10.0.0.3") as c:
        assert (
            a.post("/v1/auth/login", json={"email": email, "password": "wrong-pass-1"}).status_code
            == 401
        )
        second = {"email": email.upper(), "password": "wrong-pass-2"}
        assert b.post("/v1/auth/login", json=second).status_code == 401
        _error(
            c.post("/v1/auth/login", json={"email": email, "password": TEST_PASSWORD}),
            429,
            "rate_limited",
        )  # the account is throttled across client addresses
        other = c.post("/v1/auth/login", json={"email": new_session().principal.email,
                                               "password": TEST_PASSWORD})  # fmt: skip
        assert other.status_code == 200


def test_rate_limiter_window() -> None:
    now = [0.0]
    limiter = RateLimiter(2, 60, clock=lambda: now[0])
    assert limiter.hit("k") is None and limiter.hit("k") is None
    assert limiter.hit("k") == pytest.approx(60)
    now[0] = 30
    assert limiter.hit("k") == pytest.approx(30)
    assert limiter.hit("other") is None
    now[0] = 60.5
    assert limiter.hit("k") is None  # the oldest hit left the window
    for i in range(1000):  # periodic purge keeps memory bounded
        now[0] = 200 + i * 61
        limiter.hit(f"key{i}")
    assert len(limiter._hits) < 50
    limiter.reset()
    assert limiter._hits == {}


# ---- Logs ------------------------------------------------------------------------------------


def test_logs_are_json_without_personal_data(client) -> None:
    import json

    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = Capture()
    api_logger = logging.getLogger("loanlens.api")
    api_logger.addHandler(handler)
    try:
        email, password = new_email(), "Secret-" + uuid.uuid4().hex
        created = client.post("/v1/auth/register", json={"email": email, "password": password})
        token = created.json()["access_token"]
        client.post("/v1/auth/login", json={"email": email, "password": "wrong-" + password})
        client.post("/v1/score", headers={"Authorization": f"Bearer {token}"}, json=STRONG)
        client.get(
            "/v1/audit", params={"profile": email}, headers={"Authorization": f"Bearer {token}"}
        )
    finally:
        api_logger.removeHandler(handler)
    formatter = next(h for h in api_logger.handlers if getattr(h, "_loanlens", False)).formatter
    lines = [formatter.format(r) for r in records]
    assert len(lines) >= 4
    for line in lines:
        entry = json.loads(line)
        assert {"ts", "level", "event", "request_id"} <= set(entry)
        for secret in (email, password, token, "testclient", str(STRONG["income_annum"])):
            assert secret not in line
    assert any(json.loads(line).get("path") == "/v1/score" for line in lines)
