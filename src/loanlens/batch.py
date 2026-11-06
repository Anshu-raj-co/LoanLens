"""Bulk Check: CSV in, validated and scored results out (CLAUDE.md section 7).

Pipeline: :func:`read_csv_bytes` -> :func:`map_columns` -> :func:`validate_rows` ->
:func:`score` (chunked, using the same :func:`loanlens.decision.decide_many` core as
customer mode) -> :func:`summarise` / :func:`results_csv`.

Every problem with the file raises :class:`BatchError` with a plain-English message.
Problems with individual rows are collected as :class:`RowError` and those rows are
skipped; they never stop the rest of the batch.
"""

from __future__ import annotations

import codecs
import csv
import io
import math
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import annotated_types
import numpy as np
import pandas as pd

from loanlens import explain
from loanlens.cleaning import normalise_column_name
from loanlens.config import Policy, list_profiles, load_policy, load_profile
from loanlens.decision import INPUT_COLUMNS, decide_many
from loanlens.formatting import likelihood_band, score_percent
from loanlens.schema import FIELD_LABELS, ApplicantInput

ID_COLUMN = "applicant_id"
PRODUCT_COLUMN = "product"  # optional loan type per row; blank means the default profile
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
    # loan type
    "loan_type": PRODUCT_COLUMN,
    "product_type": PRODUCT_COLUMN,
    "loan_product": PRODUCT_COLUMN,
    "profile": PRODUCT_COLUMN,
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
    products: pd.Series | None = None  # loan type of each valid row (None: no product column)
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
    wanted = set(REQUIRED_COLUMNS) | {ID_COLUMN, PRODUCT_COLUMN}
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


def _product_errors(raw: pd.Series, default: str) -> tuple[pd.Series, pd.Series]:
    """Return (normalised loan type per row, error message per row or '')."""
    known = list_profiles()
    products = raw.fillna("").astype(str).str.strip().str.lower().replace("", default)
    msg = pd.Series("", index=raw.index, dtype=object)
    unknown = ~products.isin(known)
    msg[unknown] = [
        f"Product '{str(v).strip()}' is not a known loan type. Use one of: {', '.join(known)}."
        for v in raw[unknown]
    ]
    return products, msg


def validate_rows(
    frame: pd.DataFrame, default_product: str | None = None, first_row: int = 2
) -> ParsedBatch:
    """Validate every row with the same limits as customer mode (vectorised).

    Invalid rows are reported (spreadsheet row number, ID if any, every problem in the row)
    and left out of ``values``. An optional ``product`` column picks each row's loan type
    (blank means ``default_product``, normally ``personal``); an unknown value is a row error.
    ``first_row`` is the row number of the frame's first row (2 for a whole file, because the
    header is row 1; later chunks of a streamed file continue the numbering).
    """
    default_product = default_product or load_policy().profile
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
    products = None
    if PRODUCT_COLUMN in frame.columns:
        products, msg = _product_errors(frame[PRODUCT_COLUMN], default_product)
        has = msg != ""
        problems[has] = np.where(problems[has] == "", msg[has], problems[has] + " " + msg[has])
    valid = (problems == "").to_numpy()
    rows = np.arange(n) + first_row  # header is spreadsheet row 1
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
        products=None if products is None else products[valid].reset_index(drop=True),
        errors=errors,
        total_rows=n,
    )


def parse_upload(data: bytes, policy: Policy | None = None) -> ParsedBatch:
    """Read, map and validate an uploaded file in one call."""
    policy = policy or load_policy()
    frame = read_csv_bytes(data, policy.batch.max_rows)
    mapped, renamed, ignored = map_columns(frame)
    parsed = validate_rows(mapped, policy.profile)
    parsed.renamed, parsed.ignored = renamed, ignored
    return parsed


# ---- Streaming (large files, read in chunks) -----------------------------------------------

CSV_FORMAT, PARQUET_FORMAT = "csv", "parquet"
PARQUET_MAGIC = b"PAR1"
_SNIFF_BYTES = 1 << 16
_BLOCK_BYTES = 1 << 20


