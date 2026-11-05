# Progress

## Phase 0: Setup (done)

**What was done**
- Created the folder structure from CLAUDE.md section 8, using `.gitkeep` files for empty folders.
- Renamed `Data/Raw/` to `data/raw/`. The CSV contents were not touched.
- Created `requirements.txt` (pinned, Python 3.11), `.gitignore` (`.venv`, `__pycache__`, `models/`, `data/raw/`, SQLite files), a minimal `README.md`, and `pyproject.toml` (editable install plus ruff and pytest settings).
- Created `config/policy.yaml`. Every threshold is marked "PLACEHOLDER - illustrative value; a lender would replace it with its own credit policy".
- Created `.venv` (Python 3.11.9), installed the requirements (`pip check` reports no broken requirements), installed the project with `pip install -e .`, and initialised git.

**Test results**
- `ruff check`: all checks passed. `pytest`: no tests yet in this phase.

**Open issues**
- All policy thresholds are placeholders, illustrative until replaced by a lender's real credit policy.

## Phase 1: Data audit and cleaning (done)

**What was done**
- `notebooks/01_audit.ipynb` audits the primary dataset: shape, dtypes, whitespace, nulls, duplicates, value ranges, outliers, and the negative assets. It compares the three treatments for negative assets.
- `src/loanlens/cleaning.py` has these functions: `normalise_column_name`, `normalise_columns`, `strip_string_values`, `map_target`, `count_negative_assets`, `handle_negative_assets` (`clip_zero` / `drop` / `nan`), `drop_identifier`, `drop_duplicate_rows`, `load_negative_strategy`, `clean`, and `build_clean_dataset`. The strategy is read from `config/policy.yaml` under `cleaning.negative_assets_strategy`.
- Output: `data/processed/loan_approval_clean.csv`, 4,269 rows x 12 columns (`loan_id` dropped), with no missing values.
- `tests/test_cleaning.py` tests every cleaning function plus an end-to-end run on the real file.

**Data-quality summary** (numbers produced by the notebook)

| Issue | Count | Action taken |
|---|---|---|
| Column names with leading/trailing whitespace | 12 of 13 | Stripped and normalised to snake_case |
| Text cells with leading/trailing whitespace | 12,807 (every cell in education, self_employed, loan_status) | Stripped |
| Missing values | 0 | None needed |
| Exact duplicate rows | 0 | None found; pipeline still drops exact duplicates |
| Duplicate rows ignoring `loan_id` | 0 | None needed |
| Negative `residential_assets_value` (all exactly -100,000; 16 approved, 12 rejected) | 28 | Set to 0 (`clip_zero`, configurable) |
| CIBIL outside 300-900 | 0 | None needed |
| IQR outliers (residential 52, commercial 37, bank 5) | 94 | Kept: plausible high values, not errors |
| Target stored as text | 4,269 | Mapped Approved=1 / Rejected=0 |
| `loan_id` identifier | 1 column | Dropped |

**Test results**
- `ruff check .`: all checks passed (including notebooks).
- `pytest tests/test_cleaning.py`: 24 passed.

**Open issues**
- None for cleaning. The CSV-upload column mapping (Bulk Check) will reuse `normalise_column_name` in a later phase.
