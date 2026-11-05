"""Bulk Check: CSV in, validated and scored results out (CLAUDE.md section 7).

Pipeline: :func:`read_csv_bytes` -> :func:`map_columns` -> :func:`validate_rows` ->
:func:`score` (chunked, using the same :func:`loanlens.decision.decide_many` core as
customer mode) -> :func:`summarise` / :func:`results_csv`.

Every problem with the file raises :class:`BatchError` with a plain-English message.
Problems with individual rows are collected as :class:`RowError` and those rows are
skipped; they never stop the rest of the batch.
"""

from __future__ import annotations

import csv
import io
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import annotated_types
import numpy as np
import pandas as pd

from loanlens import explain
from loanlens.cleaning import normalise_column_name
from loanlens.config import Policy, load_policy
from loanlens.decision import INPUT_COLUMNS, decide_many
from loanlens.formatting import likelihood_band, score_percent
from loanlens.schema import FIELD_LABELS, ApplicantInput

ID_COLUMN = "applicant_id"
DELIMITERS = (",", ";", "\t", "|")

# Normalised header -> canonical column. Canonical names map to themselves implicitly.
ALIASES: dict[str, str] = {
    # CIBIL
    "cibil": "cibil_score",
    "cibil_score_value": "cibil_score",
    "credit_score": "cibil_score",
    "score": "cibil_score",
    # income
    "income": "income_annum",
    "annual_income": "income_annum",
    "income_annual": "income_annum",
    "yearly_income": "income_annum",
    "income_per_annum": "income_annum",
    "annual_income_inr": "income_annum",
    # loan amount
    "loan": "loan_amount",
    "loan_amt": "loan_amount",
    "amount": "loan_amount",
    "loan_amount_inr": "loan_amount",
    "requested_amount": "loan_amount",
    # term
    "term": "loan_term",
    "loan_term_years": "loan_term",
    "tenure": "loan_term",
    "tenure_years": "loan_term",
    "term_years": "loan_term",
    # assets
    "residential_assets": "residential_assets_value",
    "residential_asset_value": "residential_assets_value",
    "commercial_assets": "commercial_assets_value",
    "commercial_asset_value": "commercial_assets_value",
    "luxury_assets": "luxury_assets_value",
    "luxury_asset_value": "luxury_assets_value",
    "bank_assets": "bank_asset_value",
    "bank_assets_value": "bank_asset_value",
    "bank_balance": "bank_asset_value",
    # identifier
    "id": ID_COLUMN,
    "loan_id": ID_COLUMN,
    "application_id": ID_COLUMN,
    "applicant": ID_COLUMN,
    "customer_id": ID_COLUMN,
}
REQUIRED_COLUMNS: tuple[str, ...] = INPUT_COLUMNS
TEMPLATE_ROWS: tuple[dict[str, Any], ...] = (
    {
        ID_COLUMN: "APP-0001",
        "cibil_score": 780,
        "income_annum": 6000000,
        "loan_amount": 15000000,
        "loan_term": 10,
        "residential_assets_value": 12000000,
        "commercial_assets_value": 4000000,
        "luxury_assets_value": 10000000,
        "bank_asset_value": 5000000,
    },
    {
        ID_COLUMN: "APP-0002",
        "cibil_score": 640,
        "income_annum": 2500000,
        "loan_amount": 7500000,
        "loan_term": 15,
        "residential_assets_value": 3000000,
        "commercial_assets_value": 1000000,
        "luxury_assets_value": 3000000,
        "bank_asset_value": 1000000,
    },
    {
        ID_COLUMN: "APP-0003",
        "cibil_score": 480,
        "income_annum": 5000000,
        "loan_amount": 15000000,
        "loan_term": 10,
        "residential_assets_value": 8000000,
        "commercial_assets_value": 3000000,
        "luxury_assets_value": 9000000,
        "bank_asset_value": 4000000,
    },
)


class BatchError(Exception):
    """A problem with the whole file. ``str(error)`` is a user-facing message."""


@dataclass(frozen=True)
class RowError:
    """A problem with one row. ``row`` is the spreadsheet row number (header = row 1)."""

    row: int
    applicant_id: str
    message: str


