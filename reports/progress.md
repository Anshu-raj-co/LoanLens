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
- Customer result: a large green/red banner with [tick]/[cross] status, amber borderline pill, and the likelihood inside it. Reason cards red, positive cards green, "what would change" blue, warnings amber, and policy checks with [tick mark]/[cross mark].
- Bulk Check: coloured metric cards, a [tick]/[cross] status column coloured green/red (up to 5,000 visible rows), and an amber skipped-rows panel. The CSV download is unchanged.
- Charts and notebooks share the Plotly template (Approved green, Rejected red, neutral blue, white background). Notebooks 02 and 03 were re-executed.
- `reports/example_decisions.md` uses [tick]/[cross]/[warning sign].
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

## Phase 10: Hardening and handover (done)

**What was done**
- Review decision 1: mean absolute SHAP share is the single feature-importance measure on the Analytics page, About page and model card (new "Feature importance" table; the old "74% of gain" headline explained and retired).
- Review decision 2: a plain-language "How the borderline flag works" section on the About page (built from `policy.yaml` values) and in USER_GUIDE.md, including why a near-minimum CIBIL is not flagged when another enforced rule failed.
- Review decision 3: Bulk Check now needs a password from `LOANLENS_MANAGER_PASSWORD` or the Streamlit secret `manager_password`, with the documented local-demo default `loanlens-demo` (`src/loanlens/access.py`). `.streamlit/secrets.toml` is gitignored. No other secret exists in the repository.
- Review decisions 4 and 5: `requirements.txt` installs the package (`-e .`); `python -m loanlens.model` builds the cleaned data and the model; the app shows a friendly message if the model is missing. The Kaggle CSVs and the processed copy are gitignored; README lists sources and links.
- Hardening walk-through of every page with invalid, empty, zero, huge, borderline, 50,000-row and 51,000-row inputs: no exception or stack trace reaches the user.
- README.md rewritten (purpose, framing, fresh-clone setup, data sources, pages with screenshots, decision logic, manager gate, structure, limitations, future work). New USER_GUIDE.md (customers and bank managers, CSV template and columns, borderline explanation).
- `reports/decisions_log.md` now opens with a list, for a lender's credit-policy team to review, of every placeholder and assumption.
- Screenshots retaken after the Phase 10 UI changes.

**Test results**
- `ruff check .`: all checks passed.
- `pytest`: 281 passed; coverage of `src/loanlens` 98% (`pytest --cov=loanlens`).
- `streamlit run app/Home.py`: all five pages return 200, no errors in the server log.
- Fresh clone: verified, see below.

**Open issues**
- All policy thresholds, enforce flags and the assumed 10% interest rate are illustrative until replaced by a lender's real credit policy.
- Dataset licences not verified; the source page of `loan_data.csv` was not recorded (D-060).

### Fresh-clone verification (Phase 10)
- `git clone` into an empty, gitignored folder inside the project (`.fresh_clone_test/`, deleted afterwards), then `py -3.11 -m venv .venv` and `pip install -r requirements.txt`: 5.5 minutes, no errors. `loanlens` was importable from the clone's `src/` with no extra step.
- **Before any data:** `python -m loanlens.model` stopped with "Missing ...loan_approval_dataset.csv. Download ... into data/raw/". The eligibility and Analytics pages showed the friendly "model has not been trained yet ... run `python -m loanlens.model`" message, with no exception. `pytest`: 184 passed, 97 skipped (data and model needed), 0 failed, after five tests were fixed to request the model fixture (they had failed instead of skipping).
- **After copying the three CSVs into `data/raw/`:** `python -m loanlens.model` built the cleaned data and the model in 7 seconds, with the same CV metrics as the model card (ROC-AUC 0.9942, F1 0.9639). `streamlit run app/Home.py`: health ok, all five pages returned 200, every page was driven in headless Edge (including a 1,000-row upload with the demo password), and the server log had no errors. `pytest`: 281 passed.

## Reframe and publication (done)

**What was done**
- Reframed as an independent proof of concept: 56 replacements across 16 files; no mention of the former affiliation or reviewer remains in files or history (D-062).
- Dataset credits re-checked against Kaggle metadata; `bank_loan_data.csv` now cited as https://www.kaggle.com/datasets/udaymalviya/bank-loan-data; `loan_data.csv` marked "source not verified" (D-063).
- `tests/fixtures/batch_1000.csv` replaced by a fully synthetic file from `scripts/make_batch_fixture.py` (D-064).
- Screenshots retaken with Playwright (Chromium inside the venv; `requirements-dev.txt`), including a new `08_eligibility_rejected.png` (D-065).
- README improved (header, results at a glance, gallery, documentation, lender requirements, security notes); new `PROJECT_EXPLAINED.md`.