@dataclass
class Chunk:
    """One block of a streamed file: canonical text columns and its first row number."""

    frame: pd.DataFrame  # recognised columns only, canonical names, text values
    first_row: int  # spreadsheet row number of the frame's first row (header = row 1)


def detect_format(path: Path) -> str:
    """``parquet`` when the file starts with the Parquet magic bytes, else ``csv``."""
    with open(path, "rb") as fh:
        return PARQUET_FORMAT if fh.read(4) == PARQUET_MAGIC else CSV_FORMAT


def detect_encoding(path: Path) -> str:
    """``utf-8-sig`` if the whole file is valid UTF-8, else ``cp1252`` (read in blocks).

    Raises:
        BatchError: the file is empty or is not text.
    """
    with open(path, "rb") as fh:
        head = fh.read(_SNIFF_BYTES)
        if not head.strip():
            raise BatchError("The file is empty. Please upload a CSV with a header row and data.")
        if b"\x00" in head:
            raise BatchError("The file could not be read as text. Please upload a CSV file.")
        decoder = codecs.getincrementaldecoder("utf-8")()
        fh.seek(0)
        try:
            while block := fh.read(_BLOCK_BYTES):
                decoder.decode(block)
            decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            return "cp1252"
    return "utf-8-sig"


def estimate_rows(path: Path, fmt: str | None = None) -> int:
    """Number of data rows: exact for Parquet; for CSV the number of lines after the header.

    The CSV count is for progress and the row limit; blank lines are counted too.
    """
    fmt = fmt or detect_format(path)
    if fmt == PARQUET_FORMAT:
        return int(_parquet_file(path).metadata.num_rows)
    lines, last = 0, b""
    with open(path, "rb") as fh:
        while block := fh.read(_BLOCK_BYTES):
            lines += block.count(b"\n")
            last = block[-1:]
    if last and last != b"\n":
        lines += 1
    return max(0, lines - 1)


