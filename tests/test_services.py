"""Service-layer authorisation: every protected function checks the principal itself.

For each function: no principal and a hand-built principal raise an authorisation error, an
applicant is refused where only managers are allowed, and the allowed roles succeed.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from app_support import TEST_PASSWORD, new_session

from loanlens import auth, batch, services
from loanlens.auth import service as svc
from loanlens.examples import EXAMPLES
from loanlens.schema import ValidationFailure

STRONG = EXAMPLES[0][1]
APP_PAGES = Path(__file__).resolve().parents[1] / "app"


def _parsed():
    return batch.parse_upload(batch.template_csv())


def _save_summary(principal):
    parsed = _parsed()
    results = batch.score(parsed)
    return services.save_batch_summary(
        principal, batch.summarise(results, parsed), "1.0.0", results
    )


# name -> (call(principal), roles allowed)
CALLS = {
    "score_applicant": (lambda p, a: services.score_applicant(p, STRONG, artifact=a), "any"),
    "score_records": (lambda p, a: services.score_records(p, [STRONG], artifact=a), "manager"),
    "score_batch_upload": (
        lambda p, a: services.score_batch_upload(p, _parsed(), artifact=a), "manager"),
    "save_batch_summary": (lambda p, a: _save_summary(p), "manager"),
    "latest_batch_summary": (lambda p, a: services.latest_batch_summary(p), "manager"),
    "recent_batch_summaries": (lambda p, a: services.recent_batch_summaries(p), "manager"),
    "training_data": (lambda p, a: services.training_data(p), "manager"),
    "feature_importance": (lambda p, a: services.feature_importance(p, a), "manager"),
    "my_history": (lambda p, a: services.my_history(p), "any"),
    "audit_records": (lambda p, a: services.audit_records(p), "manager"),
    "audit_export": (lambda p, a: services.audit_export(p), "manager"),
    "audit_filter_options": (lambda p, a: services.audit_filter_options(p), "manager"),
}  # fmt: skip


def _forged(role: str) -> svc.Principal:
    real = new_session().principal
    return svc.Principal(real.user_id, real.email, role, real.audit_ref)


@pytest.mark.parametrize("name", list(CALLS))
def test_no_principal_is_refused(name, artifact) -> None:
    call, _ = CALLS[name]
    with pytest.raises(auth.AuthorisationError):
        call(None, artifact)


@pytest.mark.parametrize("name", list(CALLS))
@pytest.mark.parametrize("role", [auth.APPLICANT, auth.MANAGER])
def test_hand_built_principal_is_refused(name, role, artifact) -> None:
    call, _ = CALLS[name]
    with pytest.raises(auth.AuthorisationError):
        call(_forged(role), artifact)


@pytest.mark.parametrize("name", list(CALLS))
def test_applicant(name, artifact) -> None:
    call, allowed = CALLS[name]
    principal = new_session(auth.APPLICANT).principal
    if allowed == "manager":
        with pytest.raises(auth.PermissionDenied, match="bank managers only"):
            call(principal, artifact)
    else:
        assert call(principal, artifact) is not None


@pytest.mark.parametrize("name", list(CALLS))
def test_manager(name, artifact) -> None:
    call, _ = CALLS[name]
    principal = new_session(auth.MANAGER).principal
    call(principal, artifact)  # no error (training data may be None without the dataset)


def test_stale_principal_is_refused(artifact) -> None:
    signed_in = new_session()
    auth.change_password(signed_in.principal, TEST_PASSWORD, "another long passphrase")
    with pytest.raises(auth.InvalidSession):  # issued before the password change
        services.score_applicant(signed_in.principal, STRONG, artifact=artifact)


def test_deactivated_manager_is_refused(artifact) -> None:
    first, second = new_session(auth.MANAGER), new_session(auth.MANAGER)
    auth.set_active(first.principal, second.principal.user_id, False)
    with pytest.raises(auth.InvalidSession):
        services.audit_records(second.principal)


def test_invalid_input_is_returned_not_audited(artifact) -> None:
    principal = new_session().principal
    out = services.score_applicant(principal, {"cibil_score": 10}, artifact=artifact)
    assert isinstance(out, ValidationFailure)
    assert services.my_history(principal) == []


def test_score_records_rejects_invalid_rows(artifact) -> None:
    manager = new_session(auth.MANAGER).principal
    with pytest.raises(services.InvalidRecords) as exc:
        services.score_records(manager, [STRONG, {"cibil_score": 5}], artifact=artifact)
    assert list(exc.value.errors) == [1]
    assert services.audit_records(manager).total == 0  # nothing written
    with pytest.raises(ValueError, match="one entry per record"):
        services.score_records(manager, [STRONG], products=[], artifact=artifact)


def test_channels_are_checked(artifact) -> None:
    principal = new_session(auth.MANAGER).principal
    with pytest.raises(ValueError, match="Channel"):
        services.score_applicant(principal, STRONG, channel="batch", artifact=artifact)
    with pytest.raises(ValueError, match="Channel"):
        services.score_records(principal, [STRONG], channel="ui", artifact=artifact)


# ---- Pages call only the protected service layer --------------------------------------------

FORBIDDEN = (
    "decide(", "decide_many(", "batch.score(", " storage.", "(storage.",
    "explain.feature_importance",
    "loanlens.audit import query", "audit.query", "audit.write", "cleaning.PROCESSED_PATH",
    "from loanlens.decision import", "from loanlens import storage",
)  # fmt: skip


@pytest.mark.parametrize("page", sorted(p.name for p in (APP_PAGES / "pages").glob("*.py")))
def test_pages_do_not_call_unprotected_internals(page) -> None:
    source = (APP_PAGES / "pages" / page).read_text(encoding="utf-8")
    found = [name for name in FORBIDDEN if name in source]
    assert not found, f"{page} calls {found}"


def test_principal_seal_is_not_exposed() -> None:
    principal = new_session().principal
    assert "seal" not in repr(principal)
    assert principal == svc.Principal(  # equality ignores the seal
        principal.user_id, principal.email, principal.role, principal.audit_ref,
        principal.must_change_password, principal.token_version,
    )  # fmt: skip
    assert str(uuid.UUID(principal.audit_ref)) == principal.audit_ref
