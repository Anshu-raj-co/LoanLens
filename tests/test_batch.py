"""Tests for loanlens.batch, loanlens.storage and the Bulk Check page."""

from __future__ import annotations

import io
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from loanlens import batch, storage
from loanlens.access import DEMO_PASSWORD
from loanlens.config import BatchConfig, StorageConfig, load_policy
from loanlens.decision import decide
from loanlens.schema import ValidationFailure, validate_applicant

FIXTURE = Path(__file__).parent / "fixtures" / "batch_1000.csv"
BAD_ROWS = [150, 153, 168, 230, 238, 249, 324, 334, 335, 366,
            370, 432, 499, 546, 575, 628, 678, 784, 829, 932]  # fmt: skip
POLICY = load_policy()


def csv_bytes(frame: pd.DataFrame, sep: str = ",") -> bytes:
    return frame.to_csv(index=False, sep=sep).encode("utf-8")


@pytest.fixture(scope="module")
def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture(scope="module")
def fixture_parsed(fixture_bytes):
    return batch.parse_upload(fixture_bytes)


@pytest.fixture(scope="module")
def fixture_results(fixture_parsed, artifact):
    return batch.score(fixture_parsed, artifact=artifact)


# Template ----------------------------------------------------------------------------------


def test_template_has_headers_and_three_rows() -> None:
    frame = pd.read_csv(io.BytesIO(batch.template_csv()))
    assert list(frame.columns) == [batch.ID_COLUMN, *batch.REQUIRED_COLUMNS]
    assert len(frame) == 3
    parsed = batch.parse_upload(batch.template_csv())
    assert parsed.errors == [] and len(parsed.values) == 3


# Good CSV ----------------------------------------------------------------------------------


def test_good_csv(artifact) -> None:
    parsed = batch.parse_upload(batch.template_csv())
    results = batch.score(parsed, artifact=artifact)
    assert list(results["status"]) == ["Approved", "Approved", "Rejected"]
    assert list(results["applicant_id"]) == ["APP-0001", "APP-0002", "APP-0003"]
    assert list(results["row"]) == [2, 3, 4]
    for col in ("status", "probability", "borderline", "reasons", "what_would_change"):
        assert col in results.columns


def test_amounts_with_indian_grouping_are_parsed() -> None:
    values, blank = batch.parse_numbers(pd.Series(["12,50,000", "Rs 5,00,000", "₹ 1,000", ""]))
    assert values.tolist()[:3] == [1_250_000, 500_000, 1_000]
    assert blank.tolist() == [False, False, False, True]


# The 1,000-row fixture (980 good rows, 20 bad rows) ----------------------------------------


def test_fixture_bad_rows_reported_and_skipped(fixture_parsed) -> None:
    assert fixture_parsed.total_rows == 1000
    assert len(fixture_parsed.values) == 980
    assert sorted(e.row for e in fixture_parsed.errors) == BAD_ROWS
    for e in fixture_parsed.errors:
        assert e.message.strip().endswith(".")
        assert e.applicant_id.startswith("APP-")


def test_row_errors_agree_with_customer_validation(fixture_bytes, fixture_parsed) -> None:
    raw = pd.read_csv(io.BytesIO(fixture_bytes), dtype=str, keep_default_na=False)
    for e in fixture_parsed.errors:
        row = raw.iloc[e.row - 2].drop(labels=[batch.ID_COLUMN]).to_dict()
        row = {k: (None if v == "" else v.replace(",", "")) for k, v in row.items()}
        assert isinstance(validate_applicant(row), ValidationFailure), e


def test_fixture_scores_and_every_rejection_has_reasons(fixture_results) -> None:
    assert len(fixture_results) == 980
    rejected = fixture_results[fixture_results["status"] == "Rejected"]
    assert len(rejected) > 0
    assert (rejected["reasons"].str.strip() != "").all()
    assert (rejected["what_would_change"].str.strip() != "").all()
    approved = fixture_results[fixture_results["status"] == "Approved"]
    assert (approved["reasons"] == "").all()
    assert not fixture_results["likelihood"].str.match(r"^(0|100)%").any()


def test_summary(fixture_parsed, fixture_results) -> None:
    s = batch.summarise(fixture_results, fixture_parsed)
    assert s["total_rows"] == 1000 and s["valid_rows"] == 980 and s["invalid_rows"] == 20
    assert s["approved"] + s["rejected"] == 980
    assert s["approval_rate"] == pytest.approx(s["approved"] / 980)
    assert s["top_rejection_reasons"][0]["code"] == "RULE_MIN_CIBIL"
    assert sum(s["likelihood_bands"].values()) == 980


def test_filters_and_search(fixture_results) -> None:
    rej = batch.filter_results(fixture_results, ["Rejected"])
    assert (rej["status"] == "Rejected").all()
    border = batch.filter_results(fixture_results, borderline=True)
    assert border["borderline"].all()
    one = batch.filter_results(fixture_results, search=fixture_results["applicant_id"].iloc[0])
    assert len(one) == 1
    cibil = batch.filter_results(fixture_results, search="cibil score")
    assert len(cibil) > 0


