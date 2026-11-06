"""LoanLens REST API (FastAPI), versioned under ``/v1``.

Run with ``uvicorn loanlens.api.app:app`` (or ``python -m loanlens.api``). OpenAPI docs are
at ``/docs``. Every endpoint goes through the same protected service layer as the
Streamlit app (:mod:`loanlens.services` and :mod:`loanlens.auth`), so results are identical
and roles are checked in one place.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, File, Form, Path, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from loanlens import auth, jobs, registry, services, storage, worker
from loanlens import model as model_mod
from loanlens.api.ratelimit import RateLimiter
from loanlens.api.schemas import (
    AuditItem,
    AuditResponse,
    BatchJobList,
    BatchJobOut,
    BatchResponse,
    Credentials,
    ErrorResponse,
    ModelInfo,
    PolicySummary,
    ScoreRequest,
    ScoreResponse,
    TokenResponse,
    UserOut,
)
from loanlens.api.settings import ApiSettings, load_api_settings
from loanlens.audit import AuditFilters
from loanlens.batch import BatchError
from loanlens.config import UnknownProfileError, list_profiles, load_profile
from loanlens.db.engine import DatabaseError, ensure_schema, get_engine
from loanlens.formatting import likelihood_band, likelihood_text
from loanlens.schema import DecisionResult, ValidationFailure

logger = logging.getLogger("loanlens.api")
REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ERRORS = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
          422: {"model": ErrorResponse}, 429: {"model": ErrorResponse},
          503: {"model": ErrorResponse}}  # fmt: skip


# ---- Logging ---------------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Callers pass only non-personal fields in ``extra``."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(entry, default=str)


def _configure_logging() -> None:
    if not any(getattr(h, "_loanlens", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._loanlens = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# ---- Errors ----------------------------------------------------------------------------------


class ApiError(Exception):
    """An error with an HTTP status, a stable code and a plain message."""

    def __init__(
        self, status: int, code: str, message: str, details: list | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:  # fmt: skip
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details, self.headers = details, headers


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or services.new_request_id()


def _error(
    request: Request, status: int, code: str, message: str, details: list | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:  # fmt: skip
    rid = _request_id(request)
    body: dict[str, Any] = {"code": code, "message": message, "request_id": rid}
    if details is not None:
        body["details"] = details
    return JSONResponse(
        {"error": body}, status_code=status,
        headers={REQUEST_ID_HEADER: rid, **(headers or {})},
    )  # fmt: skip


def _field_errors(errors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Validation details without the submitted values."""
    out = []
    for err in errors:
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
        out.append({"field": ".".join(loc) or "body", "message": str(err.get("msg", ""))})
    return out


