"""Analytics and About pages, plus checks shared by every page."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from loanlens import batch, charts, explain, storage
from loanlens import model as model_mod
from loanlens.access import DEMO_PASSWORD
from loanlens.config import load_policy
from loanlens.presentation import policy_table, thresholds_note

PAGES = [
    "Home.py",
    "pages/1_Check_My_Eligibility.py",
    "pages/2_Bulk_Check.py",
    "pages/3_Analytics.py",
    "pages/4_About.py",
]


def _run(app_path: str, page: str, manager: bool = False):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(Path(app_path) / page), default_timeout=120).run()
    if manager:
        at.toggle(key="manager_mode").set_value(True).run()
        at.text_input(key="manager_password").set_value(DEMO_PASSWORD).run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_with_footer(app_path, artifact, page) -> None:
    at = _run(app_path, page, manager=page.endswith("Bulk_Check.py"))
    assert not at.exception, at.exception
    assert any("Prototype - not a lending decision" in c.value for c in at.caption)
    assert at.title[0].value  # consistent page title


@pytest.mark.parametrize(
    "page", ["pages/1_Check_My_Eligibility.py", "pages/2_Bulk_Check.py", "pages/4_About.py"]
)
def test_illustrative_thresholds_notice(app_path, artifact, page) -> None:
    """Review decision 5: the placeholder notice is on the customer, bulk and About pages."""
    at = _run(app_path, page, manager=page.endswith("Bulk_Check.py"))
    texts = [c.value for c in at.caption] + [w.value for w in at.warning]
    assert any("illustrative placeholders" in t for t in texts)


def test_model_missing_shows_friendly_message(app_path, monkeypatch) -> None:
    import ui_common

    def missing():
        raise FileNotFoundError("no model")

    ui_common._cached_artifact.clear()
    monkeypatch.setattr(model_mod, "load_artifact", missing)
    at = _run(app_path, "pages/1_Check_My_Eligibility.py")
    assert not at.exception
    assert any("python -m loanlens.model" in e.value for e in at.error)
    ui_common._cached_artifact.clear()


# Analytics -------------------------------------------------------------------------------


def test_analytics_without_batches(app_path, artifact, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(storage, "db_path", lambda policy=None: tmp_path / "none.sqlite")
    at = _run(app_path, "pages/3_Analytics.py")
    assert not at.exception and not at.error
    assert any("No batch has been checked yet" in i.value for i in at.info)
    assert len(at.get("plotly_chart")) == 4  # CIBIL band, term, loan size, importance


def test_analytics_shows_latest_batch(app_path, artifact, monkeypatch, tmp_path) -> None:
    db = tmp_path / "batches.sqlite"
    parsed = batch.parse_upload(batch.template_csv())
    results = batch.score(parsed, artifact=artifact)
    storage.save_summary(batch.summarise(results, parsed), "1.0.0", results, path=db)
    monkeypatch.setattr(storage, "db_path", lambda policy=None: db)
    at = _run(app_path, "pages/3_Analytics.py")
    assert not at.exception
    assert any(m.value == "3" for m in at.metric)
    assert len(at.get("plotly_chart")) == 6


def test_feature_importance(artifact, clean_df) -> None:
    imp = explain.feature_importance(artifact, model_mod.build_frame(clean_df))
    assert imp.sum() == pytest.approx(1.0, abs=1e-6)
    assert imp.index[0] == "CIBIL score"
    assert set(imp.index) == set(explain.FEATURE_LABELS.values())
    fig = charts.feature_importance_bar(imp)
    assert len(fig.data[0].y) == len(imp)


def test_counts_bar() -> None:
    fig = charts.counts_bar({"a": 3, "b": 1}, "t", "x")
    assert list(fig.data[0].x) == ["a", "b"]
    fig_h = charts.counts_bar(pd.Series({"a": 3, "b": 1}), "t", "x", horizontal=True)
    assert list(fig_h.data[0].y) == ["b", "a"]


# About -----------------------------------------------------------------------------------


def test_policy_table_matches_config() -> None:
    policy = load_policy()
    table = policy_table(policy)
    rules = table[table["Config key"].isin(type(policy.rules).model_fields)]
    assert len(rules) == 6
    for _, row in rules.iterrows():
        enforced = getattr(policy.rules, row["Config key"]).enforce
        assert row["Enforced"].startswith("Yes" if enforced else "No")
    assert (table["Status"] == "Placeholder").all()
    assert "illustrative placeholders" in thresholds_note(policy)


def test_about_page_content(app_path, artifact) -> None:
    at = _run(app_path, "pages/4_About.py")
    assert not at.exception
    assert any("Approval, not default" in w.value for w in at.warning)
    assert any("pre-screening and decision-support prototype" in c.value for c in at.caption)
    md = " ".join(m.value for m in at.markdown)
    assert "Model Card" in md and "does not predict default" in md
    assert "public, synthetic Kaggle data" in md
    shown = at.dataframe[0].value
    assert "max_emi_to_income" in set(shown["Config key"])