def test_results_csv_roundtrip(fixture_results) -> None:
    back = pd.read_csv(io.BytesIO(batch.results_csv(fixture_results)), encoding="utf-8-sig")
    assert len(back) == len(fixture_results)
    np.testing.assert_allclose(back["probability"], fixture_results["probability"])


def test_1000_rows_within_10_seconds(fixture_bytes, artifact) -> None:
    start = time.perf_counter()
    batch.score(batch.parse_upload(fixture_bytes), artifact=artifact)
    assert time.perf_counter() - start <= 10


# File-level problems -----------------------------------------------------------------------


@pytest.mark.parametrize("content", [b"", b"   \n\n", b"\xef\xbb\xbf"])
def test_empty_file(content: bytes) -> None:
    with pytest.raises(batch.BatchError, match="empty"):
        batch.parse_upload(content)


def test_header_only() -> None:
    with pytest.raises(batch.BatchError, match="no applicant rows"):
        batch.parse_upload(",".join(batch.REQUIRED_COLUMNS).encode())


def test_missing_columns_named_exactly() -> None:
    frame = pd.read_csv(io.BytesIO(batch.template_csv())).drop(columns=["loan_term", "cibil_score"])
    with pytest.raises(batch.BatchError) as exc:
        batch.parse_upload(csv_bytes(frame))
    msg = str(exc.value)
    assert msg == (
        "Required columns are missing: cibil_score (CIBIL score), " "loan_term (Loan term (years))."
    )


@pytest.mark.parametrize("sep", [";", "\t", "|"])
def test_other_delimiters(sep: str, artifact) -> None:
    frame = pd.read_csv(io.BytesIO(batch.template_csv()))
    parsed = batch.parse_upload(csv_bytes(frame, sep))
    assert parsed.errors == [] and len(parsed.values) == 3
    expected = batch.parse_upload(batch.template_csv()).values
    pd.testing.assert_frame_equal(parsed.values, expected)


def test_unsplittable_file_reports_missing_columns() -> None:
    with pytest.raises(batch.BatchError, match="Required columns are missing"):
        batch.parse_upload(b"cibil_score income_annum loan_amount\n700 5000000 1000000\n")


def test_too_many_rows() -> None:
    small = POLICY.model_copy(update={"batch": BatchConfig(max_rows=2)})
    with pytest.raises(batch.BatchError, match="maximum is 2 rows"):
        batch.parse_upload(batch.template_csv(), small)


def test_ragged_rows_never_crash() -> None:
    content = batch.template_csv() + b"APP-9,700,1,2,3,4,5,6,7,8,9,10,11\n"
    try:
        parsed = batch.parse_upload(content)
    except batch.BatchError as exc:
        assert "CSV" in str(exc)
    else:
        assert parsed.total_rows >= 3


# Header aliases ----------------------------------------------------------------------------


def test_header_aliases(artifact) -> None:
    frame = pd.read_csv(io.BytesIO(batch.template_csv()))
    frame.columns = [
        "Loan ID", " CIBIL ", "Income", "Loan Amount", "Tenure (years)",
        "Residential Assets", "commercial_assets", "LUXURY_ASSETS_VALUE", "Bank Assets",
    ]  # fmt: skip
    frame["Customer Name"] = "someone"
    parsed = batch.parse_upload(csv_bytes(frame))
    assert parsed.errors == []
    assert parsed.renamed["Income"] == "income_annum"
    assert parsed.renamed["Tenure (years)"] == "loan_term"
    assert parsed.renamed["Loan ID"] == "applicant_id"
    assert parsed.ignored == ["Customer Name"]
    pd.testing.assert_frame_equal(parsed.values, batch.parse_upload(batch.template_csv()).values)


@pytest.mark.parametrize(
    ("header", "canonical"),
    [("annual_income", "income_annum"), ("Annual Income", "income_annum"),
     ("credit score", "cibil_score"), ("LOAN_AMOUNT", "loan_amount"),
     ("loan_term (years)", "loan_term"), ("bank_balance", "bank_asset_value")],
)  # fmt: skip
def test_canonical_name(header: str, canonical: str) -> None:
    assert batch.canonical_name(header) == canonical


def test_duplicate_alias_rejected() -> None:
    frame = pd.read_csv(io.BytesIO(batch.template_csv()))
    frame["Income"] = frame["income_annum"]
    with pytest.raises(batch.BatchError, match="Two columns both look like 'income_annum'"):
        batch.parse_upload(csv_bytes(frame))


# Performance and consistency ----------------------------------------------------------------


@pytest.fixture(scope="module")
def ten_k_bytes(clean_df) -> bytes:
    rows = clean_df.drop(columns=["loan_status"]).sample(10_000, replace=True, random_state=7)
    rows.insert(0, "applicant_id", [f"P{i}" for i in range(len(rows))])
    return csv_bytes(rows)