@dataclass
class ParsedBatch:
    """Validated input ready for scoring."""

    values: pd.DataFrame  # valid rows only, canonical input columns
    source_rows: np.ndarray  # spreadsheet row number of each valid row
    applicant_ids: pd.Series  # "" when the file has no ID column
    errors: list[RowError] = field(default_factory=list)
    total_rows: int = 0
    renamed: dict[str, str] = field(default_factory=dict)  # original header -> canonical
    ignored: list[str] = field(default_factory=list)  # headers not used

    @property
    def has_ids(self) -> bool:
        return bool((self.applicant_ids != "").any())


# ---- Reading -------------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BatchError("The file could not be read as text. Please upload a CSV file.")


def detect_delimiter(header_line: str) -> str:
    """Pick the delimiter that splits the header line into the most columns."""
    counts = {d: header_line.count(d) for d in DELIMITERS}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def read_csv_bytes(data: bytes, max_rows: int | None = None) -> pd.DataFrame:
    """Read an uploaded CSV into a frame of strings.

    Comma, semicolon, tab and pipe delimiters are detected from the header line.

    Raises:
        BatchError: empty file, no data rows, unreadable file or too many rows.
    """
    text = _decode(data) if data else ""
    if not text.strip():
        raise BatchError("The file is empty. Please upload a CSV with a header row and data.")
    header_line = text.lstrip().splitlines()[0]
    sep = detect_delimiter(header_line)
    try:
        frame = pd.read_csv(
            io.StringIO(text),
            sep=sep,
            dtype=str,
            keep_default_na=False,
            skip_blank_lines=True,
            skipinitialspace=True,
            quoting=csv.QUOTE_MINIMAL,
        )
    except (pd.errors.ParserError, csv.Error, ValueError) as exc:
        raise BatchError(
            "The file could not be read as a CSV table. Check that every row has the same "
            "number of columns, separated by commas."
        ) from exc
    frame = frame.loc[~(frame.apply(lambda c: c.str.strip()) == "").all(axis=1)]
    if frame.empty:
        raise BatchError("The file has a header row but no applicant rows.")
    if max_rows is not None and len(frame) > max_rows:
        raise BatchError(
            f"The file has {len(frame):,} rows, but the maximum is {max_rows:,} rows per file. "
            "Please split it into smaller files."
        )
    return frame.reset_index(drop=True)


# ---- Columns -------------------------------------------------------------------------------


def canonical_name(header: str) -> str:
    """Map a header (any case, spaces, common aliases) to its canonical column name."""
    key = normalise_column_name(header)
    return ALIASES.get(key, key)


