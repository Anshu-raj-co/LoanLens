"""Analytics aggregates: the committed file, its round trip and the page without the data folder."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from app_support import open_page

from loanlens import analytics, charts, cleaning, explain, services
from loanlens import model as model_mod

ANALYTICS_PAGE = "pages/3_Analytics.py"


def test_committed_file_exists_and_is_small() -> None:
    path = analytics.AGGREGATES_PATH
    assert path.exists(), "run python scripts/build_hosted_assets.py"
    assert path.stat().st_size < 50_000


def test_committed_file_has_no_row_level_data() -> None:
    content = analytics.load()
    text = json.dumps(content)
    assert "loan_id" not in text and "income_annum" not in text
    assert set(content) == {
        "format_version", "description", "training_rows", "training_data_sha256", "tables",
        "feature_importance",
    }  # fmt: skip
    for name in analytics.TABLES:
        rows = content["tables"][name]["rows"]
        assert 1 < len(rows) <= 20  # one row per group, not per applicant
        assert {"group", *analytics.TABLE_COLUMNS} == set(rows[0])
    assert (
        sum(r["applications"] for r in content["tables"]["by_cibil_band"]["rows"])
        == (content["training_rows"])
    )


def test_committed_file_matches_the_data(clean_df, artifact) -> None:
    """The committed file is what the build script produces from the current data and model."""
    importance = explain.feature_importance(artifact, model_mod.build_frame(clean_df))
    built = analytics.build(
        clean_df, importance, artifact, model_mod.data_hash(cleaning.PROCESSED_PATH)
    )
    assert analytics.load() == built


def test_round_trip_gives_identical_charts(clean_df, artifact, tmp_path: Path) -> None:
    importance = explain.feature_importance(artifact, model_mod.build_frame(clean_df))
    path = analytics.write(
        analytics.build(clean_df, importance, artifact, "h"), tmp_path / "a.json"
    )
    stored = analytics.from_aggregates(analytics.load(path))
    live = analytics.from_frame(clean_df)
    assert stored.source == analytics.AGGREGATES and live.source == analytics.TRAINING_DATA
    assert stored.rows == live.rows == len(clean_df)
    for name in analytics.TABLES:
        a = charts.approval_rate_chart(getattr(stored, name), "t", "x")
        b = charts.approval_rate_chart(getattr(live, name), "t", "x")
        assert list(a.data[0].x) == list(b.data[0].x)
        assert list(a.data[0].y) == pytest.approx(list(b.data[0].y), abs=1e-6)
        assert list(a.data[0].text) == list(b.data[0].text)
    # The page's previous chart functions give the same figures as the table versions.
    old = charts.approval_by_quantile_band(clean_df, "loan_amount", q=5, title="t")
    new = charts.approval_rate_chart(live.by_loan_size, "t", "loan_amount")
    assert old.to_json() == new.to_json()
    restored = analytics.importance_from_aggregates(analytics.load(path), artifact)
    pd.testing.assert_series_equal(
        restored, importance.astype("float64"), check_names=False, atol=1e-6
    )


def test_importance_ignored_for_another_model() -> None:
    content = analytics.load()
    other = {"version": "9.9.9", "trained_at": "2030-01-01T00:00:00+00:00"}
    assert analytics.importance_from_aggregates(content, other) is None
    assert analytics.importance_from_aggregates({}, other) is None


def test_load_missing_and_bad_files(tmp_path: Path) -> None:
    assert analytics.load(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(analytics.AggregatesError, match="could not be read"):
        analytics.load(bad)
    bad.write_text(json.dumps({"format_version": 99}), encoding="utf-8")
    with pytest.raises(analytics.AggregatesError, match="unknown format"):
        analytics.load(bad)
    with pytest.raises(analytics.AggregatesError, match="incomplete"):
        analytics.from_aggregates({"format_version": 1, "tables": {}})


def _without_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cleaning, "PROCESSED_PATH", tmp_path / "absent.csv")


def test_services_fall_back_to_aggregates(monkeypatch, tmp_path, artifact) -> None:
    from app_support import new_session

    from loanlens import auth

    manager = new_session(auth.MANAGER).principal
    _without_data(monkeypatch, tmp_path)
    data = services.analytics_data(manager)
    assert data is not None and data.source == analytics.AGGREGATES
    assert data.rows == analytics.load()["training_rows"]
    importance = services.feature_importance(manager, artifact)
    assert importance is not None and importance.index[0] == "CIBIL score"
    monkeypatch.setattr(analytics, "AGGREGATES_PATH", tmp_path / "none.json")
    assert services.analytics_data(manager) is None
    assert services.feature_importance(manager, artifact) is None


def test_analytics_page_without_data_folder(app_path, artifact, monkeypatch, tmp_path) -> None:
    _without_data(monkeypatch, tmp_path)
    at = open_page(ANALYTICS_PAGE).run()
    assert not at.exception and not at.error
    assert any("stored aggregates" in c.value for c in at.caption)
    assert len(at.get("plotly_chart")) == 4


def test_analytics_page_with_neither(app_path, artifact, monkeypatch, tmp_path) -> None:
    _without_data(monkeypatch, tmp_path)
    monkeypatch.setattr(analytics, "AGGREGATES_PATH", tmp_path / "none.json")
    at = open_page(ANALYTICS_PAGE).run()
    assert not at.exception
    assert any("build_hosted_assets.py" in e.value for e in at.error)


def test_analytics_page_with_broken_file(app_path, artifact, monkeypatch, tmp_path) -> None:
    _without_data(monkeypatch, tmp_path)
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    monkeypatch.setattr(analytics, "AGGREGATES_PATH", broken)
    at = open_page(ANALYTICS_PAGE).run()
    assert not at.exception
    assert any("could not be read" in e.value for e in at.error)


def test_build_script_check_mode(clean_df, artifact, tmp_path, capsys) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_hosted_assets", cleaning.PROJECT_ROOT / "scripts" / "build_hosted_assets.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path / "agg.json"
    assert module.main(["--out", str(out)]) == 0
    assert module.main(["--check", "--out", str(out)]) == 0
    out.write_text(json.dumps({"format_version": 1}), encoding="utf-8")
    assert module.main(["--check", "--out", str(out)]) == 1
    assert "out of date" in capsys.readouterr().out
