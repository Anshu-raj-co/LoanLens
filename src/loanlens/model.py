"""Model training, cross-validation, calibration and persistence.

The model predicts the **approval decision** (1 = approved) in the synthetic training
data. It does not predict default. All preprocessing happens inside sklearn Pipelines,
so scalers and encoders are fitted inside each cross-validation fold only.

Run ``python -m loanlens.model`` to train the final model and save it to ``models/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

from loanlens import features
from loanlens.config import PROJECT_ROOT

SEED = 42
TARGET = "loan_status"
MODEL_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODEL_DIR / "loanlens_model.joblib"
MODEL_VERSION = "1.0.0"

ModelKind = Literal["logreg", "random_forest", "xgboost"]

# Columns available for modelling. Gender and marital status do not exist in the
# primary dataset and must never be added.
RAW_NUMERIC: tuple[str, ...] = (
    "no_of_dependents",
    "income_annum",
    "loan_amount",
    "loan_term",
    "cibil_score",
    *features.ASSET_COLUMNS,
)
CATEGORICAL: tuple[str, ...] = ("education", "self_employed")
FULL_FEATURES: tuple[str, ...] = (*RAW_NUMERIC, *CATEGORICAL, "loan_to_income")
BANNED_FEATURES: frozenset[str] = frozenset({"gender", "sex", "married", "marital_status"})

# Final configuration, chosen in notebooks/03_modelling.ipynb (see decisions_log D-019..D-023).
# Raw loan_amount is deliberately excluded: with it, the model can re-learn the synthetic
# "bigger loan -> approval" quirk around the loan_to_income constraint.
FINAL_KIND: ModelKind = "xgboost"
FINAL_FEATURES: tuple[str, ...] = (
    "cibil_score",
    "loan_term",
    "loan_to_income",
    "income_annum",
    "total_assets",
)
# +1: approval probability can only rise with the feature; -1: it can only fall.
FINAL_MONOTONE: dict[str, int] = {"cibil_score": 1, "loan_to_income": -1}
FINAL_CALIBRATION: Literal["isotonic", "sigmoid"] = "isotonic"


def build_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived features the model may use (row-wise, no fitting, no leakage)."""
    return features.add_features(df)


def _check_features(cols: tuple[str, ...] | list[str]) -> None:
    banned = {c for c in cols if any(b in c.lower() for b in BANNED_FEATURES)}
    if banned:
        raise ValueError(f"Protected attributes must not be used as features: {sorted(banned)}")


def make_estimator(
    kind: ModelKind,
    feature_cols: tuple[str, ...] | list[str],
    monotone: dict[str, int] | None = None,
    seed: int = SEED,
) -> Pipeline:
    """Build an unfitted preprocessing + model Pipeline.

    Args:
        kind: ``"logreg"``, ``"random_forest"`` or ``"xgboost"``.
        feature_cols: columns to use; categorical ones are one-hot encoded.
        monotone: optional monotonic constraints ``{feature: +1 | -1}`` (tree models only).
        seed: random seed.
    """
    feature_cols = list(feature_cols)
    _check_features(feature_cols)
    cat = [c for c in feature_cols if c in CATEGORICAL]
    num = [c for c in feature_cols if c not in CATEGORICAL]
    num_step: Any = StandardScaler() if kind == "logreg" else "passthrough"
    pre = ColumnTransformer(
        [
            ("num", num_step, num),
            (
                "cat",
                OneHotEncoder(drop="if_binary", handle_unknown="ignore", sparse_output=False),
                cat,
            ),
        ],
        verbose_feature_names_out=False,
        sparse_threshold=0,
    ).set_output(transform="pandas")

    if kind == "logreg":
        if monotone:
            raise ValueError("Logistic regression is already monotone in each feature")
        clf: Any = LogisticRegression(max_iter=5000, C=1.0, random_state=seed)
    elif kind == "random_forest":
        cst = None
        if monotone:
            if cat:
                raise ValueError("Monotone random forest supports numeric features only")
            cst = [monotone.get(c, 0) for c in num]
        clf = RandomForestClassifier(
            n_estimators=300, min_samples_leaf=2, monotonic_cst=cst, random_state=seed, n_jobs=1
        )
    elif kind == "xgboost":
        clf = XGBClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.1,
            subsample=1.0,
            eval_metric="logloss",
            monotone_constraints=dict(monotone) if monotone else None,
            random_state=seed,
            n_jobs=1,
        )
    else:  # pragma: no cover - guarded by the Literal type
        raise ValueError(f"Unknown model kind: {kind}")
    return Pipeline([("pre", pre), ("clf", clf)])


