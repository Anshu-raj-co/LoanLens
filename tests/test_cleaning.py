"""Tests for loanlens.cleaning."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from loanlens import cleaning as c


@pytest.fixture
def raw_df() -> pd.DataFrame:
    """A tiny frame shaped like the raw primary dataset, including its quirks."""
    return pd.DataFrame(
        {
            "loan_id": [1, 2, 3],
            " no_of_dependents": [2, 0, 3],
            " education": [" Graduate", " Not Graduate", " Graduate"],
            " self_employed": [" No", " Yes", " No"],
            " income_annum": [9_600_000, 4_100_000, 9_100_000],
            " loan_amount": [29_900_000, 12_200_000, 29_700_000],
            " loan_term": [12, 8, 20],
            " cibil_score": [778, 417, 506],
            " residential_assets_value": [2_400_000, -100_000, 7_100_000],
            " commercial_assets_value": [17_600_000, 2_200_000, 4_500_000],
            " luxury_assets_value": [22_700_000, 8_800_000, 33_300_000],
            " bank_asset_value": [8_000_000, 3_300_000, 12_800_000],
            " loan_status": [" Approved", " Rejected", " Rejected"],
        }
    )


# normalise_column_name / normalise_columns
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" cibil_score", "cibil_score"),
        ("Loan Term (years)", "loan_term"),
        ("  Income-Annum ", "income_annum"),
        ("loan_status", "loan_status"),
    ],
)
def test_normalise_column_name(raw: str, expected: str) -> None:
    assert c.normalise_column_name(raw) == expected


def test_normalise_columns_strips_spaces(raw_df: pd.DataFrame) -> None:
    out = c.normalise_columns(raw_df)
    assert all(col == col.strip() for col in out.columns)
    assert "cibil_score" in out.columns
    assert " cibil_score" in raw_df.columns  # input not mutated


def test_normalise_columns_rejects_collisions() -> None:
    df = pd.DataFrame({"A ": [1], " a": [2]})
    with pytest.raises(ValueError, match="collide"):
        c.normalise_columns(df)


# strip_string_values
def test_strip_string_values(raw_df: pd.DataFrame) -> None:
    out = c.strip_string_values(raw_df)
    assert out[" education"].tolist() == ["Graduate", "Not Graduate", "Graduate"]
    assert out[" cibil_score"].tolist() == [778, 417, 506]  # numerics untouched
    assert raw_df[" education"].iloc[0] == " Graduate"  # input not mutated


def test_strip_string_values_keeps_nan() -> None:
    df = pd.DataFrame({"x": [" a ", np.nan]})
    out = c.strip_string_values(df)
    assert out["x"].iloc[0] == "a"
    assert pd.isna(out["x"].iloc[1])


# map_target
def test_map_target_maps_values() -> None:
    df = pd.DataFrame({"loan_status": [" Approved", "rejected", "APPROVED "]})
    assert c.map_target(df)["loan_status"].tolist() == [1, 0, 1]


def test_map_target_unknown_value_raises() -> None:
    df = pd.DataFrame({"loan_status": ["Approved", "Pending"]})
    with pytest.raises(ValueError, match="pending"):
        c.map_target(df)


def test_map_target_missing_column_raises() -> None:
    with pytest.raises(KeyError):
        c.map_target(pd.DataFrame({"x": [1]}))


# negative assets
@pytest.fixture
def asset_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "residential_assets_value": [100, -50, 0, -1],
            "bank_asset_value": [10, 20, 30, 40],
        }
    )


def test_count_negative_assets(asset_df: pd.DataFrame) -> None:
    assert c.count_negative_assets(asset_df) == 2
    assert c.count_negative_assets(pd.DataFrame({"x": [-1]})) == 0


def test_handle_negative_assets_clip_zero(asset_df: pd.DataFrame) -> None:
    out = c.handle_negative_assets(asset_df, "clip_zero")
    assert out["residential_assets_value"].tolist() == [100, 0, 0, 0]
    assert len(out) == 4
    assert asset_df["residential_assets_value"].min() == -50  # input not mutated


def test_handle_negative_assets_drop(asset_df: pd.DataFrame) -> None:
    out = c.handle_negative_assets(asset_df, "drop")
    assert out["residential_assets_value"].tolist() == [100, 0]
    assert out.index.tolist() == [0, 1]


def test_handle_negative_assets_nan(asset_df: pd.DataFrame) -> None:
    out = c.handle_negative_assets(asset_df, "nan")
    assert out["residential_assets_value"].isna().sum() == 2
    assert out["bank_asset_value"].tolist() == [10, 20, 30, 40]


def test_handle_negative_assets_bad_strategy(asset_df: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="Unknown strategy"):
        c.handle_negative_assets(asset_df, "median")  # type: ignore[arg-type]


# drop_identifier / drop_duplicate_rows
def test_drop_identifier() -> None:
    df = pd.DataFrame({"loan_id": [1, 2], "x": [3, 4]})
    assert list(c.drop_identifier(df).columns) == ["x"]
    assert list(c.drop_identifier(pd.DataFrame({"x": [1]})).columns) == ["x"]


def test_drop_duplicate_rows() -> None:
    df = pd.DataFrame({"a": [1, 1, 2], "b": [3, 3, 4]})
    out = c.drop_duplicate_rows(df)
    assert len(out) == 2
    assert out.index.tolist() == [0, 1]


# config
def test_load_negative_strategy(tmp_path: Path) -> None:
    good = tmp_path / "good.yaml"
    good.write_text("cleaning:\n  negative_assets_strategy: drop\n", encoding="utf-8")
    assert c.load_negative_strategy(good) == "drop"

    missing = tmp_path / "missing.yaml"
    missing.write_text("rules: {}\n", encoding="utf-8")
    assert c.load_negative_strategy(missing) == "clip_zero"

    bad = tmp_path / "bad.yaml"
    bad.write_text("cleaning:\n  negative_assets_strategy: median\n", encoding="utf-8")
    with pytest.raises(ValueError):
        c.load_negative_strategy(bad)


def test_project_policy_strategy_is_valid() -> None:
    assert c.load_negative_strategy() in c.VALID_STRATEGIES


# full pipeline
def test_clean_end_to_end(raw_df: pd.DataFrame) -> None:
    out = c.clean(raw_df)
    assert "loan_id" not in out.columns
    assert out["loan_status"].tolist() == [1, 0, 0]
    assert out["education"].tolist() == ["Graduate", "Not Graduate", "Graduate"]
    assert (out[list(c.ASSET_COLUMNS)] >= 0).all().all()
    assert len(out) == 3


def test_clean_drop_strategy(raw_df: pd.DataFrame) -> None:
    assert len(c.clean(raw_df, "drop")) == 2


def test_build_clean_dataset(tmp_path: Path, raw_df: pd.DataFrame) -> None:
    raw_path = tmp_path / "raw.csv"
    out_path = tmp_path / "processed" / "clean.csv"
    raw_df.to_csv(raw_path, index=False)
    result = c.build_clean_dataset(raw_path, out_path)
    assert out_path.exists()
    reloaded = pd.read_csv(out_path)
    assert reloaded.shape == result.shape
    assert reloaded["loan_status"].isin([0, 1]).all()


@pytest.mark.skipif(not c.RAW_PATH.exists(), reason="raw dataset not available")
def test_clean_real_dataset() -> None:
    raw = pd.read_csv(c.RAW_PATH)
    out = c.clean(raw)
    assert out.isna().sum().sum() == 0
    assert (out[list(c.ASSET_COLUMNS)] >= 0).all().all()
    assert set(out["loan_status"].unique()) == {0, 1}
    assert "loan_id" not in out.columns
