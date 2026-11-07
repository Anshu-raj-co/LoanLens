"""Customer mode: the functions the eligibility page calls, plus the page itself."""

from __future__ import annotations

from pathlib import Path

import pytest
from app_support import open_page

from loanlens.config import load_policy
from loanlens.decision import decide
from loanlens.examples import EXAMPLES
from loanlens.presentation import (
    FORM_FIELDS,
    PROTOTYPE_NOTICE,
    form_defaults,
    form_matches_schema,
    present,
    thresholds_note,
)
from loanlens.schema import ApplicantInput, DecisionResult, ValidationFailure

POLICY = load_policy()
PAGE = "pages/1_Check_My_Eligibility.py"


def test_form_collects_exactly_the_model_fields() -> None:
    assert form_matches_schema()
    for f in FORM_FIELDS:
        assert f.min_value <= f.default <= f.max_value
        assert f.help.strip()


def test_form_defaults_are_valid(artifact) -> None:
    assert isinstance(decide(form_defaults()), DecisionResult)


def test_form_ranges_cover_schema_limits() -> None:
    by_name = {f.name: f for f in FORM_FIELDS}
    assert by_name["cibil_score"].min_value == 300 and by_name["cibil_score"].max_value == 900
    assert by_name["loan_term"].max_value <= ApplicantInput.model_fields["loan_term"].metadata[1].le


@pytest.mark.parametrize(("title", "applicant", "expected"), EXAMPLES, ids=[e[0] for e in EXAMPLES])
def test_example_cases(artifact, title, applicant, expected) -> None:
    result = decide(applicant)
    assert isinstance(result, DecisionResult)
    assert result.status == expected["status"], title
    assert result.borderline is expected["borderline"], title
    view = present(result, POLICY)
    assert view.notice == PROTOTYPE_NOTICE
    assert "%" in view.likelihood and view.likelihood.split(" ")[0] not in {"0%", "100%"}
    assert view.score_label == "model score on synthetic data - indicative only"
    if view.approved:
        assert view.positives and not view.reasons and view.change_summary == ""
    else:
        assert view.reasons and all(r.message for r in view.reasons)
        assert "would likely" in view.change_summary
    if view.borderline:
        assert "manual review" in view.borderline_note
    assert len(view.rule_rows) == 6


def test_invalid_input_is_friendly() -> None:
    result = decide({**form_defaults(), "income_annum": 0})
    assert isinstance(result, ValidationFailure)
    assert result.errors[0].message == "Annual income must be greater than 0."


def test_thresholds_note_mentions_placeholders() -> None:
    note = thresholds_note(POLICY)
    assert "illustrative placeholders" in note and "550" in note and "10%" in note
    assert "lender's real credit policy" in note
    assert "bank" not in note.lower() and "india" not in note.lower()  # names no institution


def test_customer_page_does_not_store_data(app_path) -> None:
    source = (Path(app_path) / PAGE).read_text(encoding="utf-8")
    for forbidden in ("storage", "open(", "to_csv", "sqlite", "logging", "print("):
        assert forbidden not in source


# The real page, rendered headlessly ------------------------------------------------------


def _page(app_path: str, name: str):
    return open_page(name)


def test_home_renders(app_path) -> None:
    at = _page(app_path, "pages/9_Home.py").run()
    assert not at.exception and not at.error
    assert not any("approval decision" in w.value for w in at.warning)  # box removed
    assert any("illustrative placeholders" in i.value for i in at.info)
    assert any("approval decision" in c.value for c in at.caption)  # footer keeps it


def test_customer_page_renders(app_path, artifact) -> None:
    at = _page(app_path, PAGE).run()
    assert not at.exception and not at.error
    assert len(at.number_input) == len(FORM_FIELDS)


@pytest.mark.parametrize(
    ("title", "applicant", "expected"), EXAMPLES[2:], ids=lambda x: str(x)[:20]
)
def test_customer_page_submits_examples(app_path, artifact, title, applicant, expected) -> None:
    at = _page(app_path, PAGE).run()
    for name, value in applicant.items():
        at.number_input(key=f"form_{name}").set_value(value)
    at.button[0].click().run()
    assert not at.exception
    badge = at.success if expected["status"] == "Approved" else at.error
    assert any(expected["status"] in b.value for b in badge)
    shown = " ".join(m.value for m in at.metric)
    assert "0%" != shown.split(" ")[0] and "100%" not in shown
    assert any("Borderline" in w.value for w in at.warning) is expected["borderline"]


def test_customer_page_shows_validation_errors(app_path, artifact) -> None:
    at = _page(app_path, PAGE).run()
    at.number_input(key="form_loan_amount").set_value(0)
    at.button[0].click().run()
    assert not at.exception
    assert any("correct the following" in e.value for e in at.error)
    assert any("Loan amount must be greater than 0." in m.value for m in at.markdown)


@pytest.mark.parametrize(("title", "applicant", "expected"), EXAMPLES, ids=lambda x: str(x)[:20])
def test_key_figures_come_from_the_policy_checks(artifact, title, applicant, expected) -> None:
    """The result cards show only numbers the decision returned (rule actuals and limits)."""
    from loanlens.formatting import pct, times
    from loanlens.presentation import key_figures

    result = decide(applicant, POLICY, artifact=artifact)
    rules = {r.rule: r for r in result.rule_results}
    figures = {f.label: f for f in key_figures(result)}
    assert list(figures) == [
        "CIBIL score", "Loan to annual income", "Loan to total assets", "EMI to monthly income",
    ]  # fmt: skip
    assert figures["CIBIL score"].value == f"{rules['min_cibil'].actual:.0f}"
    assert figures["CIBIL score"].detail == "Minimum 550"
    assert figures["Loan to annual income"].value == times(rules["max_loan_to_income"].actual)
    assert figures["Loan to total assets"].detail == "Limit 1.5x"
    emi = figures["EMI to monthly income"]
    assert emi.value == pct(rules["max_emi_to_income"].actual)
    assert emi.detail == "Estimated; limit 50% (advisory)"  # advisory under personal