def calibrated(estimator: Pipeline, method: Literal["isotonic", "sigmoid"], seed: int = SEED):
    """Wrap an estimator in probability calibration (internal 5-fold CV, single base model).

    ``ensemble=False`` fits the calibrator on out-of-fold predictions and then refits one
    base model on all data, so SHAP can explain a single model.
    """
    return CalibratedClassifierCV(
        estimator,
        method=method,
        cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=seed),
        ensemble=False,
    )


def classification_metrics(y_true, proba, threshold: float = 0.5) -> dict[str, float]:
    """ROC-AUC, PR-AUC, precision, recall, F1, accuracy, Brier score and log loss."""
    pred = (np.asarray(proba) >= threshold).astype(int)
    return {
        "roc_auc": roc_auc_score(y_true, proba),
        "pr_auc": average_precision_score(y_true, proba),
        "precision": precision_score(y_true, pred, zero_division=0),
        "recall": recall_score(y_true, pred, zero_division=0),
        "f1": f1_score(y_true, pred, zero_division=0),
        "accuracy": accuracy_score(y_true, pred),
        "brier": brier_score_loss(y_true, proba),
        "log_loss": log_loss(y_true, np.clip(proba, 1e-6, 1 - 1e-6)),
    }


@dataclass
class CVResult:
    """Cross-validation output: per-fold metrics, out-of-fold probabilities, confusion matrix."""

    name: str
    folds: pd.DataFrame
    oof_proba: np.ndarray
    confusion: np.ndarray
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def mean(self) -> pd.Series:
        return self.folds.mean()

    @property
    def std(self) -> pd.Series:
        return self.folds.std(ddof=0)


def cross_validate(
    name: str,
    estimator,
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 5,
    seed: int = SEED,
    threshold: float = 0.5,
) -> CVResult:
    """Stratified k-fold CV. Every fit (including preprocessing) happens inside the fold."""
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    oof = np.zeros(len(y), dtype=float)
    rows = []
    for train_idx, test_idx in cv.split(X, y):
        model = clone(estimator).fit(X.iloc[train_idx], y.iloc[train_idx])
        proba = model.predict_proba(X.iloc[test_idx])[:, 1]
        oof[test_idx] = proba
        rows.append(classification_metrics(y.iloc[test_idx], proba, threshold))
    cm = confusion_matrix(y, (oof >= threshold).astype(int), labels=[0, 1])
    return CVResult(name=name, folds=pd.DataFrame(rows), oof_proba=oof, confusion=cm)


def summary_table(results: list[CVResult]) -> pd.DataFrame:
    """One row per CV result with mean metrics (and F1 std)."""
    rows = []
    for r in results:
        row = r.mean.to_dict()
        row["f1_std"] = r.std["f1"]
        rows.append({"model": r.name, **row})
    return pd.DataFrame(rows).set_index("model")


def loan_size_probe(
    fitted, frame: pd.DataFrame, feature_cols: list[str] | tuple[str, ...], factor: float = 1.25
) -> dict[str, float]:
    """Scale every loan by ``factor`` (income fixed) and measure the change in probability.

    Used to check that a model cannot learn "a bigger loan improves approval". Returns the
    mean probability change and the share of rows whose probability went up.
    """
    cols = list(feature_cols)
    bigger = build_frame(frame.assign(loan_amount=frame["loan_amount"] * factor))
    before = fitted.predict_proba(frame[cols])[:, 1]
    after = fitted.predict_proba(bigger[cols])[:, 1]
    diff = after - before
    return {"mean_change": float(diff.mean()), "share_increased": float((diff > 1e-9).mean())}


def _training_ranges(X: pd.DataFrame) -> dict[str, tuple[float, float]]:
    return {c: (float(X[c].min()), float(X[c].max())) for c in X.columns}


