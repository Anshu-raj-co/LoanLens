"""Tests for loanlens.charts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from loanlens import charts


@pytest.fixture
def df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 200
    cibil = rng.integers(300, 901, n)
    return pd.DataFrame(
        {
            "cibil_score": cibil,
            "loan_term": rng.choice([2, 4, 6, 8], n),
            "education": rng.choice(["Graduate", "Not Graduate"], n),
            "income_annum": rng.integers(200_000, 10_000_000, n),
            "loan_status": (cibil > 550).astype(int),
        }
    )


def test_cibil_band_boundaries() -> None:
    bands = charts.cibil_band(pd.Series([300, 450, 451, 550, 551, 900]))
    assert bands.astype(str).tolist() == [
        "300-450",
        "300-450",
        "451-550",
        "451-550",
        "551-650",
        "751-900",
    ]


def test_approval_rate_table() -> None:
    frame = pd.DataFrame({"g": ["a", "a", "b", "b", "b"], "loan_status": [1, 0, 1, 1, 1]})
    table = charts.approval_rate_table(frame, "g").set_index("g")
    assert table.loc["a", "applications"] == 2
    assert table.loc["a", "approval_rate"] == pytest.approx(0.5)
    assert table.loc["b", "approved"] == 3


def test_approval_rate_table_with_series(df: pd.DataFrame) -> None:
    table = charts.approval_rate_table(df, charts.cibil_band(df["cibil_score"]))
    assert table["applications"].sum() == len(df)
    assert table["approval_rate"].between(0, 1).all()


def test_approval_by_cibil_band(df: pd.DataFrame) -> None:
    fig = charts.approval_by_cibil_band(df)
    assert isinstance(fig, go.Figure)
    assert list(fig.data[0].x) == list(charts.CIBIL_LABELS)
    # Toy target: nobody at or below 550 is approved.
    assert fig.data[0].y[0] == 0 and fig.data[0].y[-1] == 1


def test_approval_rate_bar_categorical(df: pd.DataFrame) -> None:
    fig = charts.approval_rate_bar(df, "education", "By education")
    assert set(fig.data[0].x) == {"Graduate", "Not Graduate"}
    assert fig.layout.title.text == "By education"


def test_approval_by_quantile_band(df: pd.DataFrame) -> None:
    fig = charts.approval_by_quantile_band(df, "income_annum", q=4)
    assert len(fig.data[0].x) == 4


def test_approval_by_quantile_band_derived_values(df: pd.DataFrame) -> None:
    ratio = df["income_annum"] / 1_000_000
    fig = charts.approval_by_quantile_band(df, "ratio", q=3, values=ratio)
    assert len(fig.data[0].x) == 3


def test_distribution_by_status(df: pd.DataFrame) -> None:
    fig = charts.distribution_by_status(df, "cibil_score")
    assert {t.name for t in fig.data} == {"Approved", "Rejected"}


def test_approval_heatmap(df: pd.DataFrame) -> None:
    bands = charts.cibil_band(df["cibil_score"]).rename("cibil_band")
    fig = charts.approval_heatmap(df, bands, "loan_term", "CIBIL x term")
    z = np.array(fig.data[0].z, dtype=float)
    assert z.shape[1] == 4
    assert np.nanmax(z) <= 1 and np.nanmin(z) >= 0
