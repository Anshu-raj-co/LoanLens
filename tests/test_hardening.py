"""Phase 10 hardening: secrets, edge cases, fallbacks and size limits."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from loanlens import batch, explain
from loanlens.config import PROJECT_ROOT, load_policy
from loanlens.decision import INPUT_COLUMNS, decide, decide_many
from loanlens.examples import EXAMPLES
from loanlens.formatting import inr, score_percent
from loanlens.presentation import borderline_explainer
from loanlens.schema import DecisionResult, ValidationFailure

STRONG = EXAMPLES[0][1]


# ---- Secrets ---------------------------------------------------------------------------------


def test_no_secret_committed() -> None:
    ignored = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".streamlit/secrets.toml" in ignored
    assert not (PROJECT_ROOT / ".streamlit" / "secrets.toml").exists()


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
