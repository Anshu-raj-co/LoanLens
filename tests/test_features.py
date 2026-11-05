"""Tests for loanlens.features."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from loanlens import features as f
from loanlens.config import load_policy


# EMI
def test_emi_known_value() -> None:
    # Rs 10,00,000 over 10 years at 10%: textbook EMI is about Rs 13,215.07.
    assert f.emi(1_000_000, 10, 0.10) == pytest.approx(13215.07, abs=0.01)


def test_emi_total_repayment_exceeds_principal() -> None:
    payment = f.emi(500_000, 5, 0.12)
    assert payment * 60 > 500_000


def test_emi_zero_rate_is_straight_line() -> None:
    assert f.emi(1_200_000, 10, 0.0) == pytest.approx(10_000)


def test_emi_uses_config_rate_by_default() -> None:
    rate = load_policy().emi.assumed_annual_interest_rate
    assert f.emi(1_000_000, 10) == pytest.approx(f.emi(1_000_000, 10, rate))


@pytest.mark.parametrize("term", [0, -1])
def test_emi_invalid_term_is_nan(term: int) -> None:
    assert math.isnan(f.emi(1_000_000, term, 0.10))


def test_emi_zero_principal() -> None:
    assert f.emi(0, 10, 0.10) == 0


def test_emi_vectorised_series_keeps_index() -> None:
    s = f.emi(pd.Series([1_000_000, 2_000_000], index=[5, 9]), pd.Series([10, 0], index=[5, 9]))
    assert list(s.index) == [5, 9]
    assert s.iloc[0] > 0 and math.isnan(s.iloc[1])


def test_emi_doubles_with_principal() -> None:
    assert f.emi(2_000_000, 7, 0.1) == pytest.approx(2 * f.emi(1_000_000, 7, 0.1))


# Ratios
def test_emi_to_income() -> None:
    payment = f.emi(1_000_000, 10, 0.10)
    assert f.emi_to_income(1_000_000, 10, 1_200_000, 0.10) == pytest.approx(payment / 100_000)


def test_emi_to_income_zero_income_is_inf() -> None:
    assert math.isinf(f.emi_to_income(1_000_000, 10, 0, 0.10))


def test_emi_to_income_zero_term_is_nan() -> None:
    assert math.isnan(f.emi_to_income(1_000_000, 0, 1_200_000, 0.10))


def test_loan_to_income() -> None:
    assert f.loan_to_income(3_000_000, 1_000_000) == pytest.approx(3.0)


def test_loan_to_income_zero_income() -> None:
    assert math.isinf(f.loan_to_income(1, 0))
    assert f.loan_to_income(0, 0) == 0


def test_loan_to_income_extreme_amounts() -> None:
    assert f.loan_to_income(1e15, 1) == pytest.approx(1e15)
    assert f.loan_to_income(1, 1e15) == pytest.approx(1e-15)


def test_loan_to_assets_zero_assets() -> None:
    assert math.isinf(f.loan_to_assets(500_000, 0))
    assert f.loan_to_assets(0, 0) == 0
    assert f.loan_to_assets(1_000_000, 4_000_000) == pytest.approx(0.25)


def test_ratio_series_with_zero_denominator() -> None:
    out = f.loan_to_income(pd.Series([10.0, 0.0, 5.0]), pd.Series([2.0, 0.0, 0.0]))
    assert out.iloc[0] == 5 and out.iloc[1] == 0 and np.isinf(out.iloc[2])


def test_total_assets() -> None:
    df = pd.DataFrame(
        {
            "residential_assets_value": [1, 0],
            "commercial_assets_value": [2, 0],
            "luxury_assets_value": [3, 0],
            "bank_asset_value": [4, 0],
        }
    )
    assert f.total_assets(df).tolist() == [10.0, 0.0]


def test_total_assets_missing_columns() -> None:
    df = pd.DataFrame({"bank_asset_value": [5]})
    assert f.total_assets(df).tolist() == [5.0]
    assert f.total_assets(pd.DataFrame({"x": [1]})).tolist() == [0.0]


# CIBIL band
def test_cibil_band() -> None:
    bands = f.cibil_band([300, 550, 551, 900]).astype(str).tolist()
    assert bands == ["300-450", "451-550", "551-650", "751-900"]


# add_features
def test_add_features_columns_and_no_mutation() -> None:
    df = pd.DataFrame(
        {
            "loan_amount": [3_000_000],
            "loan_term": [10],
            "income_annum": [1_000_000],
            "residential_assets_value": [1_000_000],
            "commercial_assets_value": [0],
            "luxury_assets_value": [1_000_000],
            "bank_asset_value": [0],
        }
    )
    out = f.add_features(df, 0.10)
    assert set(f.DERIVED_COLUMNS) <= set(out.columns)
    assert out["loan_to_income"].iloc[0] == pytest.approx(3.0)
    assert out["loan_to_assets"].iloc[0] == pytest.approx(1.5)
    assert "emi" not in df.columns