**Test results**
- `ruff check .`: all checks passed. `pytest`: 281 passed; coverage of `src/loanlens` 98%.

### Fresh-clone verification (final)
- `git clone` of the local repository (commit `e68fcc4`) into a temporary folder **outside** the project, `py -3.11 -m venv .venv`, `pip install -r requirements.txt`: no errors.
- Copied the three CSVs into `data/raw/`; `python -m loanlens.model` built the cleaned data and the model in 14 seconds with the model-card metrics (ROC-AUC 0.9942, PR-AUC 0.9946, F1 0.9639).
- `pytest`: 281 passed. `ruff check .`: all checks passed.
- `streamlit run app/Home.py` from the clone: every page (Home, Check My Eligibility with approved / rejected / borderline examples, Bulk Check with the 1,000-row synthetic upload, Analytics, About) was driven in headless Chromium; the server log had no errors.
- The temporary clone and its virtual environment were deleted afterwards; `git status` in the project showed only the intended changes.

### History rewrite and audit
- Backup bundle created; history rewritten with `git filter-repo` (terms scrubbed, author and committer set to the GitHub no-reply identity, historical dataset copies and old screenshots stripped). 0 matches remain in `git log --all -p`. ruff passes, 281 tests pass. See D-066 and D-067.

## Visual cleanup (done)
- Emoji removed from the app, the UI modules, the example-decisions script and report, README, USER_GUIDE and PROJECT_EXPLAINED (102 emoji characters). Status is shown by colour plus the words Approved / Rejected / Borderline - manual review recommended; policy checks show Passed / Failed / Advisory.
- The yellow disclaimer box is gone from Home (the text remains in every footer, on About and in README). The header strip shows only "LoanLens" at 2.4rem bold.
- New `tests/test_no_emoji.py` scans source files and rendered pages. All screenshots retaken. Example decisions are identical to before (decisions_log D-068, D-069).

