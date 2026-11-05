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

## Phase 5: Explainability and decision engine (done)

**What was done**
- `src/loanlens/schema.py`: `ApplicantInput` (Pydantic, ranges, finite numbers only, unknown fields ignored), friendly `ValidationFailure` messages, and the output models `Reason`, `Change`, `DecisionResult`.
- `src/loanlens/explain.py`: TreeSHAP drivers turned into bank-officer wording, each with code, message, your_value, benchmark and suggestion; rule reasons; merge, rank and cap at 5; positive factors; the "what would change" search (raise CIBIL or lower the loan only, worded "would likely").
- `src/loanlens/decision.py`: `decide()` validates, runs the rules (enforced vs advisory), runs the model, sets the borderline flag, then builds reasons, positive factors, changes and warnings (advisory rules, out-of-training-range inputs, borderline).
- `scripts/example_decisions.py` writes `reports/example_decisions.md`: 2 approved, 2 rejected (CIBIL rule; loan-to-income and loan-to-assets rules), 1 borderline.

**Test results**
- `ruff check .`: all checks passed.
- `pytest`: 146 passed. New `test_schema.py` and `test_decision.py` check that every rejection has a non-empty reason, approvals carry no rejection reasons, invalid input gets an error and no decision, results are deterministic, enforced rules override the model, suggestions only raise CIBIL or lower the loan and actually flip the result, and a decision takes under 2 seconds.
- Full-data run: 4,269 decisions at about 16 ms each, 0 rejections without a reason.

**Open issues**
- Single-row `decide()` is about 16 ms, so batch scoring should be vectorised in the batch phase (see Suggestions).
- All thresholds remain placeholders.

## Phase 6: Customer mode (done)

**What was done**
- Review changes:
  - Model presence checked.
  - Probability display never shows 0% or 100% and adds verbal likelihood bands (cut-offs in `policy.yaml`).
  - CIBIL-margin borderline rule (+/-25 points, in `policy.yaml`).
  - `decide_many()` vectorised core shared by `decide()`.
  - Example report regenerated with likelihood bands, plus a sixth CIBIL-margin example (`src/loanlens/examples.py`).
- `src/loanlens/presentation.py`: form specs, notices, `DecisionView`, policy table.
- `app/Home.py`: purpose, disclaimer, illustrative-thresholds note, navigation, how a result is decided.
- `app/pages/1_Check_My_Eligibility.py`: 8-field form with ranges, help and Indian-grouped amount echoes. The result shows a status badge, likelihood with band and "indicative only" label, borderline note, reason cards, what would change, positive factors, warnings, policy checks, and "Prototype - not a lending decision". Nothing is stored.
- `app/ui_common.py` (shared header, sidebar and footer; friendly model and policy errors) and `.streamlit/config.toml` (stack traces hidden).

**Test results**
- `ruff check .`: all checks passed.
- `pytest`: 183 passed. New `test_customer_mode.py` runs all 6 examples through `decide()` + `present()` and drives the real page with Streamlit AppTest (render, submit examples, validation errors). There are also new borderline-margin, likelihood-band and `decide_many` equivalence tests.
- `streamlit run app/Home.py` starts and the health check returns ok; Home and the eligibility page render with no exceptions under AppTest.

**Open issues**
- None.

## Phase 7: Bank manager batch mode (done)

**What was done**
- `src/loanlens/batch.py`: CSV reading (delimiter detection, BOM and encoding handling, size limit), header normalisation with aliases and exact missing-column errors, vectorised row validation with row-numbered reasons, chunked scoring through the shared `decide_many()` core, summary, filters and search, results CSV, and a 3-row template.
- `src/loanlens/storage.py`: SQLite storage of anonymised batch summaries. Per-row IDs only if enabled in config.
- `app/pages/2_Bulk_Check.py`: manager-mode toggle, template download, upload (up to 50,000 rows), skipped-row report, progress bar, summary metrics and top rejection reasons, results table with status, borderline and search filters, CSV download, and anonymised summary saving.
- `tests/fixtures/batch_1000.csv`: 1,000 rows, 20 deliberately bad.