def test_10k_rows_within_90_seconds(ten_k_bytes, artifact) -> None:
    start = time.perf_counter()
    parsed = batch.parse_upload(ten_k_bytes)
    results = batch.score(parsed, artifact=artifact)
    elapsed = time.perf_counter() - start
    assert len(results) == 10_000
    assert elapsed <= 90, f"10k rows took {elapsed:.1f}s"


def test_batch_matches_single_decisions(fixture_parsed, fixture_results) -> None:
    """Review decision 4: identical status, probability (1e-6) and reasons on 500+ rows."""
    n = 600
    for i in range(n):
        applicant = fixture_parsed.values.iloc[i].to_dict()
        single = decide(applicant)
        row = fixture_results.iloc[i]
        assert single.status == row["status"], i
        assert abs(single.probability - row["probability"]) <= 1e-6, i
        assert "; ".join(r.message for r in single.reasons) == row["reasons"], i
        assert single.borderline == row["borderline"], i


def test_progress_callback(fixture_parsed, artifact) -> None:
    seen: list[float] = []
    small = POLICY.model_copy(update={"batch": BatchConfig(chunk_size=300)})
    batch.score(fixture_parsed, small, artifact, progress=seen.append)
    assert seen == sorted(seen) and seen[-1] == 1.0 and len(seen) == 4


def test_positive_factors_option(artifact) -> None:
    parsed = batch.parse_upload(batch.template_csv())
    with_pos = batch.score(parsed, artifact=artifact, include_positive=True)
    assert "positive_factors" in with_pos.columns
    assert with_pos.loc[0, "positive_factors"]
    assert "positive_factors" not in batch.score(parsed, artifact=artifact).columns


# Storage -----------------------------------------------------------------------------------


def test_storage_saves_only_anonymised_summary(tmp_path, fixture_parsed, fixture_results) -> None:
    db = tmp_path / "test.sqlite"
    summary = batch.summarise(fixture_results, fixture_parsed)
    batch_id = storage.save_summary(summary, "1.0.0", fixture_results, POLICY, path=db)
    latest = storage.latest_summary(db)
    assert latest["id"] == batch_id and latest["valid_rows"] == 980
    assert latest["top_rejection_reasons"][0]["code"] == "RULE_MIN_CIBIL"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM batch_rows").fetchone()[0] == 0
    assert b"APP-" not in db.read_bytes()  # no applicant IDs anywhere in the file
    assert len(storage.list_summaries(path=db)) == 1


def test_storage_ids_only_when_enabled(tmp_path, fixture_parsed, fixture_results) -> None:
    db = tmp_path / "ids.sqlite"
    enabled = POLICY.model_copy(update={"storage": StorageConfig(store_applicant_ids=True)})
    summary = batch.summarise(fixture_results, fixture_parsed)
    storage.save_summary(summary, "1.0.0", fixture_results, enabled, path=db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM batch_rows").fetchone()[0] == 980


def test_latest_summary_when_no_database(tmp_path) -> None:
    assert storage.latest_summary(tmp_path / "missing.sqlite") is None
    assert storage.list_summaries(path=tmp_path / "missing.sqlite").empty


# The Bulk Check page -----------------------------------------------------------------------


class _Upload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _bulk_page(app_path, monkeypatch, upload: bytes | None, tmp_path):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: _Upload(upload) if upload else None)
    monkeypatch.setattr(storage, "db_path", lambda policy=None: tmp_path / "page.sqlite")
    at = AppTest.from_file(str(Path(app_path) / "pages" / "2_Bulk_Check.py"), default_timeout=120)
    at.run()
    at.toggle(key="manager_mode").set_value(True).run()
    at.text_input(key="manager_password").set_value(DEMO_PASSWORD).run()
    return at


def test_bulk_page_gated(app_path) -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(Path(app_path) / "pages" / "2_Bulk_Check.py")).run()
    assert not at.exception
    assert any("Bank manager mode" in i.value for i in at.info)


def test_bulk_page_with_fixture(app_path, monkeypatch, tmp_path, fixture_bytes, artifact) -> None:
    at = _bulk_page(app_path, monkeypatch, fixture_bytes, tmp_path)
    assert not at.exception, at.exception
    assert any("20 of 1,000 rows have problems" in w.value for w in at.warning)
    assert [m.value for m in at.metric][0] == "980"
    assert storage.latest_summary(tmp_path / "page.sqlite")["valid_rows"] == 980
    at.multiselect[0].set_value(["Rejected"]).run()
    assert not at.exception


def test_bulk_page_missing_columns(app_path, monkeypatch, tmp_path) -> None:
    frame = pd.read_csv(io.BytesIO(batch.template_csv())).drop(columns=["loan_term"])
    at = _bulk_page(app_path, monkeypatch, csv_bytes(frame), tmp_path)
    assert not at.exception
    assert any("Required columns are missing: loan_term" in e.value for e in at.error)


def test_bulk_page_empty_file(app_path, monkeypatch, tmp_path) -> None:
    at = _bulk_page(app_path, monkeypatch, b" ", tmp_path)
    assert not at.exception
    assert any("empty" in e.value for e in at.error)