def map_columns(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """Rename recognised headers to canonical names.

    Returns:
        (renamed frame with only recognised columns, {original: canonical} for headers that
        were changed, ignored headers).

    Raises:
        BatchError: required columns missing (named exactly) or two headers that map to
            the same column.
    """
    wanted = set(REQUIRED_COLUMNS) | {ID_COLUMN}
    mapping: dict[str, str] = {}
    ignored: list[str] = []
    for col in frame.columns:
        canon = canonical_name(col)
        if canon in wanted:
            if canon in mapping.values():
                first = next(k for k, v in mapping.items() if v == canon)
                raise BatchError(
                    f"Two columns both look like '{canon}': '{first}' and '{col}'. "
                    "Please keep only one."
                )
            mapping[col] = canon
        else:
            ignored.append(str(col))
    missing = [c for c in REQUIRED_COLUMNS if c not in mapping.values()]
    if missing:
        names = ", ".join(f"{c} ({FIELD_LABELS[c]})" for c in missing)
        raise BatchError(f"Required columns are missing: {names}.")
    renamed = {k: v for k, v in mapping.items() if k != v}
    return frame[list(mapping)].rename(columns=mapping), renamed, ignored


# ---- Row validation ------------------------------------------------------------------------


def _bounds(name: str) -> dict[str, float]:
    """Numeric limits of a schema field (kept in sync with ApplicantInput)."""
    out: dict[str, float] = {}
    for meta in ApplicantInput.model_fields[name].metadata:
        for attr, cls in (("gt", annotated_types.Gt), ("ge", annotated_types.Ge),
                          ("le", annotated_types.Le)):  # fmt: skip
            if isinstance(meta, cls):
                out[attr] = float(getattr(meta, attr))
    return out


INTEGER_FIELDS = {"cibil_score", "loan_term"}
_STRIP_TOKENS = ("₹", "Rs.", "Rs", "INR", "inr", "rs.", "rs", ",", " ", "_")


def parse_numbers(raw: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse text such as ``'12,50,000'`` or ``'Rs 5,00,000'`` into floats.

    Returns:
        (values as float with NaN where unparseable, mask of blank cells).
    """
    text = raw.fillna("").astype(str).str.strip()
    blank = text == ""
    cleaned = text
    for token in _STRIP_TOKENS:
        cleaned = cleaned.str.replace(token, "", regex=False)
    return pd.to_numeric(cleaned, errors="coerce"), blank


def _field_errors(name: str, raw: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return (parsed values, error message per row or '') for one input column."""
    label = FIELD_LABELS[name]
    values, blank = parse_numbers(raw)
    msg = pd.Series("", index=raw.index, dtype=object)
    not_number = values.isna() & ~blank
    finite = np.isfinite(values.fillna(0).to_numpy())
    msg[blank] = f"{label} is missing."
    msg[not_number] = f"{label} must be a number."
    msg[~blank & ~not_number & ~finite] = f"{label} must be a finite number."
    ok = msg == ""
    if name in INTEGER_FIELDS:
        frac = ok & (values.round() != values)
        msg[frac] = f"{label} must be a whole number."
        ok = msg == ""
    b = _bounds(name)
    if name == "cibil_score":
        bad = ok & ((values < b["ge"]) | (values > b["le"]))
        msg[bad] = "CIBIL score must be between 300 and 900."
    else:
        if "gt" in b:
            msg[ok & (values <= b["gt"])] = f"{label} must be greater than {b['gt']:g}."
        if "ge" in b:
            msg[ok & (values < b["ge"])] = f"{label} must be at least {b['ge']:g}."
        if "le" in b:
            msg[ok & (values > b["le"])] = f"{label} must be at most {b['le']:g}."
    return values, msg


def validate_rows(frame: pd.DataFrame) -> ParsedBatch:
    """Validate every row with the same limits as customer mode (vectorised).

    Invalid rows are reported (spreadsheet row number, ID if any, every problem in the row)
    and left out of ``values``.
    """
    n = len(frame)
    ids = (
        frame[ID_COLUMN].fillna("").astype(str).str.strip()
        if ID_COLUMN in frame.columns
        else pd.Series("", index=frame.index)
    )
    parsed: dict[str, pd.Series] = {}
    problems = pd.Series("", index=frame.index, dtype=object)
    for name in REQUIRED_COLUMNS:
        values, msg = _field_errors(name, frame[name])
        parsed[name] = values
        has = msg != ""
        problems[has] = np.where(problems[has] == "", msg[has], problems[has] + " " + msg[has])
    valid = (problems == "").to_numpy()
    rows = np.arange(n) + 2  # header is spreadsheet row 1
    errors = [
        RowError(row=int(rows[i]), applicant_id=str(ids.iloc[i]), message=str(problems.iloc[i]))
        for i in np.flatnonzero(~valid)
    ]
    values = pd.DataFrame({k: v[valid] for k, v in parsed.items()}).reset_index(drop=True)
    for name in INTEGER_FIELDS:
        values[name] = values[name].astype("int64")
    return ParsedBatch(
        values=values,
        source_rows=rows[valid],
        applicant_ids=ids[valid].reset_index(drop=True),
        errors=errors,
        total_rows=n,
    )


def parse_upload(data: bytes, policy: Policy | None = None) -> ParsedBatch:
    """Read, map and validate an uploaded file in one call."""
    policy = policy or load_policy()
    frame = read_csv_bytes(data, policy.batch.max_rows)
    mapped, renamed, ignored = map_columns(frame)
    parsed = validate_rows(mapped)
    parsed.renamed, parsed.ignored = renamed, ignored
    return parsed


# ---- Scoring -------------------------------------------------------------------------------

RESULT_COLUMNS: tuple[str, ...] = (
    "row",
    ID_COLUMN,
    "status",
    "probability",
    "likelihood",
    "borderline",
    "reasons",
    "what_would_change",
    "warnings",
    "reason_codes",
)


def score(
    parsed: ParsedBatch,
    policy: Policy | None = None,
    artifact: dict[str, Any] | None = None,
    include_positive: bool = False,
    progress: Callable[[float], None] | None = None,
) -> pd.DataFrame:
    """Score every valid row in chunks with the customer-mode decision core.

    Reasons and "what would change" are built for rejected rows only; positive factors
    only when ``include_positive`` is set.

    Returns:
        One row per valid applicant with :data:`RESULT_COLUMNS` (plus ``positive_factors``
        when requested). ``probability`` is the stored model probability; ``likelihood`` is
        its display text (never 0% or 100%).
    """
    policy = policy or load_policy()
    bands = policy.display.probability_bands
    chunk = policy.batch.chunk_size
    n = len(parsed.values)
    records: list[dict[str, Any]] = []
    for start in range(0, n, chunk):
        part = parsed.values.iloc[start : start + chunk]
        results = decide_many(
            part, policy, artifact, include_positive=include_positive, include_rule_results=False
        )
        for offset, res in enumerate(results):
            i = start + offset
            rec = {
                "row": int(parsed.source_rows[i]),
                ID_COLUMN: parsed.applicant_ids.iloc[i],
                "status": res.status,
                "probability": res.probability,
                "likelihood": f"{score_percent(res.probability)} - "
                f"{likelihood_band(res.probability, bands)}",
                "borderline": res.borderline,
                "reasons": "; ".join(r.message for r in res.reasons),
                "what_would_change": (
                    explain.change_summary(res.what_would_change)
                    if res.status == "Rejected"
                    else ""
                ),
                "warnings": "; ".join(res.warnings),
                "reason_codes": ";".join(r.code for r in res.reasons),
            }
            if include_positive:
                rec["positive_factors"] = "; ".join(r.message for r in res.positive_factors)
            records.append(rec)
        if progress is not None:
            progress(min(1.0, (start + len(part)) / n))
    columns = list(RESULT_COLUMNS) + (["positive_factors"] if include_positive else [])
    return pd.DataFrame(records, columns=columns)


# ---- Outputs -------------------------------------------------------------------------------


def summarise(results: pd.DataFrame, parsed: ParsedBatch, top_n: int = 5) -> dict[str, Any]:
    """Anonymised batch summary: counts, approval rate, likelihood bands, top reasons."""
    valid = len(results)
    approved = int((results["status"] == "Approved").sum()) if valid else 0
    codes = Counter(
        code
        for joined in results.loc[results["status"] == "Rejected", "reason_codes"]
        for code in joined.split(";")
        if code
    )
    bands = results["likelihood"].str.split(" - ").str[-1].value_counts().to_dict() if valid else {}
    return {
        "total_rows": parsed.total_rows,
        "valid_rows": valid,
        "invalid_rows": len(parsed.errors),
        "approved": approved,
        "rejected": valid - approved,
        "borderline": int(results["borderline"].sum()) if valid else 0,
        "approval_rate": approved / valid if valid else math.nan,
        "likelihood_bands": {k: int(v) for k, v in bands.items()},
        "top_rejection_reasons": [
            {"code": c, "reason": explain.REASON_LABELS.get(c, c), "count": int(k)}
            for c, k in codes.most_common(top_n)
        ],
    }


def errors_frame(errors: list[RowError]) -> pd.DataFrame:
    """Row-level problems as a table."""
    return pd.DataFrame(
        [{"row": e.row, ID_COLUMN: e.applicant_id, "problem": e.message} for e in errors],
        columns=["row", ID_COLUMN, "problem"],
    )


def filter_results(
    results: pd.DataFrame,
    statuses: list[str] | None = None,
    borderline: bool | None = None,
    search: str = "",
) -> pd.DataFrame:
    """Filter results by status, borderline flag and free-text search (ID or reasons)."""
    out = results
    if statuses:
        out = out[out["status"].isin(statuses)]
    if borderline is not None:
        out = out[out["borderline"] == borderline]
    if search.strip():
        term = search.strip().lower()
        hay = (
            out[ID_COLUMN].astype(str) + " " + out["reasons"] + " " + out["what_would_change"]
        ).str.lower()
        out = out[hay.str.contains(term, regex=False)]
    return out


def results_csv(results: pd.DataFrame) -> bytes:
    """Results as CSV bytes (UTF-8 with BOM so Excel shows rupee text correctly)."""
    return results.to_csv(index=False).encode("utf-8-sig")


def template_csv() -> bytes:
    """Downloadable template: correct headers and three hypothetical sample rows."""
    frame = pd.DataFrame(list(TEMPLATE_ROWS), columns=[ID_COLUMN, *REQUIRED_COLUMNS])
    return frame.to_csv(index=False).encode("utf-8")
