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

## Phase 2: EDA (done)

**What was done**
- `notebooks/02_eda.ipynb` charts approval rate (Plotly) by CIBIL band, CIBIL x loan term, loan term, loan-to-income, income, loan amount, each asset type and total assets, education, self-employment and dependents. It adds chi-square tests and correlations.
- Every CLAUDE.md section 3 claim is checked against printed numbers, with a summary table in notebook section 9.8. The table is in `decisions_log.md` D-009.
- A plain-language "Findings and data limitations" cell.
- `src/loanlens/charts.py`: 5 reusable chart functions (`approval_rate_bar`, `approval_by_cibil_band`, `approval_by_quantile_band`, `distribution_by_status`, `approval_heatmap`) plus helpers `cibil_band` and `approval_rate_table`. Tests are in `tests/test_charts.py`.

**Test results**
- `ruff check .`: all checks passed (including both notebooks).
- `pytest`: 33 passed (24 cleaning, 9 charts).

**Open issues**
- Random forest accuracy is 98.2% on raw features, not the 99.9% in CLAUDE.md. It reaches 99.6% with loan-to-income (D-010).
- In the low-CIBIL, short-term group, approval rises with loan-to-income, a synthetic artefact (D-011). The later "what would change" logic must guard against it.
- The EMI-to-income cap of 0.50 would flag 44% of rows, and those rows are approved more often, not less (D-012). Needs a decision before `rules.py`.

## Phase 3: Features and rules (done)

**What was done**
- `CLAUDE.md` section 3 is updated with the corrected random-forest figure and the loan-to-income quirk.
- `config/policy.yaml` gives each rule a `value` and an `enforce` flag (all PLACEHOLDER). `src/loanlens/config.py` loads and validates it.
- `src/loanlens/features.py`: `emi` (reducing balance, rate from config), `emi_to_income`, `loan_to_income`, `total_assets`, `loan_to_assets`, `cibil_band`, `add_features`. Zero income, zero assets and a zero term are handled without errors.
- `src/loanlens/rules.py`: one `check_*` function per rule, each returning a `RuleResult` (rule, passed, actual, threshold, enforce, message). Also `evaluate_rules`, `enforced_failures` / `advisory_failures`, the vectorised `rule_pass_frame`, and `summarise_against_labels`.
- `reports/rules_vs_labels.md` (from `python -m loanlens.rules`): `min_cibil` fails 7.0% of approved applicants (enforced); EMI-to-income fails 47.4% (advisory); loan-to-income, loan-to-assets and the term limits fail 0% (enforced). It also has an EMI-cap sensitivity table.
- `src/loanlens/formatting.py`: Indian digit grouping.

**Test results**
- `ruff check .`: all checks passed.
- `pytest`: 92 passed (new: test_features, test_rules, test_config, covering zero income, zero assets, zero term, extreme amounts and values exactly at each threshold).

**Open issues**
- All thresholds and enforce flags are placeholders. The EMI-to-income rule is advisory until a lender supplies its real interest rate and FOIR policy.

## Phase 4: Modelling (done)

**What was done**
- `src/loanlens/model.py`: Pipelines (ColumnTransformer + scaler/one-hot fitted inside each fold), logistic regression / random forest / XGBoost, stratified 5-fold `cross_validate` with out-of-fold confusion matrices, calibration, a loan-size monotonicity probe, `train_final`, and save/load of an artifact with features, version, ranges and benchmarks. CLI: `python -m loanlens.model`.
- `notebooks/03_modelling.ipynb`: model comparison on three feature sets, ablations (CIBIL only, without CIBIL, without term, without loan-to-income), a shuffled-label check, monotone-constraint experiments with the quirk probe, calibration comparison and curve, the selection rule, and final training.
- Final model: constrained XGBoost (CIBIL +, loan-to-income -), isotonic calibration, COMPACT features. CV ROC-AUC 0.9942, PR-AUC 0.9946, F1 0.9639.
- `reports/model_card.md`.

**Test results**
- `ruff check .`: all checks passed.
- `pytest`: 106 passed (new `test_model.py`, including protected-attribute blocking, determinism, a save/load round trip, and checks that a bigger loan never raises and a higher CIBIL never lowers approval in the saved model).

**Open issues**
- The constrained model disagrees with the quirky historical labels by design (D-021).
- Isotonic calibration makes borderline cases rare (D-022).
