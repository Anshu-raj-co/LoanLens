"""Display helpers (Indian digit grouping for INR amounts)."""

from __future__ import annotations

import math


def group_indian(number: float) -> str:
    """Format a number with Indian digit grouping, rounded to whole units.

    >>> group_indian(1250000)
    '12,50,000'
    """
    if not math.isfinite(number):
        return "n/a"
    sign = "-" if number < 0 else ""
    digits = str(int(round(abs(number))))
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join(parts + [tail])


def inr(amount: float) -> str:
    """Format an amount as rupees, e.g. ``'Rs 12,50,000'``."""
    return f"Rs {group_indian(amount)}"


def times(ratio: float) -> str:
    """Format a ratio as a multiple, e.g. ``'3.2x'``."""
    return "n/a" if not math.isfinite(ratio) else f"{ratio:.1f}x"


def pct(ratio: float) -> str:
    """Format a fraction as a whole percentage, e.g. ``'48%'``."""
    return "n/a" if not math.isfinite(ratio) else f"{ratio:.0%}"


SCORE_LABEL = "model score on synthetic data - indicative only"


def score_percent(probability: float) -> str:
    """Probability as a percentage that never reads 0% or 100% (display only)."""
    if not math.isfinite(probability):
        return "n/a"
    if probability > 0.99:
        return ">99%"
    if probability < 0.01:
        return "<1%"
    return f"{probability:.0%}"


def likelihood_band(probability: float, bands) -> str:
    """Verbal band for a probability, using the lower bounds in ``bands``.

    ``bands`` is ``config.ProbabilityBands`` (very_likely > likely > borderline > unlikely).
    """
    if probability >= bands.very_likely:
        return "Very likely"
    if probability >= bands.likely:
        return "Likely"
    if probability >= bands.borderline:
        return "Borderline"
    if probability >= bands.unlikely:
        return "Unlikely"
    return "Very unlikely"


def likelihood_text(probability: float, bands) -> str:
    """E.g. ``'96% - Very likely'``."""
    return f"{score_percent(probability)} - {likelihood_band(probability, bands)}"