## Milestone 1: database layer, policy profiles, model registry (done)
- **Database:** SQLAlchemy 2 + Alembic (`src/loanlens/db/`, revision `0001_initial`). `DATABASE_URL`, default `sqlite:///data/loanlens.sqlite`; PostgreSQL via psycopg. `storage.py` rebuilt on it with identical behaviour; database failures give a plain message. The existing local database was adopted without data loss (checked on a copy).
- **Policy profiles:** `config/policies/` with personal (the original values, unchanged), home and vehicle. Each has a semantic version and a content hash; results record profile, policy version, policy hash and model version. Adds the loan-type selector, the optional `product` CSV column and all profiles on About.
- **Model registry:** `models/registry.json`, versioned artifacts, `--list` / `--activate`, `LOANLENS_MODEL_VERSION`, SHA-256 check on load. The existing artifact was registered as 1.0.0 with identical bytes.
- **Checks on 2026-11-06 (this Windows machine):**
  - 376 tests passed and 3 PostgreSQL tests skipped (no database available; Docker's engine was not running). Coverage of `src/loanlens` is 98%, and ruff is clean.
  - The six example decisions are byte-identical to before, and `reports/example_decisions.md` regenerated unchanged.
  - The app ran with all five pages and a 1,000-row upload, with no server-log errors (screenshot run).
- **Not repeated:** the fresh-clone verification.
- Decisions: D-070 to D-073.

## Milestone 2: authentication and roles (done)
- **Accounts:** `src/loanlens/auth/` holds the service layer, argon2id passwords, HS256 JWT sessions, settings and a CLI. Alembic `0002_auth` adds the `users` and `auth_events` tables.
- **Roles:** applicant (self sign-up) and manager (CLI, one-time bootstrap or another manager). Roles are enforced in the service layer and in the pages.
- **Rules:**
  - password policy of 10 to 128 characters, not common, not the email;
  - one generic sign-in error;
  - 5 failures lock the account for 15 minutes;
  - 60-minute sessions, re-validated on every page load;
  - production or hosted mode refuses to start without `LOANLENS_JWT_SECRET`.
- **Pages:** Sign in (Sign in and Create account tabs), Account (change password, delete account) and Users (list, create manager, deactivate or reactivate, temporary password). Forced password change. Check My Eligibility needs a signed-in user; Bulk Check and Analytics need a manager.
- **Removed:** the old shared-password gate (`access.py`, `LOANLENS_MANAGER_PASSWORD`, the demo password).
- **Checks on 2026-11-06 (this Windows machine):**
  - 499 tests passed and 3 PostgreSQL tests skipped (no database available). Coverage of `src/loanlens` is 99%, and ruff is clean.
  - A test confirms that no plaintext password or token appears in the database file, the `auth_events` rows or the logs.
  - The six example decisions are byte-identical to the baseline, and `reports/example_decisions.md` regenerated unchanged.
  - The live screenshot run had no server-log errors and no passwords in the log. It covered sign-up, the three examples, an applicant blocked from Bulk Check, the bootstrapped manager's forced password change, the 1,000-row upload, Analytics, Users and About.
- **Not repeated:** the fresh-clone verification.
- Decisions: D-074 to D-083.

## Milestone 3: audit trail and REST API (done)
- **Audit trail:** `decision_audit` (Alembic `0003_audit`) records every decision from the UI, the API and Bulk Check (chunked inserts). It is append-only: there are no update or delete code paths, and triggers reject UPDATE and DELETE on SQLite and PostgreSQL. A decision is shown only after its record is written. New pages: My History (own records, CSV) and Audit (managers; filters, counts, CSV).
- **Service layer:** `src/loanlens/services.py`. Every scoring, batch, analytics, batch-summary and audit function verifies a sealed principal and its role itself. Pages and the API call only these functions.
- **Sessions:** a token version on `users`. A password change, a temporary password and deactivation or reactivation invalidate older tokens; the changing session gets a fresh token.
- **REST API:** FastAPI under `/v1`, with health and ready endpoints and OpenAPI docs at `/docs`.
  - request ids stored in the audit trail, JSON logs without personal data, one error format;
  - CORS off by default;
  - in-memory rate limits per client address and per account on sign-in and registration.
- **Checks on 2026-11-06 (this Windows machine):**
  - 655 tests passed and 8 skipped (7 PostgreSQL tests, because `LOANLENS_TEST_POSTGRES_URL` is not set, and one PostgreSQL-only TRUNCATE check on SQLite). Coverage of `src/loanlens` is 99%, and ruff is clean.
  - **No PostgreSQL test ran**, so PostgreSQL support, including the PostgreSQL triggers, is not verified.
  - The six example decisions are byte-identical to the baseline, and `reports/example_decisions.md` regenerated unchanged.
  - The API was served live with uvicorn and exercised with curl (register, login, score, audit, roles); its log had no personal data.
  - The screenshot run (all pages, including My History and Audit) had no server-log errors and no passwords in the log.
- **Not repeated:** the fresh-clone verification.
- Decisions: D-084 to D-090.

## Milestone 3 fix: migrations no longer reset logging; PostgreSQL tests verified (2026-11-06)
- **Problem:** with `LOANLENS_TEST_POSTGRES_URL` set, `pytest tests/test_db.py tests/test_audit.py tests/test_auth.py` failed 3 auth tests (empty `caplog`, "Logging error: ValueError: I/O operation on closed file"). Cause: the Alembic command-line test loads alembic.ini's logging section inside the test process, which disabled every existing logger and bound a handler to a closed stream (D-091).
- **Fix:** `ensure_schema()` marks its Alembic config with `skip_logging_config`; `env.py` applies alembic.ini's logging only for the `alembic` command, with `disable_existing_loggers=False`. The CLI test restores logging afterwards. `alembic upgrade head` from the project root works as before.
- **New tests:** loggers and root handlers unchanged after `ensure_schema` (SQLite and PostgreSQL); `caplog` still captures warnings after migrations (SQLite and PostgreSQL); the three auth tests pass with the CLI test before and after them.
- **Checks on 2026-11-06 (this Windows machine, PostgreSQL 16.15 in a disposable database on port 5433):**
  - With `LOANLENS_TEST_POSTGRES_URL` set: 668 passed, 1 skipped (the SQLite case of the TRUNCATE check). All 9 PostgreSQL tests ran and passed: `test_migration_creates_tables`, `test_round_trip`, `test_ids_not_stored_by_default`, `test_ensure_schema_leaves_logging_alone`, `test_caplog_works_after_ensure_schema` (test_db.py) and `test_triggers_reject_update_and_delete`, `test_orm_changes_are_rejected_too`, `test_truncate_rejected_on_postgres`, `test_inserts_still_work_in_chunks` (test_audit.py). PostgreSQL support, including the append-only triggers, is now verified on this machine. (Correction made in Milestone 4: the PostgreSQL server was a local `postgres:16` Docker container; what has not run inside Docker yet is LoanLens itself.)
  - Without it: 659 passed, 10 skipped (the 9 PostgreSQL tests and the TRUNCATE check on SQLite).
  - The three test files pass in both orders (127 passed, 1 skipped each). Coverage 99%, ruff clean. Decision logic untouched; the example-decision tests pass.

## Milestone 4: batch jobs, benchmarks, load test (done)
- **Chunked pipeline** (`src/loanlens/pipeline.py`, `batch.ChunkReader`): CSV and Parquet read 20,000 rows at a time; per chunk: validate, score with the shared decision core, write audit records in bulk inserts, append to Parquet and CSV results files and an errors CSV with original row numbers; summary from running counts. Decisions identical to the Milestone 3 path (golden file captured before the change, compared at five chunk sizes).
- **Background jobs** (`src/loanlens/jobs.py`, `src/loanlens/worker.py`, Alembic `0004_batch_jobs`): `batch_jobs` and `batch_workers` tables; atomic claiming (`FOR UPDATE SKIP LOCKED` on PostgreSQL, a conditional `UPDATE` on SQLite); heartbeats, stale jobs failed at start-up, cancel (queued at once, running after the current chunk); `python -m loanlens.worker` (`--once`, `--cleanup`) and an embedded thread when no external worker runs. The worker uses the submitting manager's stored `audit_ref`, not a session token, and checks the account is still an active manager.
- **Files:** private `data/jobs/` (gitignored), random names, no client paths; uploads deleted when a job ends; results and errors deleted after 7 days (`LOANLENS_JOB_RETENTION_DAYS`), jobs then marked expired.
- **Service layer and API:** `submit_batch_job`, `list_batch_jobs`, `get_batch_job`, `cancel_batch_job`, `batch_job_file`, `batch_job_preview` (managers; any manager sees every job). `POST /v1/batches`, `GET /v1/batches`, `GET /v1/batches/{id}`, `GET /v1/batches/{id}/result` (Parquet or CSV), `GET /v1/batches/{id}/errors`, `POST /v1/batches/{id}/cancel`.
- **Bulk Check page:** CSV or Parquet upload (200 MB, `.streamlit/config.toml`), loan type, submit; progress polled by an `st.fragment` every 2 s; job list; summary, downloads and a 1,000-row preview of the selected job.
- **Benchmarks** (`scripts/benchmark_batch.py`, `reports/performance.md`), measured on 2026-11-06 on an i7-11800H laptop: 1,000,000 synthetic rows in 663.7 s (PostgreSQL) and 833.5 s (SQLite) with audit on, 525.9 s and 633.3 s with audit off; peak memory 457 to 527 MB at every size. One PostgreSQL run was invalidated by the laptop sleeping and was repeated.
- **Load test** (`tests/load/locustfile.py`, `reports/load_test.md`): one uvicorn worker levels off at about 18 to 23 scores a second; 4 workers on PostgreSQL served 81 a second at 100 users (p50 93 ms, p95 380 ms, no failures); 4 workers on SQLite failed 1.1% of requests at 100 users on the database lock.
- **Checks on 2026-11-06 (this Windows machine, PostgreSQL 16.15 in a local Docker container on port 5433):**
  - With `LOANLENS_TEST_POSTGRES_URL` set: 746 passed, 2 skipped (the SQLite variants of the TRUNCATE and SKIP LOCKED checks). All 11 PostgreSQL tests ran and passed, including `test_two_workers_never_claim_the_same_job[postgresql]` and `test_skip_locked_skips_a_row_being_claimed[postgresql]`.
  - Without it: 735 passed, 13 skipped. Coverage of `src/loanlens` is 98%, and ruff is clean.
  - The six example decisions are unchanged: `reports/example_decisions.md` regenerated byte-identical.
- **Not done in this milestone:** new screenshots of the Bulk Check page (Milestone 5), the fresh-clone verification.
- Decisions: D-092 to D-100.

## Milestone 5: hosted-ready assets, Docker, deployment, release v2.0 (done)
- **No data folder needed:** the registry and the active model were already committed; `scripts/build_hosted_assets.py` now writes `data/hosted/analytics_aggregates.json` (4 KB of aggregates: approval counts and rates per CIBIL band, loan term and loan-size quintile, and the model's feature-importance shares; no rows). The Analytics page uses it when `data/processed/` is absent and says so; with the data present nothing changes (identical figures, tested).
- **Packaging:** `requirements.txt` is runtime only; `requirements-dev.txt` adds `-e .`, tests, ruff, notebooks, Playwright and Locust; `constraints.txt` pins every indirect package. The project root is found from `LOANLENS_HOME`, the checkout or the current directory, and the app adds `src/` to its import path when the package is not installed. `python -m loanlens.db upgrade` runs the migrations from an installed package. Version 2.0.0.
- **Docker:** multi-stage `Dockerfile` (python:3.11-slim, non-root uid 10001, pinned packages with `xgboost-cpu` of the same version, non-editable install, `HEALTHCHECK` via `python -m loanlens.healthcheck`), allow-list `.dockerignore`, `docker-compose.yml` with `db` (no published port), `migrate`, `api`, `app` and `worker`, a shared `jobs` volume at `/data/jobs`, `LOANLENS_EMBEDDED_WORKER=0` for app and API, and required secrets without defaults. hadolint: no findings.
- **Hosted mode** (`src/loanlens/hosted.py`): Streamlit secrets, refusal of weak secrets and weak bootstrap settings, a warning without an external PostgreSQL database, 5,000-row chunks, at most 200,000 rows and 50 MB per job, temporary job files, and a synthetic-data notice with the cap on the Bulk Check page. Measured on 2026-11-07: Streamlit with its embedded worker peaked at 503 MB on a 200,000-row file.
- **Worker heartbeat** now continues during long jobs (a heartbeat thread), so the app and the container health check see a busy worker as alive.
- **Screenshots:** all 17 retaken against a throwaway database (D-107); the old Bulk Check screenshot and its note were removed.
- **Docs:** README (architecture, quick start, Docker, Deploy, privacy, performance conditions), PROJECT_EXPLAINED (plain-English "Where LoanLens can run", technical section 16), USER_GUIDE (how to open each set-up, hosted limits).

- **Docker actually run on 2026-11-07** (Docker 29.6.2): `docker compose up --build`, all services healthy, manager created with `docker compose run`, sign-in through the API and the app, jobs from the API and from the app run by the worker container with results identical to the expected test output, the example decisions in the container identical to the host, and with `--scale worker=2` four jobs each processed once. Everything created was removed afterwards (D-105).

- **Fresh clone verified on 2026-11-07** outside the project folder with a new Python 3.11 environment, `requirements.txt` only and no data folder: every page of the app (without installing the package), the API after a non-editable install, the worker and the migration command worked; tests 759 passed, 33 skipped, 0 failed after one fix (`tests/test_benchmark.py` no longer needs `nbformat`) (D-108).

- **Checks on 2026-11-07 (this Windows machine):**
  - With `LOANLENS_TEST_POSTGRES_URL` set (PostgreSQL 16.15, local container): **790 passed, 2 skipped**; all 11 PostgreSQL tests ran and passed. Without it: **779 passed, 13 skipped**. Coverage of `src/loanlens` 98%; ruff clean.
  - The example decisions are unchanged: `reports/example_decisions.md` regenerated byte-identical; the 18 decisions (6 examples x 3 loan types) were also identical inside the Docker image.
  - Hosted memory: 503 MB peak for Streamlit with its embedded worker on 200,000 rows (D-106).
  - Release scans and tracked-file audit: see D-110.

- Decisions: D-101 to D-110.

## Sign-in first, role-based navigation and UI redesign (done, not pushed)

- **Part A:** Sign In is the only screen before signing in (no menu, no sidebar). A role selector (Applicant, Bank manager (admin)); the manager portal has no Create account. The stored role decides: a correct password on the wrong portal keeps no session and shows a neutral message; wrong credentials keep the generic message. The menu is built with `st.navigation` from the re-validated session for each role; Home is the dashboard after sign-in; About needs a signed-in user; a temporary password limits the menu to Account. The temporary-signing-key notice is shown only to managers (collapsed, Users and Account). Material icons are allowed; the favicon is an SVG logo mark (D-111 to D-116).
- **Part B:** a design system in `src/loanlens/theme.py` (tokens as CSS variables, Inter font, gradients, cards, focus, motion, breakpoints), a hero Home page with feature cards, a step flow and a trust strip, a two-panel Sign In, a sidebar with logo and user card, and a redesigned result screen with a confidence meter and the applicant's own figures (D-117, D-118).
- **Checks on 2026-11-07:** with `LOANLENS_TEST_POSTGRES_URL` set (PostgreSQL 16.15, local container): **829 passed, 2 skipped** (all 11 PostgreSQL tests ran); without it **818 passed, 13 skipped**; coverage of `src/loanlens` 98%; ruff clean. The example decisions regenerated byte-identical. The app ran (`streamlit run app/Home.py`) for a visitor, an applicant and a manager with every page opened and no error or warning lines in the server log; screenshots retaken (D-119).
