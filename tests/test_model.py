"""Tests for loanlens.model."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from loanlens import model as m


@pytest.fixture(scope="module")
def toy() -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(0)
    n = 300
    cibil = rng.integers(300, 901, n)
    income = rng.integers(1_000_000, 9_000_000, n).astype(float)
    df = pd.DataFrame(
        {
            "no_of_dependents": rng.integers(0, 6, n),
            "education": rng.choice(["Graduate", "Not Graduate"], n),
            "self_employed": rng.choice(["Yes", "No"], n),
            "income_annum": income,
            "loan_amount": income * rng.uniform(1.5, 4.0, n),
            "loan_term": rng.choice([2, 4, 10, 20], n),
            "cibil_score": cibil,
            "residential_assets_value": rng.integers(0, 9_000_000, n),
            "commercial_assets_value": rng.integers(0, 9_000_000, n),
            "luxury_assets_value": rng.integers(0, 9_000_000, n),
            "bank_asset_value": rng.integers(0, 9_000_000, n),
        }
    )
    df["loan_status"] = (cibil > 550).astype(int)
    return df, df["loan_status"]


@pytest.mark.parametrize("kind", ["logreg", "random_forest", "xgboost"])
def test_make_estimator_fits_with_categoricals(kind, toy) -> None:
    df, y = toy
    frame = m.build_frame(df)
    est = m.make_estimator(kind, list(m.FULL_FEATURES)).fit(frame[list(m.FULL_FEATURES)], y)
    proba = est.predict_proba(frame[list(m.FULL_FEATURES)])[:, 1]
    assert proba.shape == (len(df),) and ((proba >= 0) & (proba <= 1)).all()


def test_protected_attributes_are_blocked() -> None:
    with pytest.raises(ValueError, match="Protected"):
        m.make_estimator("xgboost", ["cibil_score", "gender"])
    with pytest.raises(ValueError, match="Protected"):
        m.make_estimator("xgboost", ["cibil_score", "marital_status"])


def test_no_protected_attributes_in_feature_lists() -> None:
    for cols in (m.FULL_FEATURES, m.FINAL_FEATURES):
        m._check_features(cols)  # raises if any protected attribute slipped in


def test_monotone_logreg_rejected() -> None:
    with pytest.raises(ValueError):
        m.make_estimator("logreg", ["cibil_score"], {"cibil_score": 1})


def test_cross_validate_outputs(toy) -> None:
    df, y = toy
    frame = m.build_frame(df)
    res = m.cross_validate("x", m.make_estimator("xgboost", ["cibil_score"]), frame, y)
    assert len(res.folds) == 5
    assert set(m.classification_metrics(y, y.astype(float))) <= set(res.folds.columns)
    assert res.confusion.sum() == len(y)
    assert res.oof_proba.shape == (len(y),)
    assert res.mean["roc_auc"] > 0.95  # toy target is a pure CIBIL rule


def test_cross_validate_is_deterministic(toy) -> None:
    df, y = toy
    frame = m.build_frame(df)
    est = m.make_estimator("random_forest", ["cibil_score", "loan_term"])
    a = m.cross_validate("a", est, frame, y).oof_proba
    b = m.cross_validate("b", est, frame, y).oof_proba
    np.testing.assert_array_equal(a, b)


def test_classification_metrics_perfect() -> None:
    y = np.array([0, 0, 1, 1])
    out = m.classification_metrics(y, np.array([0.1, 0.2, 0.8, 0.9]))
    assert out["roc_auc"] == 1 and out["f1"] == 1 and out["accuracy"] == 1


def test_save_and_load_roundtrip(toy, tmp_path: Path) -> None:
    df, _ = toy
    art = m.train_final(df)
    path = m.save_artifact(art, tmp_path / "model.joblib")
    loaded = m.load_artifact(path)
    assert loaded["features"] == list(m.FINAL_FEATURES)
    assert loaded["version"] == m.MODEL_VERSION
    assert path.with_suffix(".json").exists()
    frame = m.build_frame(df)
    np.testing.assert_allclose(m.predict_proba(loaded, frame), m.predict_proba(art, frame))


def test_load_missing_artifact_gives_instructions(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="python -m loanlens.model"):
        m.load_artifact(tmp_path / "nope.joblib")


# Properties of the real saved model
def test_artifact_contents(artifact) -> None:
    for key in ("model", "features", "version", "training_ranges", "benchmarks", "monotone"):
        assert key in artifact
    assert artifact["features"] == list(m.FINAL_FEATURES)
    assert "loan_amount" not in artifact["features"]


def test_final_model_bigger_loan_never_helps(artifact, clean_df) -> None:
    frame = m.build_frame(clean_df)
    probe = m.loan_size_probe(artifact["model"], frame, artifact["features"], factor=1.25)
    assert probe["share_increased"] == 0


def test_final_model_higher_cibil_never_hurts(artifact, clean_df) -> None:
    frame = m.build_frame(clean_df.sample(500, random_state=1))
    before = m.predict_proba(artifact, frame)
    after = m.predict_proba(artifact, frame.assign(cibil_score=frame["cibil_score"] + 50))
    assert (after >= before - 1e-9).all()