def _parquet_file(path: Path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    try:
        return pq.ParquetFile(path)
    except (pa.ArrowException, OSError) as exc:
        raise BatchError("The file could not be read as a Parquet file.") from exc


def _as_text(series: pd.Series) -> pd.Series:
    """A Parquet column as text, the way it would appear in a CSV (missing -> blank)."""
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return series.astype("string").fillna("").astype(object)
    return series.where(series.notna(), "").astype(str)


def _drop_blank_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    blank = (frame.apply(lambda c: c.astype(str).str.strip()) == "").all(axis=1)
    return frame.loc[~blank]


class ChunkReader:
    """Read a CSV or Parquet file in chunks of ``chunk_size`` rows, never all at once.

    The header is checked first (:func:`map_columns`), so a file with missing columns fails
    before any row is scored. ``renamed`` and ``ignored`` describe the header. Rows that are
    blank in every column are skipped and not numbered, exactly as for a small upload.

    Raises (while iterating):
        BatchError: unreadable file, missing columns, or a malformed line.
    """

    def __init__(self, path: Path, chunk_size: int, fmt: str | None = None) -> None:
        self.path = Path(path)
        self.chunk_size = int(chunk_size)
        self.format = fmt or detect_format(self.path)
        self.renamed: dict[str, str] = {}
        self.ignored: list[str] = []
        self._mapping: dict[str, str] = {}
        if self.format == PARQUET_FORMAT:
            self._parquet = _parquet_file(self.path)
            self._set_header(list(self._parquet.schema_arrow.names))
        else:
            self._encoding = detect_encoding(self.path)
            self._sep = detect_delimiter(self._header_line())
            try:
                header = pd.read_csv(
                    self.path, sep=self._sep, nrows=0, encoding=self._encoding,
                    skipinitialspace=True, dtype=str,
                )  # fmt: skip
            except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError,
                    ValueError) as exc:  # fmt: skip
                raise BatchError(
                    "The file could not be read as a CSV table. Check that every row has the "
                    "same number of columns, separated by commas."
                ) from exc
            self._set_header(list(header.columns))

    def _header_line(self) -> str:
        with open(self.path, encoding=self._encoding, errors="replace") as fh:
            for line in fh:
                if line.strip():
                    return line
        raise BatchError("The file is empty. Please upload a CSV with a header row and data.")

    def _set_header(self, columns: list[str]) -> None:
        mapped, self.renamed, self.ignored = map_columns(pd.DataFrame(columns=columns))
        self._mapping = {orig: canon for orig, canon in zip(
            [c for c in columns if canonical_name(c) in set(mapped.columns)],
            mapped.columns, strict=True,
        )}  # fmt: skip

    def _raw_chunks(self) -> Iterator[pd.DataFrame]:
        if self.format == PARQUET_FORMAT:
            import pyarrow as pa

            try:
                for rb in self._parquet.iter_batches(
                    batch_size=self.chunk_size, columns=list(self._mapping)
                ):
                    yield rb.to_pandas().apply(_as_text)
            except pa.ArrowException as exc:
                raise BatchError("The file could not be read as a Parquet file.") from exc
            return
        reader = pd.read_csv(
            self.path, sep=self._sep, dtype=str, keep_default_na=False, skip_blank_lines=True,
            skipinitialspace=True, quoting=csv.QUOTE_MINIMAL, encoding=self._encoding,
            chunksize=self.chunk_size,
        )  # fmt: skip
        try:
            with reader:
                for part in reader:  # all columns are read so malformed lines are caught
                    yield part[list(self._mapping)]
        except (pd.errors.ParserError, csv.Error, UnicodeDecodeError, ValueError) as exc:
            raise BatchError(
                "Part of the file could not be read as a CSV table. Check that every row has "
                "the same number of columns, separated by commas."
            ) from exc

    def __iter__(self) -> Iterator[Chunk]:
        next_row = 2  # header is row 1
        for raw in self._raw_chunks():
            frame = _drop_blank_rows(raw.rename(columns=self._mapping))
            if frame.empty:
                continue
            yield Chunk(frame=frame.reset_index(drop=True), first_row=next_row)
            next_row += len(frame)


# ---- Scoring -------------------------------------------------------------------------------

RESULT_COLUMNS: tuple[str, ...] = (
    "row",
    ID_COLUMN,
    PRODUCT_COLUMN,
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
    only when ``include_positive`` is set. Each row is decided under its own loan type's
    profile (``parsed.products``); rows without one use ``policy``.

    Returns:
        One row per valid applicant with :data:`RESULT_COLUMNS` (plus ``positive_factors``
        when requested). ``probability`` is the stored model probability; ``likelihood`` is
        its display text (never 0% or 100%).
    """
    policy = policy or load_policy()
    bands = policy.display.probability_bands
    chunk = policy.batch.chunk_size
    n = len(parsed.values)
    products = (
        parsed.products
        if parsed.products is not None
        else pd.Series(policy.profile, index=parsed.values.index)
    )
    records: list[dict[str, Any]] = []
    for start in range(0, n, chunk):
        part = parsed.values.iloc[start : start + chunk]
        part_products = products.iloc[start : start + chunk].to_numpy()
        results: list[Any] = [None] * len(part)
        for name in dict.fromkeys(part_products):  # each loan type in order of appearance
            idx = np.flatnonzero(part_products == name)
            profile_policy = policy if name == policy.profile else load_profile(name)
            decided = decide_many(
                part.iloc[idx],
                profile_policy,
                artifact,
                include_positive=include_positive,
                include_rule_results=False,
            )
            for k, res in zip(idx, decided, strict=True):
                results[k] = res
        for offset, res in enumerate(results):
            i = start + offset
            rec = {
                "row": int(parsed.source_rows[i]),
                ID_COLUMN: parsed.applicant_ids.iloc[i],
                PRODUCT_COLUMN: res.profile,
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
