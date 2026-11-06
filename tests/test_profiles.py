"""Versioned policy profiles: loading, hashing, per-profile rules, decisions and Bulk Check."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from loanlens import batch
from loanlens.config import (
    DEFAULT_PROFILE,
    PROFILES_DIR,
    SEMVER,
    UnknownProfileError,
    list_profiles,
    load_all_profiles,
    load_policy,
    load_policy_file,
    load_profile,
)
from loanlens.decision import decide, decide_many
from loanlens.examples import EXAMPLES
from loanlens.schema import DecisionResult

# Probabilities of the six built-in examples, recorded before profiles existed (model
# 1.0.0). The personal profile must keep reproducing them.
EXPECTED_EXAMPLES = [
    ("Approved", 0.9981, False),
    ("Approved", 0.9608, False),
    ("Rejected", 0.0000, False),
    ("Rejected", 0.6042, False),
    ("Rejected", 0.4502, True),
    ("Rejected", 0.0000, True),
]
BASE = {
    "cibil_score": 760,
    "income_annum": 5_000_000,
    "loan_amount": 10_000_000,
    "loan_term": 10,
    "residential_assets_value": 9_000_000,
    "commercial_assets_value": 3_000_000,
    "luxury_assets_value": 6_000_000,
    "bank_asset_value": 3_000_000,
}


def _rule(result: DecisionResult, name: str):
    return next(r for r in result.rule_results if r.rule == name)


# ---- Loading -------------------------------------------------------------------------------


def test_profiles_listed_default_first() -> None:
    assert list_profiles() == ["personal", "home", "vehicle"]
    assert DEFAULT_PROFILE == "personal"
    assert load_policy() is load_profile("personal")


@pytest.mark.parametrize("name", ["personal", "home", "vehicle"])
def test_profile_metadata(name: str) -> None:
    policy = load_profile(name)
    assert policy.profile == name
    assert re.fullmatch(SEMVER, policy.version)
    assert "illustrative" in policy.description.lower()
    assert re.fullmatch(r"[0-9a-f]{64}", policy.content_hash)


@pytest.mark.parametrize("path", sorted(PROFILES_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_every_profile_value_marked_placeholder(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.split("#")[0].strip()
        if stripped.startswith(
            ("value:", "enforce:", "assumed_annual", "approval_threshold", "lower:", "upper:")
        ):
            assert "PLACEHOLDER" in line, line
    assert "rules and assumptions only" in text  # states that the model is not changed


def test_personal_reproduces_the_original_policy() -> None:
    """The values of the original config/policy.yaml, unchanged."""
    p = load_profile("personal")
    r = p.rules
    assert (r.min_cibil.value, r.min_cibil.enforce) == (550, True)
    assert (r.max_emi_to_income.value, r.max_emi_to_income.enforce) == (0.5, False)
    assert (r.max_loan_to_income.value, r.max_loan_to_income.enforce) == (4.0, True)
    assert (r.max_loan_to_assets.value, r.max_loan_to_assets.enforce) == (1.5, True)
    assert (r.min_loan_term_years.value, r.max_loan_term_years.value) == (2, 20)
    assert p.emi.assumed_annual_interest_rate == 0.10
    assert p.model.approval_threshold == 0.5
    assert (p.model.borderline_band.lower, p.model.borderline_band.upper) == (0.4, 0.6)
    assert p.model.borderline_cibil_margin == 25
    bands = p.display.probability_bands
    assert (bands.very_likely, bands.likely, bands.borderline, bands.unlikely) == (
        0.85,
        0.65,
        0.35,
        0.15,
    )
    assert (p.batch.max_rows, p.batch.chunk_size) == (50_000, 2_000)
    assert p.storage.store_applicant_ids is False


def test_other_profiles_differ_as_documented() -> None:
    home, vehicle = load_profile("home"), load_profile("vehicle")
    assert (home.rules.min_loan_term_years.value, home.rules.max_loan_term_years.value) == (5, 30)
    assert home.rules.max_loan_to_income.value == 6.0
    assert home.rules.max_loan_to_assets.value == 2.0
    assert home.emi.assumed_annual_interest_rate == 0.085
    assert (vehicle.rules.min_loan_term_years.value, vehicle.rules.max_loan_term_years.value) == (
        1,
        7,
    )
    assert vehicle.rules.max_loan_to_income.value == 1.5
    assert vehicle.rules.max_loan_to_assets.value == 1.0
    assert vehicle.emi.assumed_annual_interest_rate == 0.11
    for policy in (home, vehicle):  # the model settings are shared
        assert policy.model == load_profile("personal").model


def test_unknown_profile_is_a_clear_error() -> None:
    with pytest.raises(UnknownProfileError, match="Choose one of: personal, home, vehicle"):
        load_profile("boat")
    for bad in ("../personal", "personal.yaml", "C:/x", "a" * 40):
        with pytest.raises(UnknownProfileError):
            load_profile(bad)


def test_profile_names_are_normalised() -> None:
    assert load_profile(" Home ") is load_profile("home")
    assert load_profile(None).profile == "personal" and load_profile("").profile == "personal"


def test_load_all_profiles() -> None:
    assert list(load_all_profiles()) == ["personal", "home", "vehicle"]


# ---- Content hash --------------------------------------------------------------------------


def test_hash_is_stable_and_ignores_comments(tmp_path: Path) -> None:
    text = (PROFILES_DIR / "personal.yaml").read_text(encoding="utf-8")
    original = load_profile("personal").content_hash
    commented = tmp_path / "personal.yaml"
    commented.write_text("# an extra comment\n" + text.replace("  #", "      #"), "utf-8")
    assert load_policy_file(commented).content_hash == original
    changed = tmp_path / "changed.yaml"
    changed.write_text(text.replace("value: 550", "value: 600", 1), "utf-8")
    assert load_policy_file(changed).content_hash != original
    hashes = {p.content_hash for p in load_all_profiles().values()}
    assert len(hashes) == 3


def test_version_must_be_semantic(tmp_path: Path) -> None:
    text = (PROFILES_DIR / "home.yaml").read_text(encoding="utf-8")
    bad = tmp_path / "home.yaml"
    bad.write_text(text.replace('version: "1.0.0"', 'version: "v1"'), "utf-8")
    with pytest.raises(ValidationError):
        load_policy_file(bad)


# ---- Decisions -----------------------------------------------------------------------------


@pytest.mark.parametrize("index", range(len(EXAMPLES)), ids=[e[0][:25] for e in EXAMPLES])
def test_personal_reproduces_example_decisions(artifact, index: int) -> None:
    title, applicant, _ = EXAMPLES[index]
    status, probability, borderline = EXPECTED_EXAMPLES[index]
    default = decide(applicant)
    personal = decide(applicant, profile="personal")
    assert default.model_dump() == personal.model_dump()
    assert personal.status == status, title
    assert personal.probability == pytest.approx(probability, abs=5e-5), title
    assert personal.borderline is borderline, title
    assert personal.profile == "personal" and personal.policy_version == "1.0.0"
    assert personal.policy_hash == load_profile("personal").content_hash
    assert personal.model_version == "1.0.0"


def test_result_records_the_profile(artifact) -> None:
    for name in list_profiles():
        result = decide(BASE, profile=name)
        policy = load_profile(name)
        assert (result.profile, result.policy_version, result.policy_hash) == (
            name,
            policy.version,
            policy.content_hash,
        )


def test_term_limits_follow_the_profile(artifact) -> None:
    long_loan = {**BASE, "loan_term": 25}
    assert not _rule(decide(long_loan, profile="personal"), "max_loan_term_years").passed
    assert _rule(decide(long_loan, profile="home"), "max_loan_term_years").passed
    assert not _rule(decide(long_loan, profile="vehicle"), "max_loan_term_years").passed
    one_year = {**BASE, "loan_term": 1}
    assert not _rule(decide(one_year, profile="personal"), "min_loan_term_years").passed
    assert _rule(decide(one_year, profile="vehicle"), "min_loan_term_years").passed
    four_years = {**BASE, "loan_term": 4}
    assert not _rule(decide(four_years, profile="home"), "min_loan_term_years").passed


def test_income_multiple_follows_the_profile(artifact) -> None:
    five_x = {**BASE, "loan_amount": 25_000_000}  # 5.0x annual income
    personal = decide(five_x, profile="personal")
    assert not _rule(personal, "max_loan_to_income").passed and personal.status == "Rejected"
    assert _rule(decide(five_x, profile="home"), "max_loan_to_income").passed
    two_x = BASE  # 2.0x annual income
    assert _rule(decide(two_x, profile="personal"), "max_loan_to_income").passed
    assert not _rule(decide(two_x, profile="vehicle"), "max_loan_to_income").passed


def test_asset_multiple_follows_the_profile(artifact) -> None:
    applicant = {**BASE, "loan_amount": 18_000_000, "luxury_assets_value": 0}  # 1.2x assets
    assert _rule(decide(applicant, profile="personal"), "max_loan_to_assets").passed
    assert not _rule(decide(applicant, profile="vehicle"), "max_loan_to_assets").passed


def test_interest_rate_follows_the_profile(artifact) -> None:
    def emi_message(name: str) -> str:
        return _rule(decide(BASE, profile=name), "max_emi_to_income").message

    assert emi_message("personal") != emi_message("home")  # different EMI share
    failing = {**BASE, "income_annum": 1_300_000, "loan_amount": 5_000_000, "loan_term": 3}
    assert "8.5%" in _rule(decide(failing, profile="home"), "max_emi_to_income").message
    assert "11.0%" in _rule(decide(failing, profile="vehicle"), "max_emi_to_income").message


def test_unknown_profile_in_decide(artifact) -> None:
    with pytest.raises(UnknownProfileError, match="Unknown loan type 'boat'"):
        decide(BASE, profile="boat")
    with pytest.raises(UnknownProfileError):
        decide_many(pd.DataFrame([BASE]), profile="boat")


def test_explicit_policy_wins_over_profile(artifact) -> None:
    result = decide(BASE, policy=load_profile("home"), profile="vehicle")
    assert result.profile == "home"


# ---- Bulk Check product column -------------------------------------------------------------


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def test_batch_product_column(artifact) -> None:
    rows = [
        {"applicant_id": "P1", **BASE, "product": "personal"},
        {"applicant_id": "H1", **{**BASE, "loan_term": 25}, "product": "Home"},
        {"applicant_id": "B1", **BASE, "product": ""},
        {"applicant_id": "X1", **BASE, "product": "boat"},
        {"applicant_id": "V1", **BASE, "product": " vehicle "},
    ]
    parsed = batch.parse_upload(_csv(rows))
    assert [e.applicant_id for e in parsed.errors] == ["X1"]
    assert "Product 'boat' is not a known loan type" in parsed.errors[0].message
    assert "personal, home, vehicle" in parsed.errors[0].message
    assert list(parsed.products) == ["personal", "home", "personal", "vehicle"]
    results = batch.score(parsed)
    assert list(results["product"]) == ["personal", "home", "personal", "vehicle"]
    for (_, row), product, raw in zip(
        results.iterrows(), parsed.products, [rows[0], rows[1], rows[2], rows[4]], strict=True
    ):
        applicant = {k: raw[k] for k in BASE}
        single = decide(applicant, profile=product)
        assert row["status"] == single.status
        assert row["probability"] == pytest.approx(single.probability)


def test_batch_product_header_aliases(artifact) -> None:
    rows = [{**BASE, "Loan Type": "vehicle"}]
    parsed = batch.parse_upload(_csv(rows))
    assert parsed.renamed == {"Loan Type": "product"} and list(parsed.products) == ["vehicle"]


def test_batch_without_product_column_is_unchanged(artifact) -> None:
    parsed = batch.parse_upload(batch.template_csv())
    assert parsed.products is None
    results = batch.score(parsed)
    assert set(results["product"]) == {"personal"}
    for (_, row), (_, values) in zip(results.iterrows(), parsed.values.iterrows(), strict=True):
        assert row["status"] == decide(values.to_dict()).status


def test_batch_products_split_across_chunks(artifact) -> None:
    policy = load_policy()
    small = policy.model_copy(update={"batch": policy.batch.model_copy(update={"chunk_size": 2})})
    rows = [{**BASE, "product": p} for p in ["home", "personal", "home", "vehicle", "personal"]]
    parsed = batch.parse_upload(_csv(rows), small)
    results = batch.score(parsed, small)
    assert list(results["product"]) == ["home", "personal", "home", "vehicle", "personal"]
    assert list(results["row"]) == [2, 3, 4, 5, 6]


def test_template_still_has_no_product_column() -> None:
    frame = pd.read_csv(io.BytesIO(batch.template_csv()))
    assert "product" not in frame.columns  # optional column, documented on the page


# ---- Customer page -------------------------------------------------------------------------


def test_customer_page_loan_type_selector(app_path, artifact) -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(
        str(Path(app_path) / "pages/1_Check_My_Eligibility.py"), default_timeout=120
    ).run()
    box = at.selectbox(key="form_loan_type")
    assert box.value == "personal" and list(box.options) == [
        "Personal loan",
        "Home loan",
        "Vehicle loan",
    ]
    assert any("not the trained model" in c.value for c in at.caption)
    box.set_value("home").run()
    assert any("5 to 30 years" in c.value for c in at.caption)  # thresholds note follows
    at.button[0].click().run()
    assert not at.exception
    assert any("Loan type: Home loan (policy profile v1.0.0" in c.value for c in at.caption)
