"""Derived features: EMI, affordability ratios, total assets and CIBIL band.

All functions accept scalars or pandas Series / numpy arrays and never raise on
zero income, zero assets or a zero term. Undefined ratios become ``inf`` (when the
numerator is positive, so the related policy rule fails safely) or ``nan``
(when the EMI itself cannot be computed).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from loanlens.config import load_policy

ASSET_COLUMNS: tuple[str, ...] = (
    "residential_assets_value",
    "commercial_assets_value",
    "luxury_assets_value",
    "bank_asset_value",
)
DERIVED_COLUMNS: tuple[str, ...] = (
    "emi",
    "emi_to_income",
    "loan_to_income",
    "total_assets",
    "loan_to_assets",
)

CIBIL_EDGES: tuple[int, ...] = (300, 450, 550, 650, 750, 900)
CIBIL_LABELS: tuple[str, ...] = ("300-450", "451-550", "551-650", "651-750", "751-900")


def _safe_ratio(numerator, denominator):
    """Divide elementwise; x/0 is ``inf`` for x > 0 and 0 for x == 0."""
    num = np.asarray(numerator, dtype="float64")
    den = np.asarray(denominator, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(den > 0, num / np.where(den > 0, den, 1.0), np.where(num > 0, np.inf, 0.0))
    return _restore(out, numerator, denominator)


def _restore(values: np.ndarray, *like):
    """Return a Series if any input was a Series, a float for scalars, else an array."""
    for obj in like:
        if isinstance(obj, pd.Series):
            return pd.Series(values, index=obj.index)
    if values.ndim == 0:
        return float(values)
    return values


def emi(principal, term_years, annual_rate: float | None = None):
    """Monthly EMI using the standard reducing-balance formula.

    ``EMI = P * r * (1 + r)^n / ((1 + r)^n - 1)`` with ``r`` the monthly rate and
    ``n`` the number of months. A zero rate falls back to ``P / n``. A term of zero
    or less gives ``nan`` (no meaningful EMI).

    Args:
        principal: loan amount in INR.
        term_years: loan term in years.
        annual_rate: annual interest rate as a fraction; defaults to the assumed
            rate in ``config/policy.yaml``.
    """
    if annual_rate is None:
        annual_rate = load_policy().emi.assumed_annual_interest_rate
    p = np.asarray(principal, dtype="float64")
    n = np.asarray(term_years, dtype="float64") * 12
    r = annual_rate / 12
    valid = n > 0
    n_safe = np.where(valid, n, 1.0)
    if r == 0:
        value = p / n_safe
    else:
        growth = (1 + r) ** n_safe
        value = p * r * growth / (growth - 1)
    return _restore(np.where(valid, value, np.nan), principal, term_years)


def emi_to_income(principal, term_years, income_annum, annual_rate: float | None = None):
    """Monthly EMI divided by monthly income (``income_annum / 12``)."""
    return _safe_ratio(emi(principal, term_years, annual_rate), np.asarray(income_annum) / 12)


def loan_to_income(loan_amount, income_annum):
    """Loan amount divided by annual income."""
    return _safe_ratio(loan_amount, income_annum)


def total_assets(df: pd.DataFrame) -> pd.Series:
    """Sum of the four asset columns (missing columns count as 0)."""
    present = [c for c in ASSET_COLUMNS if c in df.columns]
    return df[present].sum(axis=1).astype("float64") if present else pd.Series(0.0, df.index)


def loan_to_assets(loan_amount, assets):
    """Loan amount divided by total assets."""
    return _safe_ratio(loan_amount, assets)


def cibil_band(scores) -> pd.Series:
    """Bucket CIBIL scores into fixed bands; 550 falls in ``451-550``."""
    return pd.cut(
        pd.Series(scores), bins=list(CIBIL_EDGES), labels=list(CIBIL_LABELS), include_lowest=True
    )


def add_features(df: pd.DataFrame, annual_rate: float | None = None) -> pd.DataFrame:
    """Return a copy of ``df`` with every derived column added."""
    out = df.copy()
    out["emi"] = emi(out["loan_amount"], out["loan_term"], annual_rate)
    out["emi_to_income"] = emi_to_income(
        out["loan_amount"], out["loan_term"], out["income_annum"], annual_rate
    )
    out["loan_to_income"] = loan_to_income(out["loan_amount"], out["income_annum"])
    out["total_assets"] = total_assets(out)
    out["loan_to_assets"] = loan_to_assets(out["loan_amount"], out["total_assets"])
    return out