def _install_error_handlers(app: FastAPI) -> None:
    def handle(exc_type, status: int, code: str, message=None, headers=None):
        async def handler(request: Request, exc: Exception) -> JSONResponse:
            return _error(request, status, code, message or str(exc), headers=headers)

        app.add_exception_handler(exc_type, handler)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _error(request, exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(
            request, 422, "validation_error", "Some fields are missing or not valid.",
            _field_errors(exc.errors()),
        )  # fmt: skip

    @app.exception_handler(auth.InputError)
    async def _input(request: Request, exc: auth.InputError) -> JSONResponse:
        details = [{"field": "body", "message": p} for p in exc.problems]
        return _error(request, 422, "invalid_input", "The details are not valid.", details)

    @app.exception_handler(services.InvalidRecords)
    async def _records(request: Request, exc: services.InvalidRecords) -> JSONResponse:
        details = [
            {"index": i, "field": e.field, "message": e.message}
            for i, failure in exc.errors.items()
            for e in failure.errors
        ]
        return _error(request, 422, "invalid_records", str(exc), details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed"}
        return _error(request, exc.status_code, codes.get(exc.status_code, "http_error"),
                      str(exc.detail))  # fmt: skip

    handle(auth.InvalidSession, 401, "not_authenticated", headers={"WWW-Authenticate": "Bearer"})
    handle(auth.LoginFailed, 401, "login_failed", headers={"WWW-Authenticate": "Bearer"})
    handle(auth.PermissionDenied, 403, "forbidden")
    handle(auth.AccountError, 409, "account_conflict")
    handle(UnknownProfileError, 422, "unknown_profile")
    handle(auth.ConfigurationError, 503, "configuration_error")
    handle(DatabaseError, 503, "database_unavailable")
    handle(jobs.JobNotFound, 404, "job_not_found")
    handle(jobs.JobFileUnavailable, 409, "file_unavailable")
    handle(jobs.UploadTooLarge, 413, "upload_too_large")
    handle(BatchError, 422, "invalid_file")


# ---- Dependencies ----------------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False, description="The access_token from /v1/auth/login")


def signed_in(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> auth.Principal:
    """The principal behind the bearer token (401 without a valid, current token)."""
    if credentials is None or not credentials.credentials:
        raise auth.InvalidSession("Sign in first and send 'Authorization: Bearer <token>'.")
    principal = auth.principal_from_token(credentials.credentials)
    request.state.role = principal.role
    return principal


def ready_principal(principal: Annotated[auth.Principal, Depends(signed_in)]) -> auth.Principal:
    """As :func:`signed_in`, but refuses accounts that must change their password first."""
    if principal.must_change_password:
        raise ApiError(
            403, "password_change_required",
            "This account must change its password first (Account page in the app).",
        )  # fmt: skip
    return principal


Principal = Annotated[auth.Principal, Depends(ready_principal)]


def audit_filters(
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = Query(None, pattern="^(Approved|Rejected)$"),
    profile: str | None = Query(None, max_length=32),
    channel: str | None = Query(None, pattern="^(ui|api|batch)$"),
    model_version: str | None = Query(None, max_length=64),
    policy_version: str | None = Query(None, max_length=32),
) -> AuditFilters:
    """Audit filters from query parameters (dates are inclusive, UTC)."""
    try:
        return AuditFilters(
            date_from=date_from, date_to=date_to, status=status, profile=profile,
            channel=channel, model_version=model_version, policy_version=policy_version,
        )  # fmt: skip
    except ValueError:
        raise ApiError(
            422, "validation_error", "The start date must not be after the end date."
        ) from None


# ---- Helpers ---------------------------------------------------------------------------------


def _score_response(result: DecisionResult, request_id: str, audit_id: str) -> ScoreResponse:
    bands = load_profile(result.profile).display.probability_bands
    return ScoreResponse(
        **result.model_dump(),
        likelihood_band=likelihood_band(result.probability, bands),
        likelihood=likelihood_text(result.probability, bands),
        request_id=request_id,
        audit_id=audit_id,
    )


def _job_out(job: jobs.JobView) -> BatchJobOut:
    base = f"/v1/batches/{job.id}"
    links: dict[str, str] = {}
    if job.status == jobs.COMPLETED and job.has_result:
        links = {"result_url": f"{base}/result", "result_csv_url": f"{base}/result?format=csv"}
        if job.has_errors:
            links["errors_url"] = f"{base}/errors"
    fields = {k: getattr(job, k) for k in BatchJobOut.model_fields if hasattr(job, k)}
    return BatchJobOut(**fields, progress=job.fraction, **links)


JobId = Annotated[str, Path(pattern=jobs.JOB_ID_PATTERN, description="Batch job id")]


def _token_response(signed: auth.SignedIn) -> TokenResponse:
    p = signed.principal
    return TokenResponse(
        access_token=signed.token, expires_at=signed.expires_at,
        user=UserOut(email=p.email, role=p.role, must_change_password=p.must_change_password),
    )  # fmt: skip


def _rate_limit(request: Request, email: str) -> None:
    """Per client address, then per account; raise 429 when either limit is reached."""
    client = request.client.host if request.client else "unknown"
    account = hashlib.sha256((email or "").strip().lower().encode()).hexdigest()
    for limiter, key in (
        (request.app.state.client_limiter, f"client:{client}"),
        (request.app.state.account_limiter, f"account:{account}"),
    ):
        wait = limiter.hit(key)
        if wait is not None:
            seconds = max(1, int(wait + 0.999))
            raise ApiError(
                429, "rate_limited", f"Too many attempts. Try again in {seconds} seconds.",
                headers={"Retry-After": str(seconds)},
            )  # fmt: skip


# ---- App -------------------------------------------------------------------------------------


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Build the API. Settings come from the environment unless given."""
    settings = settings or load_api_settings()
    _configure_logging()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        auth.signing_key()  # refuses to start in production or hosted mode without a secret
        auth.load_settings()
        job_settings = jobs.load_job_settings()
        try:
            auth.bootstrap_from_env()
        except DatabaseError:
            logger.warning("bootstrap skipped: database unavailable")
        if job_settings.embedded_worker:
            try:
                worker.ensure_worker(settings=job_settings)
            except DatabaseError:
                logger.warning("embedded worker not started: database unavailable")
        yield
        worker.stop_embedded()

    app = FastAPI(
        title="LoanLens API",
        version="1.0.0",
        summary="Explainable loan pre-eligibility (prototype; approval decision, not default).",
        description=(
            "Independent proof of concept. Predicts the approval decision recorded in a public "
            "synthetic dataset, not default. Every policy threshold is an illustrative "
            "placeholder. Sign in with `/v1/auth/login` and send `Authorization: Bearer "
            "<access_token>`."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.client_limiter = RateLimiter(
        settings.auth_limit_per_client, settings.auth_window_seconds
    )
    app.state.account_limiter = RateLimiter(
        settings.auth_limit_per_account, settings.auth_window_seconds
    )
    _install_error_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        rid = incoming if _SAFE_REQUEST_ID.match(incoming) else services.new_request_id()
        request.state.request_id = rid
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - never a stack trace in the response
            logger.error("unhandled_error", extra={"fields": {
                "request_id": rid, "error_type": type(exc).__name__}})  # fmt: skip
            response = _error(request, 500, "internal_error", "Something went wrong.")
        response.headers[REQUEST_ID_HEADER] = rid
        route = request.scope.get("route")
        logger.info("request", extra={"fields": {
            "request_id": rid, "method": request.method,
            "path": getattr(route, "path", "unmatched"), "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            "role": getattr(request.state, "role", None),
        }})  # fmt: skip
        return response

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type",
                                                          REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
        )  # fmt: skip

    # ---- Health -------------------------------------------------------------------------

    @app.get("/health", tags=["health"], summary="Liveness")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"], summary="Readiness: database reachable, model loaded")
    def ready() -> JSONResponse:
        checks = {"database": "ok", "model": "ok"}
        try:
            url = storage.resolve_url()
            ensure_schema(url)
            with get_engine(url).connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - report, never raise
            checks["database"] = "unavailable"
        try:
            model_mod.load_artifact()
        except Exception:  # noqa: BLE001
            checks["model"] = "unavailable"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ready" if ok else "not_ready", "checks": checks},
            status_code=200 if ok else 503,
        )

    # ---- Auth ---------------------------------------------------------------------------

    @app.post("/v1/auth/register", tags=["auth"], status_code=201, response_model=TokenResponse,
              responses={**ERRORS, 409: {"model": ErrorResponse}})  # fmt: skip
    def register(request: Request, body: Credentials) -> TokenResponse:
        """Create an applicant account (managers cannot sign up) and return a token."""
        _rate_limit(request, body.email)
        return _token_response(auth.register_applicant(body.email, body.password))

    @app.post("/v1/auth/login", tags=["auth"], response_model=TokenResponse, responses=ERRORS)
    def login(request: Request, body: Credentials) -> TokenResponse:
        """Sign in. Every failure returns the same message."""
        _rate_limit(request, body.email)
        return _token_response(auth.sign_in(body.email, body.password))

    @app.get("/v1/auth/me", tags=["auth"], response_model=UserOut, responses=ERRORS)
    def me(principal: Annotated[auth.Principal, Depends(signed_in)]) -> UserOut:
        """The signed-in account."""
        return UserOut(
            email=principal.email, role=principal.role,
            must_change_password=principal.must_change_password,
        )  # fmt: skip

    # ---- Scoring ------------------------------------------------------------------------

    @app.post("/v1/score", tags=["score"], response_model=ScoreResponse, responses=ERRORS)
    def score(request: Request, principal: Principal, body: ScoreRequest) -> ScoreResponse:
        """Score one application (any signed-in user). The decision is audited."""
        scored = services.score_applicant(
            principal, body.model_dump(exclude={"product"}), product=body.product,
            channel=services.API, request_id=_request_id(request),
        )  # fmt: skip
        if isinstance(scored, ValidationFailure):  # pragma: no cover - the body is validated
            raise ApiError(422, "validation_error", "Some fields are not valid.",
                           [e.model_dump() for e in scored.errors])  # fmt: skip
        return _score_response(scored.result, scored.request_id, scored.audit_id)

    @app.post("/v1/score/batch", tags=["score"], response_model=BatchResponse,
              responses={**ERRORS, 413: {"model": ErrorResponse}})  # fmt: skip
    def score_batch(
        request: Request, principal: Principal, body: Annotated[list[ScoreRequest], Body()]
    ) -> BatchResponse:
        """Score a list of applications (managers only). Every decision is audited."""
        auth.require_role(principal, auth.MANAGER)
        limit = request.app.state.settings.max_batch
        if not body:
            raise ApiError(422, "validation_error", "Send at least one applicant.")
        if len(body) > limit:
            raise ApiError(413, "batch_too_large",
                           f"Send at most {limit} applicants per request.")  # fmt: skip
        run = services.score_records(
            principal, [item.model_dump(exclude={"product"}) for item in body],
            products=[item.product for item in body], channel=services.API,
            request_id=_request_id(request),
        )  # fmt: skip
        results = [
            _score_response(res, run.request_id, audit_id)
            for res, audit_id in zip(run.results, run.audit_ids, strict=True)
        ]
        return BatchResponse(
            batch_id=run.batch_id, request_id=run.request_id, count=len(results),
            results=results,
        )  # fmt: skip

    # ---- Batch jobs ---------------------------------------------------------------------

    @app.post("/v1/batches", tags=["batches"], status_code=202, response_model=BatchJobOut,
              responses={**ERRORS, 413: {"model": ErrorResponse}})  # fmt: skip
    def submit_batch(
        principal: Principal,
        file: Annotated[UploadFile, File(description="CSV or Parquet file")],
        product: Annotated[str, Form(max_length=32)] = "personal",
        include_positive: Annotated[bool, Form()] = False,
    ) -> BatchJobOut:
        """Upload a CSV or Parquet file as a background job (managers only).

        The job runs in a worker; poll `GET /v1/batches/{id}` and download the results when
        it has completed. Every scored row is recorded in the audit trail.
        """
        job = services.submit_batch_job(
            principal, file.file, file.filename or "upload", product=product,
            include_positive=include_positive,
        )  # fmt: skip
        return _job_out(job)

    @app.get("/v1/batches", tags=["batches"], response_model=BatchJobList, responses=ERRORS)
    def list_batches(
        principal: Principal, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> BatchJobList:
        """Recent batch jobs of all managers, newest first (managers only)."""
        items = [_job_out(j) for j in services.list_batch_jobs(principal, limit)]
        return BatchJobList(count=len(items), items=items)

    @app.get("/v1/batches/{job_id}", tags=["batches"], response_model=BatchJobOut,
             responses={**ERRORS, 404: {"model": ErrorResponse}})  # fmt: skip
    def get_batch(principal: Principal, job_id: JobId) -> BatchJobOut:
        """One batch job with its progress and counts (managers only)."""
        return _job_out(services.get_batch_job(principal, job_id))

    @app.post("/v1/batches/{job_id}/cancel", tags=["batches"], response_model=BatchJobOut,
              responses={**ERRORS, 404: {"model": ErrorResponse}})  # fmt: skip
    def cancel_batch(principal: Principal, job_id: JobId) -> BatchJobOut:
        """Cancel a queued job, or stop a running one after its current chunk (managers)."""
        return _job_out(services.cancel_batch_job(principal, job_id))

    @app.get("/v1/batches/{job_id}/result", tags=["batches"], response_class=FileResponse,
             responses={**ERRORS, 404: {"model": ErrorResponse},
                        409: {"model": ErrorResponse}})  # fmt: skip
    def batch_result(
        principal: Principal,
        job_id: JobId,
        format: Annotated[str, Query(pattern="^(parquet|csv)$")] = "parquet",
    ) -> FileResponse:
        """Download a completed job's results as Parquet (default) or CSV (managers)."""
        kind = "result_csv" if format == "csv" else "result"
        path = services.batch_job_file(principal, job_id, kind)
        media = "text/csv" if format == "csv" else "application/vnd.apache.parquet"
        return FileResponse(path, media_type=media,
                            filename=f"loanlens_results_{job_id[:8]}.{format}")  # fmt: skip

    @app.get("/v1/batches/{job_id}/errors", tags=["batches"], response_class=FileResponse,
             responses={**ERRORS, 404: {"model": ErrorResponse},
                        409: {"model": ErrorResponse}})  # fmt: skip
    def batch_errors(principal: Principal, job_id: JobId) -> FileResponse:
        """Download the skipped rows (row number, applicant ID, problem) as CSV (managers)."""
        path = services.batch_job_file(principal, job_id, "errors")
        return FileResponse(path, media_type="text/csv",
                            filename=f"loanlens_errors_{job_id[:8]}.csv")  # fmt: skip

    # ---- Policies and model -------------------------------------------------------------

    @app.get("/v1/policies", tags=["reference"], response_model=list[PolicySummary])
    def policies() -> list[PolicySummary]:
        """Every policy profile (loan type). Profiles change rules, not the model."""
        return [
            PolicySummary(
                profile=p.profile,
                version=p.version,
                description=p.description,
                policy_hash=p.content_hash,
            )  # fmt: skip
            for p in (load_profile(name) for name in list_profiles())
        ]

    @app.get("/v1/policies/{profile}", tags=["reference"],
             responses={404: {"model": ErrorResponse}})  # fmt: skip
    def policy(profile: str) -> dict[str, Any]:
        """One profile's full settings (all values are illustrative placeholders)."""
        try:
            chosen = load_profile(profile)
        except UnknownProfileError as exc:
            raise ApiError(404, "unknown_profile", str(exc)) from None
        return {**chosen.model_dump(mode="json"), "policy_hash": chosen.content_hash}

    @app.get("/v1/model", tags=["reference"], response_model=ModelInfo,
             responses={503: {"model": ErrorResponse}})  # fmt: skip
    def model_info() -> ModelInfo:
        """The active registered model version and its cross-validated metrics."""
        try:
            entry, _ = registry.resolve_artifact()
        except (FileNotFoundError, registry.RegistryError):
            raise ApiError(503, "model_unavailable", "No registered model is available.") from None
        return ModelInfo(**entry.model_dump(include=set(ModelInfo.model_fields)))

    # ---- Audit --------------------------------------------------------------------------

    @app.get("/v1/audit", tags=["audit"], response_model=AuditResponse, responses=ERRORS)
    def audit_trail(
        principal: Principal,
        filters: Annotated[AuditFilters, Depends(audit_filters)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=services.MAX_PAGE_SIZE)] = 50,
    ) -> AuditResponse:
        """The decision audit trail (managers only), newest first, with counts."""
        result = services.audit_records(principal, filters, page=page, page_size=page_size)
        return AuditResponse(
            total=result.total, page=result.page, page_size=result.page_size,
            counts=result.counts, items=[AuditItem(**item) for item in result.items],
        )  # fmt: skip

    return app


app = create_app()
