"""Phase 10 hardening: manager gate, edge cases, fallbacks and size limits."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from loanlens import access, batch, explain
from loanlens.config import PROJECT_ROOT, load_policy
from loanlens.decision import INPUT_COLUMNS, decide, decide_many
from loanlens.examples import EXAMPLES
from loanlens.formatting import inr, score_percent
from loanlens.presentation import borderline_explainer
from loanlens.schema import DecisionResult, ValidationFailure

STRONG = EXAMPLES[0][1]


# ---- Manager gate (review decision 3) -----------------------------------------------------


def test_gate_password_precedence() -> None:
    assert access.resolve_password({}, None).is_demo_default
    assert access.resolve_password({}, {"manager_password": "s3"}).value == "s3"
    env = access.resolve_password({access.ENV_VAR: "e1"}, {"manager_password": "s3"})
    assert (env.value, env.source) == ("e1", "environment")
    assert access.resolve_password({access.ENV_VAR: "  "}, {}).is_demo_default


def test_gate_survives_broken_secrets() -> None:
    class Broken(dict):
        def get(self, *_):
            raise FileNotFoundError("no secrets.toml")

    assert access.resolve_password({}, Broken()).is_demo_default


def test_check_password() -> None:
    gate = access.GatePassword("right", "environment")
    assert access.check_password("right", gate)
    assert not access.check_password("wrong", gate)
    assert not access.check_password("", gate) and not access.check_password(None, gate)


def test_no_secret_committed() -> None:
    ignored = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".streamlit/secrets.toml" in ignored
    assert not (PROJECT_ROOT / ".streamlit" / "secrets.toml").exists()


def _bulk(app_path, monkeypatch, tmp_path, password: str | None):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from loanlens import storage

    monkeypatch.delenv(access.ENV_VAR, raising=False)
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: None)
    monkeypatch.setattr(storage, "db_path", lambda policy=None: tmp_path / "g.sqlite")
    at = AppTest.from_file(str(Path(app_path) / "pages" / "2_Bulk_Check.py"), default_timeout=120)
    at.run()
    at.toggle(key="manager_mode").set_value(True).run()
    if password is not None:
        at.text_input(key="manager_password").set_value(password).run()
    return at


def test_bulk_page_needs_password(app_path, monkeypatch, tmp_path, artifact) -> None:
    at = _bulk(app_path, monkeypatch, tmp_path, None)
    assert not at.exception
    assert any("Enter the manager password" in i.value for i in at.info)
    assert not at.get("download_button")
    at = _bulk(app_path, monkeypatch, tmp_path, "not-the-password")
    assert not at.exception
    assert any("not correct" in e.value for e in at.error)
    at = _bulk(app_path, monkeypatch, tmp_path, access.DEMO_PASSWORD)
    assert not at.exception and not at.error
    assert any("demo password" in c.value for c in at.sidebar.caption)


def test_bulk_page_uses_env_password(app_path, monkeypatch, tmp_path, artifact) -> None:
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv(access.ENV_VAR, "from-env")
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: None)
    at = AppTest.from_file(str(Path(app_path) / "pages" / "2_Bulk_Check.py"), default_timeout=120)
    at.run()
    at.toggle(key="manager_mode").set_value(True).run()
    at.text_input(key="manager_password").set_value(access.DEMO_PASSWORD).run()
    assert any("not correct" in e.value for e in at.error)
    at.text_input(key="manager_password").set_value("from-env").run()
    assert not at.exception and not at.error


# ---- Decision edge cases -------------------------------------------------------------------


def test_decide_many_empty(artifact) -> None:
    empty = pd.DataFrame(columns=list(INPUT_COLUMNS))
    assert decide_many(empty, load_policy(), artifact) == []


def test_rejection_always_has_a_reason_even_without_drivers(artifact, monkeypatch) -> None:
    """If no rule failed and no single model driver stands out, the fallback reason is used."""
    policy = load_policy()
    strict = policy.model_copy(
        update={"model": policy.model.model_copy(update={"approval_threshold": 0.999999})}
    )
    applicant = EXAMPLES[1][1]  # approved at 0.5, but below an extreme threshold
    monkeypatch.setattr(explain, "model_reasons", lambda *a, **k: [])
    result = decide(applicant, policy=strict, artifact=artifact)
    assert isinstance(result, DecisionResult) and result.status == "Rejected"
    assert [r.code for r in result.reasons] == ["OVERALL_PROFILE"]
    assert result.reasons[0].message


@pytest.mark.parametrize(
    ("field", "value"),
    [("income_annum", 0), ("loan_amount", 0), ("loan_amount", -5), ("cibil_score", 1000),
     ("loan_term", 0), ("bank_asset_value", -1), ("income_annum", float("inf")),
     ("income_annum", float("nan")), ("cibil_score", "abc")],
)  # fmt: skip
def test_bad_values_give_friendly_errors(field, value, artifact) -> None:
    result = decide({**STRONG, field: value}, artifact=artifact)
    assert isinstance(result, ValidationFailure)
    assert result.errors and all("Traceback" not in e.message for e in result.errors)


def test_huge_values_decide_with_warning(artifact) -> None:
    huge = {**STRONG, "income_annum": 1e15, "loan_amount": 2e15, "bank_asset_value": 1e16}
    result = decide(huge, artifact=artifact)
    assert isinstance(result, DecisionResult)
    assert result.warnings  # outside the training range
    zero_assets = {**STRONG, **{c: 0 for c in INPUT_COLUMNS if c.endswith("_value")}}
    result = decide(zero_assets, artifact=artifact)
    assert isinstance(result, DecisionResult) and result.status == "Rejected" and result.reasons


def test_borderline_explainer_matches_policy() -> None:
    policy = load_policy()
    text = borderline_explainer(policy)
    assert "manual review" in text and "another rule also failed" in text
    assert f"{policy.rules.min_cibil.value:.0f}" in text
    assert f"{policy.model.borderline_cibil_margin:g} points" in text


def test_single_and_many_what_would_change_agree(artifact) -> None:
    policy = load_policy()
    applicant = EXAMPLES[2][1]
    from loanlens.schema import validate_applicant

    single = explain.what_would_change(validate_applicant(applicant), artifact, policy)
    many = explain.what_would_change_many(pd.DataFrame([applicant]), artifact, policy)[0]
    assert single == many


def test_cibil_candidates_near_the_top() -> None:
    assert explain._cibil_candidates(895) == [900]
    assert explain._cibil_candidates(900) == []


def test_non_finite_display() -> None:
    assert inr(float("nan")).endswith("n/a")
    assert score_percent(float("inf")) == "n/a"


# ---- Batch edge cases ----------------------------------------------------------------------


def _rows(n: int) -> bytes:
    template = pd.read_csv(io.BytesIO(batch.template_csv()))
    frame = pd.concat([template] * (n // len(template) + 1), ignore_index=True).head(n)
    frame[batch.ID_COLUMN] = [f"A{i}" for i in range(n)]
    return frame.to_csv(index=False).encode()


def test_50000_rows_accepted_51000_rejected_clearly() -> None:
    policy = load_policy()
    assert policy.batch.max_rows == 50_000
    parsed = batch.parse_upload(_rows(50_000), policy)
    assert len(parsed.values) == 50_000 and not parsed.errors
    with pytest.raises(batch.BatchError, match=r"51,000 rows, but the maximum is 50,000"):
        batch.parse_upload(_rows(51_000), policy)


def test_cp1252_file_is_read() -> None:
    template = batch.template_csv().decode("utf-8-sig")
    data = template.replace("APP-0001", "Rs’s file").encode("cp1252")
    assert b"\x92" in data  # not valid UTF-8, so the cp1252 fallback is exercised
    parsed = batch.parse_upload(data)
    assert not parsed.errors and len(parsed.values) == 3
    assert parsed.applicant_ids.iloc[0] == "Rs’s file"


def test_binary_file_gives_friendly_error() -> None:
    with pytest.raises(batch.BatchError):
        batch.parse_upload(b"\x00\x01\x02\xff\xfe" * 50)