def _approved_benchmarks(frame: pd.DataFrame, y: pd.Series) -> dict[str, float]:
    approved = frame.loc[y == 1]
    cols = [c for c in (*RAW_NUMERIC, *features.DERIVED_COLUMNS) if c in frame.columns]
    return {c: float(approved[c].median()) for c in cols}


def train_final(
    df: pd.DataFrame,
    kind: ModelKind = FINAL_KIND,
    feature_cols: tuple[str, ...] = FINAL_FEATURES,
    monotone: dict[str, int] | None = None,
    calibration: Literal["isotonic", "sigmoid"] = FINAL_CALIBRATION,
    cv_metrics: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Fit the calibrated final model on all data and return a saveable artifact.

    The artifact holds the model, its feature list, a version string, training ranges
    (for out-of-range warnings), approved-applicant medians (benchmarks for reasons) and
    the cross-validated metrics.
    """
    monotone = FINAL_MONOTONE if monotone is None else monotone
    frame = build_frame(df)
    X, y = frame[list(feature_cols)], frame[TARGET]
    model = calibrated(make_estimator(kind, feature_cols, monotone), calibration).fit(X, y)
    raw_inputs = [c for c in (*RAW_NUMERIC, "loan_to_income") if c in frame.columns]
    return {
        "model": model,
        "features": list(feature_cols),
        "kind": kind,
        "monotone": dict(monotone),
        "calibration": calibration,
        "version": MODEL_VERSION,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_train": int(len(y)),
        "seed": SEED,
        "training_ranges": _training_ranges(frame[raw_inputs]),
        "benchmarks": _approved_benchmarks(frame, y),
        "cv_metrics": cv_metrics or {},
    }


def save_artifact(artifact: dict[str, Any], path: Path = MODEL_PATH) -> Path:
    """Save the artifact with joblib, plus a small JSON sidecar with its metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, path)
    meta = {k: v for k, v in artifact.items() if k != "model"}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


@lru_cache(maxsize=4)
def load_artifact(path: Path = MODEL_PATH) -> dict[str, Any]:
    """Load (and cache) a saved artifact.

    Raises:
        FileNotFoundError: with instructions if the model has not been trained yet.
    """
    if not Path(path).exists():
        raise FileNotFoundError(
            f"No trained model at {path}. Run `python -m loanlens.model` to train it."
        )
    return joblib.load(path)


def base_pipeline(artifact: dict[str, Any]) -> Pipeline:
    """The single fitted (uncalibrated) pipeline inside the calibrated model, used by SHAP."""
    return artifact["model"].calibrated_classifiers_[0].estimator


def predict_proba(artifact: dict[str, Any], frame: pd.DataFrame) -> np.ndarray:
    """Calibrated approval probability for each row of a frame with derived features."""
    return artifact["model"].predict_proba(frame[artifact["features"]])[:, 1]


def main() -> None:  # pragma: no cover - exercised via the CLI
    """Cross-validate the final configuration, train it on all data and save it."""
    from loanlens import cleaning

    if not cleaning.PROCESSED_PATH.exists():
        if not cleaning.RAW_PATH.exists():
            raise SystemExit(
                f"Missing {cleaning.RAW_PATH}. Download loan_approval_dataset.csv (see README.md, "
                "'Data') into data/raw/ and run this command again."
            )
        cleaning.build_clean_dataset()
        print(f"Built the cleaned dataset at {cleaning.PROCESSED_PATH}")
    df = pd.read_csv(cleaning.PROCESSED_PATH)
    frame = build_frame(df)
    est = calibrated(make_estimator(FINAL_KIND, FINAL_FEATURES, FINAL_MONOTONE), FINAL_CALIBRATION)
    cv = cross_validate("final", est, frame[list(FINAL_FEATURES)], frame[TARGET])
    metrics = {k: round(float(v), 4) for k, v in cv.mean.items()}
    artifact = train_final(df, cv_metrics=metrics)
    path = save_artifact(artifact)
    print(f"Saved model {artifact['version']} ({FINAL_KIND}, {FINAL_CALIBRATION}) to {path}")
    print("CV metrics:", metrics)


if __name__ == "__main__":  # pragma: no cover
    main()
