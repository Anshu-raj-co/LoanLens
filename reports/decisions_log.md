# Decisions Log

Each entry records what was found, what was chosen, and why.

## Phase 0: Setup

### D-001 Data folder casing
- **Found:** the data was in `Data/Raw/`, but CLAUDE.md specifies `data/raw/`.
- **Chose:** renamed it to `data/raw/` (lowercase). The file contents were not touched.
- **Why:** Git and Linux are case-sensitive, and every path in code and docs uses lowercase.

### D-002 Python version and package pins
- **Found:** both Python 3.13 and 3.11 are installed.
- **Chose:** a `.venv` on Python 3.11 (per CLAUDE.md), with numpy pinned to 2.0.2.
- **Why:** SHAP 0.46 depends on numba, which supports numpy only up to 2.0.x.

### D-003 Packaging
- **Chose:** a minimal `pyproject.toml`, installed with `pip install -e .`, so that `loanlens` imports cleanly from notebooks, tests and (later) the app. The same file holds the ruff and pytest settings.
- **Why:** this avoids `sys.path` hacks in every notebook and test.

### D-004 Placeholder policy thresholds
- **Chose:** `min_cibil` 550, `max_emi_to_income` 0.50, `max_loan_to_income` 4.0, `max_loan_to_assets` 1.5, loan term 2 to 20 years, interest rate 10%, approval threshold 0.5, borderline band 0.4 to 0.6. Every value is marked as a placeholder.
- **Why:** CLAUDE.md's example reason uses a minimum CIBIL of 650, but the data shows the approval boundary at about 550. 550 is the data-consistent placeholder. The loan-term range and the 4.0 loan-to-income cap match the observed data ranges.
- **Open issue (for the rules phase):** see D-012. The 0.50 EMI-to-income cap conflicts with the synthetic data.

### D-005 .gitignore covers raw data
- **Chose:** everything in `data/raw/` is gitignored. Processed data in `data/processed/` is committed, because it is small (about 4.3k rows) and derived from public synthetic data.
- **Why:** CLAUDE.md says raw files must never be committed if large, and bank data must never be committed. Ignoring the whole raw folder is the safest choice.

## Phase 1: Audit and cleaning

### D-006 Negative residential_assets_value
- **Found:** 28 rows. **All 28 have exactly -100,000** (16 approved, 12 rejected). No other asset column has negatives.
- **Chose:** `clip_zero` (set to 0), configurable in `config/policy.yaml` under `cleaning.negative_assets_strategy` (`clip_zero` | `drop` | `nan`).
- **Why:** assets cannot be negative, and the identical value points to a sentinel or entry error, not a real amount. Clipping to 0 keeps all 28 rows, which is under 1% of the data and has a mixed target. Zero is the most conservative reading, since we credit no residential assets. Dropping would also be defensible. It is kept as an option.

### D-007 Duplicates
- **Found:** 0 exact duplicate rows, and 0 duplicates even after removing `loan_id`.
- **Chose:** the cleaning pipeline still drops exact duplicates, as a safety net for future data.

### D-008 Column name normalisation
- **Chose:** strip, lower-case, drop bracketed units (`loan_term (years)` becomes `loan_term`), and replace non-alphanumeric runs with `_`. Collisions raise an error.
- **Why:** this matches the CLAUDE.md column list. The raw header is actually `loan_term`, with no "(years)", but the function handles both forms. The same rule will be reused for uploaded CSVs.