**Test results**
- `ruff check .`: all checks passed.
- `pytest`: 223 passed. New `test_batch.py` covers good CSV, bad rows, missing columns, empty and BOM-only files, header-only file, other delimiters, header aliases and duplicates, too many rows, 1,000 rows in 10 s or less, 10,000 rows in 90 s or less, batch vs single consistency on 600 rows, storage anonymity, and the page (gate, fixture upload, missing columns, empty file).
- Measured speed: 1,000 rows 0.7 s, 10,000 rows 6.2 s, 50,000 rows 32 s.
- `streamlit run app/Home.py`: server healthy, pages return 200, no errors in the server log.

**Open issues**
- None.

## Phase 8: Analytics and About pages (done)

**What was done**
- `app/pages/3_Analytics.py`, in three tabs:
  - Approval patterns: CIBIL band, loan term, loan size, with plain-language captions about the synthetic quirks.
  - What drives the model: mean |SHAP| feature importance.
  - Latest batch: metrics, top rejection reasons, likelihood bands and a recent-batches table, all from SQLite.
  - Data and importance are cached.
- `app/pages/4_About.py`: approval-not-default framing, data source, model metadata and CV metrics, illustrative-thresholds notice, current policy table with enforce settings, the rendered model card, and future work.
- `charts.py`: `feature_importance_bar`, `counts_bar`. `explain.py`: `feature_importance`.
- The model card is updated with the borderline and likelihood-band display rules.

**Test results**
- `ruff check .`: all checks passed.
- `pytest`: 238 passed. New `test_pages.py`: every page renders with title and footer; the placeholder notice appears on the customer, bulk and About pages; the model-missing message is friendly; Analytics works with and without stored batches; feature importance; About content and policy table.
- `streamlit run app/Home.py`: health ok, all five page URLs return 200, no errors in the server log.

**Open issues**
- None.

## UI restyle: white fintech theme (done)

**What was done**
- `src/loanlens/theme.py`: the single home for every colour (palette plus darker text shades for contrast), the status-to-colour mapping, the shared CSS, the Plotly template, and small HTML helpers (header strip, pill, policy-check list, status table styling).
- `.streamlit/config.toml`: light base theme with the palette; stack traces stay hidden.
- Every page gets the CSS and a branded header strip via `app/ui_common.py`.
- Customer result: a large green/red banner with ✅/❌ status, amber borderline pill, and the likelihood inside it. Reason cards red, positive cards green, "what would change" blue, warnings amber, and policy checks with ✓/✗.
- Bulk Check: coloured metric cards, a ✅/❌ status column coloured green/red (up to 5,000 visible rows), and an amber skipped-rows panel. The CSV download is unchanged.
- Charts and notebooks share the Plotly template (Approved green, Rejected red, neutral blue, white background). Notebooks 02 and 03 were re-executed.
- `reports/example_decisions.md` uses ✅/❌/⚠️.
- Screenshots of every page are in `reports/screenshots/`.

**Test results**
- `ruff check .`: all checks passed.
- `pytest`: 251 passed (new `tests/test_theme.py`: palette, status colours, config sync, WCAG contrast, table styling, chart colours, every page renders with the theme). No earlier test was changed.
- `streamlit run app/Home.py`: all five pages return 200 and the server log has no errors.

**Open issues**
- None.

## Phase 9: Benchmark on the larger dataset (done)

**What was done**
- `notebooks/04_benchmark_bank_loan_data.ipynb`: profile (columns, types, class balance, currency, missing values, ranges, synthetic signs, label caution), cleaning, EDA charts in the LoanLens theme, logistic regression / random forest / XGBoost with stratified 5-fold CV and class weights, confusion matrices, ablations, and SHAP. Gender and age are excluded.
- `reports/benchmark.md`: side-by-side comparison of the two datasets (features that matter, performance, currency and score scales, extra fields a real system should collect).
- About page: a short "Benchmark" section (`presentation.BENCHMARK_SUMMARY`).
- Not merged with the primary data; the production model file is byte-identical before and after.

**Test results**
- `ruff check .`: all checks passed.
- `pytest`: 256 passed (new `tests/test_benchmark.py`: the notebook never touches the production model, excludes sensitive features and ran without errors; the report covers the required points; the About page shows the summary).

**Open issues**
- The benchmark label's direction for interest rate and loan-to-income looks like a default label (D-054).
