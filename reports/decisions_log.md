# Decisions Log

This log has two parts. **Part 1** is a clean list of every assumption and placeholder for a lender's credit-policy team to review. **Part 2** is the full record, phase by phase, of what was found, what was chosen, and why (entries D-001 to D-064). Every value in Part 1 is illustrative: a lender would replace it with its own credit policy.

## Part 1: Assumptions and placeholders for a lender's credit-policy team to review

### Policy rules (`config/policy.yaml`, all PLACEHOLDER)

| # | Setting | Current value | Enforced? | Effect today | Why this value | Ref |
|---|---|---|---|---|---|---|
| P1 | `rules.min_cibil` | 550 | **Yes**: below 550 is always Rejected, whatever the model says | Fails 7.0% of applicants approved in the data | Where approval drops from about 99% to about 10% in the data | D-016, D-025 |
| P2 | `rules.max_loan_to_income` | 4.0x annual income | **Yes** | Fails 0% of approved applicants | Data range is 1.5x to 4.0x | D-016 |
| P3 | `rules.max_loan_to_assets` | 1.5x total assets | **Yes** | Fails 0% of approved applicants | Generous illustrative cap | D-016 |
| P4 | `rules.min_loan_term_years` | 2 years | **Yes** | Fails 0% | Data minimum | D-016 |
| P5 | `rules.max_loan_term_years` | 20 years | **Yes** | Fails 0% | Data maximum | D-016 |
| P6 | `rules.max_emi_to_income` | 50% of monthly income | **No (advisory warning only)** | Would fail 47% of approved applicants, so enforcing it would contradict the data | Common FOIR-style cap; the real FOIR policy is needed | D-012, D-016 |

Rule of thumb used for the enforce flags: a rule is enforced only if it fails fewer than 5% of the applicants who were approved in the data (milestone 1 review, decision 2). `min_cibil` always overrides the model (milestone 1 review, decision 3).

### Other assumptions and placeholders

| # | Setting / assumption | Current value | Notes | Ref |
|---|---|---|---|---|
| A1 | `emi.assumed_annual_interest_rate` | **10% a year** | The dataset has no interest rate or existing EMIs. Used only for the advisory EMI check. Needs the real product rates. | D-012, D-016 |
| A2 | `model.approval_threshold` | 0.5 | A model score at or above this is Approved (when no enforced rule failed). | D-025 |
| A3 | `model.borderline_band` | 40% to 60% | Model-score band flagged "manual review recommended" (only when no enforced rule failed). | D-025 |
| A4 | `model.borderline_cibil_margin` | +/- 25 points around `min_cibil` | Also flagged borderline, unless another enforced rule failed. | D-033 |
| A5 | `display.probability_bands` | 85 / 65 / 35 / 15% | Verbal labels only (Very likely to Very unlikely); stored scores unchanged. | D-032 |
| A6 | `batch.max_rows` | 50,000 rows | Set from measured speed (50,000 rows scored in 16-32 s). | D-040, D-059 |
| A7 | `storage.store_applicant_ids` | false | Only anonymised batch summaries are stored. | D-041 |
| A8 | `cleaning.negative_assets_strategy` | clip_zero | The 28 rows with residential assets of -1,00,000 are treated as 0. | D-006 |
| A9 | Manager password | env `LOANLENS_MANAGER_PASSWORD`, else secret `manager_password` in the gitignored `.streamlit/secrets.toml`, else the documented local demo default `loanlens-demo` (the sidebar says when the demo default is in use) | Prototype gate, not authentication: no accounts, roles, lockout or audit log. Constant-time comparison. Never host the app with the demo password. | D-057 |
| A10 | Model | Monotone-constrained, isotonic-calibrated XGBoost on CIBIL, loan term, loan-to-income, income, total assets | Trained on synthetic Kaggle data only; predicts the approval decision, not default. | D-019 to D-024 |
| A11 | Feature importance measure | Mean absolute SHAP share (CIBIL 57%) | One measure everywhere. | D-045, D-058 |
| A12 | Data licences | Kaggle metadata shows MIT for the primary and benchmark datasets; `loan_data.csv` source not verified | The Kaggle CSVs are not committed; the test fixture is fully synthetic. | D-060, D-063, D-064 |

### Known data quirks a lender's credit-policy team should be aware of

- Approval in the primary data is almost a "CIBIL above 550" rule (D-009).
- Low-CIBIL applicants with 2- or 4-year loans and a *higher* loan-to-income were approved: a synthetic artefact the model is constrained not to learn (D-011, D-021).
- In the benchmark dataset, previous defaults dominate and credit score has no effect, and the label behaves partly like a default label (D-054, D-056).

## Part 2: Full decision record

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


## Phase 2: EDA

### D-009 Checking the CLAUDE.md section 3 claims (numbers from `02_eda.ipynb`)
| Claim | Actual | Verdict |
|---|---|---|
| About 62% approved | 62.2% (2,656 of 4,269) | Confirmed |
| About 99% approved above CIBIL 550 | 99.5% (2,467 of 2,480) | Confirmed |
| About 10% approved at or below 550 | 10.6% (189 of 1,789) | Confirmed |
| CIBIL-only tree about 95% accuracy | 95.4% (depth-1 stump, 5-fold CV; split learned at 549.5) | Confirmed |
| Random forest about 99.9% accuracy | **98.2%** on raw features; **99.6%** once loan-to-income is added (5-fold CV) | **Corrected**, see D-010 |
| Education, self-employment, dependents have no effect | Spreads of 0.5, 0.03 and 3.9 points; chi-square p = 0.77, 1.00, 0.78 | Confirmed |
| Low-CIBIL approvals are almost all 2 or 4 year terms | 186 of 189 (98.4%) | Confirmed |
| Loan-to-income ranges 1.5 to 4.0 | 1.50 to 4.00 | Confirmed |
| No gender or marital status used | The primary dataset has no such columns | Confirmed |

### D-010 Random forest accuracy is not 99.9% on raw features
- **Found:** a 300-tree random forest gets 98.22% mean accuracy over stratified 5-fold CV on the raw cleaned features. Single 80/20 splits range from 97.4% to 99.2%. Adding the derived loan-to-income ratio gives 99.63%. CIBIL, term and loan-to-income alone give 99.60%.
- **Chose:** the corrected fact is "about 98% on raw features, about 99.6% with loan-to-income". The 99.9% figure is not used anywhere.
- **Why:** these are the numbers the code actually produces. The ratio matters because trees struggle to rebuild a ratio from two raw columns.

### D-011 New quirk: inside the low-CIBIL, short-term group, a higher loan-to-income ratio means approval
- **Found:** for CIBIL at or below 550 with a 2 or 4 year term, approval is 0% when loan-to-income is at or below 2.5, 8 to 13% from 2.5 to 3.0, and 96 to 100% above 3.0. The 13 rejections above CIBIL 550 also have high loan-to-income (median 3.78 vs 3.00 overall).
- **Chose:** documented as a synthetic-data artefact in the notebook's findings. It is not presented as policy.
- **Why it matters later:** the "what would change" search in a later phase could suggest "borrow more" or "take a shorter loan", which would be harmful advice. Logged for the modelling and explainability phases (see Suggestions).

### D-012 The EMI-to-income placeholder conflicts with the data (open issue for the rules phase)
- **Found:** at the assumed 10% rate, EMI-to-income exceeds 0.50 for 1,877 of 4,269 rows (44%). Those rows are approved *more* often (67.1% vs 58.4%), because short terms produce very large EMIs on loans of 1.5 to 4 times annual income.
- **Chose:** the placeholder stays at 0.50, because it sits within the typical Indian FOIR range, and the config already marks it as a placeholder. Nothing was changed in this phase.
- **Why:** rules are a later phase. Decide there with a lender's credit-policy team whether to relax the cap, compute it differently, or accept that the hard rule will override the model for these rows.

### D-013 Charts module
- **Chose:** `src/loanlens/charts.py` contains `cibil_band`, `approval_rate_table` (data helper), `approval_rate_bar`, `approval_by_cibil_band`, `approval_by_quantile_band`, `distribution_by_status` and `approval_heatmap`. That is 5 chart functions plus 2 helpers. The CIBIL band edges are 300/450/550/650/750/900, so 550 falls in the lower band, matching the "at or below 550" claim.
- **Why:** these are generic, data-in and figure-out functions with no Streamlit dependency, so the Analytics page can reuse them. Derived ratios are computed inside the notebook for now, because `features.py` belongs to a later phase.

### D-014 Notebook rendering
- **Chose:** Plotly renderer `plotly_mimetype+notebook_connected`. plotly.js loads from a CDN instead of being embedded, which keeps `02_eda.ipynb` at about 0.8 MB.

### D-015 CLAUDE.md section 3 updated (milestone 1 review, decision 1)
- **Chose:** the random-forest figure is corrected to 98.2% on raw features and 99.6% with loan-to-income, and the loan-to-income quirk (D-011) is added as a second documented quirk.

## Phase 3: Features and rules

### D-016 Policy file restructured with an `enforce` flag per rule (review decision 2)
- **Chose:** each rule is now `{value, enforce}`, validated by `src/loanlens/config.py` (Pydantic). Both values and flags are marked PLACEHOLDER. `min_cibil` stays at 550.
- **Numbers behind each ratio-rule choice** (full table in `reports/rules_vs_labels.md`):
  - `max_emi_to_income` (0.50 at 10% interest): fails **1,260 of 2,656 approved (47.4%)**, so enforce = **false** (advisory warning only).
  - `max_loan_to_income` (4.0): fails **0 approved (0.0%)**, so enforce = **true**.
  - `max_loan_to_assets` (1.5): fails **0 approved (0.0%)**, so enforce = **true**.
- `min_cibil` and both loan-term limits are enforced by decision. Note that `min_cibil` 550 rejects **185 applicants (7.0%) who were approved in the data**, all low-CIBIL short-term approvals from the synthetic quirk. That is intended: the hard rule overrides those quirky labels.
- A test (`test_config_enforce_matches_five_percent_criterion`) fails if the data and the config flags ever disagree.

### D-017 Rule semantics
- **Chose:** a value exactly at a threshold **passes** (CIBIL >= 550, ratios <= cap, term within [2, 20]). Ratios are rounded to 9 decimals before comparison to avoid float noise. A value that cannot be computed (NaN, e.g. EMI with a term of 0) **fails**.
- **Edge cases:** zero income gives an infinite loan-to-income and EMI-to-income, so those rules fail. Zero assets gives an infinite loan-to-assets, so that rule fails. The messages say "No annual income was given" or "No assets were declared" instead of printing "inf".

### D-018 Small supporting modules
- **Chose:** `config.py` (typed policy loader, cached) and `formatting.py` (Indian digit grouping: 12,50,000). Neither is in the CLAUDE.md file list, but both are tiny and shared by rules, explanations and (later) the app. The CIBIL band definition moved into `features.py`, and `charts.py` imports it from there, so it is defined only once.

## Phase 4: Modelling

### D-019 Feature set
- **Chose:** COMPACT = `cibil_score`, `loan_term`, `loan_to_income`, `income_annum`, `total_assets`.
- **Why:** education, self-employment, dependents and the four separate asset columns add nothing. FULL vs COMPACT ROC-AUC for XGBoost is 0.9993 vs 0.9992. Raw `loan_amount` is excluded (D-021). Gender and marital status are blocked in `make_estimator`.
- **Not used:** `emi_to_income`, because it depends on the placeholder interest rate.

### D-020 Leakage and ablation results (XGBoost, COMPACT, unconstrained)
- All features: ROC-AUC 0.9992. CIBIL only: 0.9603. Without CIBIL: 0.5837. Without loan_term: 0.9822. Without loan_to_income: 0.9948. Shuffled labels: 0.499.
- **Verdict:** no leakage. No identifier or target-derived column is used, and there are no duplicate rows. The high scores come from the near-deterministic synthetic label. Suspicious behaviour found: the loan-to-income quirk (D-011).

### D-021 Monotone constraints (review decision 4)
- **Found:**
  - A CIBIL-only constraint costs 0.06 ROC-AUC points, but it does **not** stop the quirk: a 25% bigger loan still raises approval for 66% of low-CIBIL short-term rows.
  - Adding a loan-to-income non-increasing constraint while raw `loan_amount` is still a feature is **bypassed**: the probe rises for 85% of those rows, because the model rebuilds the ratio from `loan_amount` and income.
  - Only removing raw `loan_amount` *and* constraining CIBIL (+) and loan-to-income (-) stops it (probe: 0% of rows rise).
- **Cost:** 0.40 ROC-AUC points (0.9992 to 0.9952), under 1%. F1 against the raw labels falls 2.79 points (0.9957 to 0.9677), but the loss is entirely in CIBIL < 550 rows, which the enforced `min_cibil` rule rejects regardless. On rule-passing rows F1 is 0.9970 vs 0.9968, and for the full rule + model decision 0.9611 vs 0.9609, so effectively no cost.
- **Chose:** use the constraints. The "less than 1%" test is applied to ROC-AUC, the primary threshold-free metric, and confirmed on the rule-gated and full-system F1.

### D-022 Calibration
- **Found (constrained XGBoost):**
  - Uncalibrated: Brier 0.0275, log loss 0.0868.
  - Sigmoid: Brier 0.0310, log loss 0.1143.
  - Isotonic: Brier 0.0257, log loss 0.0803.
- **Chose:** isotonic, which is best on both. `ensemble=False`, so there is one base model for SHAP.
- **Side effect:** isotonic output is step-shaped, so probabilities in the 0.4 to 0.6 borderline band are rare.

### D-023 Model choice
- **Rule:** the simplest model within about 1% ROC-AUC of the best. Simplicity is measured by model size: logistic regression (6 parameters) < XGBoost (about 2,964 leaves) < random forest (about 30,491 leaves).
- **Found:** logistic regression scores 0.9689, more than 1% behind the best, so it is out. Constrained isotonic XGBoost scores 0.9942 and constrained random forest 0.9942. XGBoost is within 0.51 points of the best unconstrained model (0.9993).
- **Chose:** XGBoost, the smaller of the two that qualify. Its native, well-documented monotone constraints are a second reason.
- **Final CV metrics:** ROC-AUC 0.9942, PR-AUC 0.9946, precision 0.9527, recall 0.9759, F1 0.9639, accuracy 0.9546.

### D-024 Model artifact
- **Chose:** a joblib dict (model, features, version 1.0.0, monotone constraints, training ranges, medians of approved applicants used as benchmarks, CV metrics) plus a JSON sidecar. `models/` stays gitignored, so `python -m loanlens.model` rebuilds it. The test fixture trains it automatically if it is missing.

## Phase 5: Explainability and decision engine

### D-025 Decision flow details
- **Chose:** `decide()` follows CLAUDE.md section 5: validate, run the rules, run the model, set the borderline flag, build the reasons.
  - Any *enforced* rule failure means Rejected, whatever the model probability (review decision 3). Advisory failures become warnings that start with "Advisory check:".
  - The model probability is still reported when a rule rejects, for transparency. For example, the 5x-income example shows 60% but is Rejected.
  - `borderline` is set only when no enforced rule failed, because manual review cannot override a hard rule.
- **Invalid input** returns `ValidationFailure` (a list of `FieldError`s with plain-English messages) instead of a `DecisionResult`, so there is no decision at all.

### D-026 Loan term is never used as a model reason
- **Found:** SHAP blames the loan term for low-CIBIL rejections (for example "8 years was approved less often"), because the term effect comes from the synthetic short-term quirk.
- **Chose:** `loan_term` stays a model feature but is never turned into a reason or a positive factor, and "what would change" never touches it (review decision 5). Rule failures on the term limits (outside 2 to 20 years) still state the limit, because that is policy.

### D-027 Reason construction
- **Chose:** rule reasons first (in rule order), then SHAP drivers with |SHAP| >= 0.25 log-odds, ranked by size, with model drivers already covered by a rule removed (e.g. "LOW_CIBIL" when `min_cibil` failed). At most 5 reasons.
  - A negative model reason is shown only if the applicant's value is on the weaker side of the median approved applicant. A high income is never called a weakness.
  - Benchmarks are medians of approved applicants, saved in the model artifact.
- **Fallback:** if a rejection somehow has no reason, an "OVERALL_PROFILE" reason is added. In the full-data run this never triggered.
- **Positive factors** (approvals only): up to 3 positive SHAP drivers. If none clears 0.25, the largest positive driver is used, so every approval gets at least one. Approved results have `reasons == []`. Positive factors go in a separate `positive_factors` field (an addition to the CLAUDE.md output list) so they can never be confused with rejection reasons.

### D-028 What would change
- **Chose:** two searches, one feature at a time, each re-running the full decision (enforced rules + model):
  - CIBIL raised in steps of 5 up to 900.
  - The loan reduced from 99% to 10% of the request in 1% steps, rounded down to Rs 10,000.
- The first approved candidate is reported with "would likely". Because the model is monotone in CIBIL and loan-to-income, the first flip is also the smallest. It never suggests a bigger loan or a different term (enforced by tests).
- If only a term change would help (e.g. a 25-year term), no suggestion is given, and the summary says no single change would likely help.

### D-029 Probability display
- **Found:** isotonic calibration returns exactly 0 or 1 for many applicants.
- **Chose:** the example report shows ">99%" / "<1%" instead of "100%" / "0%", to avoid implying certainty. The app should do the same (see Suggestions).

### D-030 Full-data check of the decision engine
- **Found:** across all 4,269 historical rows (about 16 ms per decision):
  - Agreement with the labels is 95.5%.
  - 1,791 are Rejected, all with at least one reason. 1,785 are led by the CIBIL rule, 4 by low assets and 2 by low income.
  - 11 are borderline.
  - Every rejection gets a "what would change" suggestion.

## Milestone 2 review changes (before Phase 6)

### D-031 Saved model check (review decision 1)
- **Found:** `models/loanlens_model.joblib` was present, so no rebuild was needed. If the model is missing, every app page now shows "The prediction model has not been trained yet... run `python -m loanlens.model`" and stops cleanly.

### D-032 Probability display (review decision 2)
- **Chose:** `formatting.score_percent` never prints 0% or 100%: values above 0.99 show as ">99%" and below 0.01 as "<1%". `likelihood_text` adds the verbal band, e.g. "96% - Very likely". The figure is labelled "model score on synthetic data - indicative only".
- The band cut-offs (0.85 / 0.65 / 0.35 / 0.15) are in `config/policy.yaml` under `display.probability_bands`, marked PLACEHOLDER and validated as strictly decreasing. Stored probabilities are unchanged.
- **Note:** the verbal "Borderline" band (35 to 65%) is wider than the borderline *flag* band (40 to 60%). They are separate settings, and both are shown.

### D-033 Borderline near the CIBIL minimum (review decision 3)
- **Chose:** `borderline = (no enforced rule failed AND p in [0.4, 0.6]) OR (|CIBIL - min_cibil| <= borderline_cibil_margin AND min_cibil is enforced AND no other enforced rule failed)`. The margin defaults to 25 and is in `policy.yaml`.
- **Why the extra condition:** a manual review cannot override, say, a term-limit failure, so the CIBIL margin does not flag those.
- The status is still decided by the rules and the model. This replaces D-025's "borderline only when no enforced rule failed", but only for the CIBIL-margin case.
- A sixth example (CIBIL 540, otherwise strong: Rejected and borderline) was added to `reports/example_decisions.md`.

### D-034 One decision core for both modes (supports review decision 4)
- **Chose:** `decision.decide_many()` is the vectorised core: features, rules, model, SHAP and the "what would change" search in batched passes. `decide()` validates one application and calls the same core with one row. `explain.what_would_change_many()` scores every candidate of every rejected row in one model call, and the single-row version calls it too. Batch and customer mode are therefore identical by construction, and tests check this.

## Phase 6: Customer mode

### D-035 Presentation logic lives in `src/loanlens/presentation.py`
- **Chose:** form field specs (labels, ranges, defaults, help), notices, the policy table and a `DecisionView` (badge headline, likelihood text, reason cards, change summary, warnings, rule table) live in `src/loanlens/presentation.py`. Streamlit pages only lay these out.
- **Why:** pages stay free of logic, and the tests call exactly what the page calls. Shared page chrome is in `app/ui_common.py` (layout only).

### D-036 Form design
- **Chose:** `st.number_input` boxes, each amount followed by a live caption in Indian grouping (e.g. "= Rs 1,50,00,000"). Streamlit number boxes cannot display Indian grouping themselves.
- **No `st.form`:** without it the captions update as you type, and an old result disappears when an input changes, so a stale result is never shown.
- **Ranges:** CIBIL 300 to 900, term 1 to 30 years, amounts from 0 up to generous caps. Zero income or loan is let through to validation so the user gets the friendly message instead of a silent clamp.

### D-037 Privacy and errors
- **Chose:** the customer page imports nothing from storage, writes no files and does not log; a test checks the page source for this. `.streamlit/config.toml` sets `showErrorDetails = false`, so no stack trace reaches users even if something unexpected escapes. Each page also catches errors and shows a friendly message.

## Phase 7: Bank manager batch mode

### D-038 CSV handling
- **Chose:**
  - The delimiter (comma, semicolon, tab or pipe) is detected from the header line, so a "wrong delimiter" file is read correctly instead of rejected. A file that cannot be split at all ends up as "Required columns are missing: ..." with each column named.
  - Text is decoded as UTF-8 (BOM tolerated), falling back to cp1252.
  - Fully blank lines are skipped.
- **Headers:** run through the same `normalise_column_name` as cleaning, then an alias table (e.g. Income / annual_income to `income_annum`, Tenure to `loan_term`, Loan ID to `applicant_id`). Two headers that map to the same column produce a clear error. Unrecognised columns (e.g. a name column) are listed as "not used" and never read further.
- **All 8 inputs are required columns.** A blank asset *cell* is a row error ("... is missing.") rather than a silent 0. A silent 0 would make the loan-to-assets rule reject the row with a misleading reason.

### D-039 Row validation mirrors customer mode
- **Chose:** vectorised checks using the same limits, read from `ApplicantInput`'s field metadata so they cannot drift, and the same messages as `schema.validate_applicant`. A test checks that every bad fixture row is also rejected by the customer validator.
- Amounts like "12,50,000" or "Rs 5,00,000" are accepted. Row numbers are spreadsheet rows (header = row 1). Every problem in a row is reported, and the row is skipped.

### D-040 Scoring, consistency and speed (review decision 4)
- **Chose:** `batch.score()` calls `decide_many()` (the customer-mode core) in chunks of `batch.chunk_size` (2,000), which drives the progress bar and bounds memory.
  - Reasons and "what would change" are built for rejected rows only. Positive factors only when the UI option is ticked. Features, rules and model are vectorised, and SHAP runs on the whole chunk.
- **Measured (this laptop, single-threaded XGBoost):**
  - 1,000 rows: 0.7 s (target 10 s or less)
  - 10,000 rows: 6.2 s (target 90 s or less)
  - 50,000 rows: 32 s
  - So the maximum upload stays at **50,000 rows** (`batch.max_rows`), stated in the UI and README.
- **Consistency test:** 600 fixture rows match `decide()` exactly on status, probability (within 1e-6), reasons and the borderline flag.
- **Output columns:** row, applicant_id, status, probability (stored value), likelihood (display text with band, never 0% or 100%), borderline, reasons ("; "-separated), what_would_change, warnings, reason_codes (machine-readable, used for the summary).
  - `row`, `likelihood`, `warnings` and `reason_codes` are additions to the required list. The warnings carry the out-of-range and advisory notices CLAUDE.md requires.

### D-041 Storage
- **Chose:** `storage.py` (stdlib `sqlite3`) writes one row per batch to `batch_summaries` in `data/loanlens.sqlite` (gitignored via `*.sqlite`). The row holds counts, approval rate, likelihood-band counts, top rejection reason codes and the model version. There are no IDs, names or input values; a test checks that the database file contains no applicant IDs.
- Per-row ID, status and probability go to `batch_rows` only if `storage.store_applicant_ids: true`. The default is false.
- A storage failure never blocks the results; the page shows a small note instead.

### D-042 Bank manager gate
- **Chose:** a sidebar "Bank manager mode" toggle (CLAUDE.md section 7 allows a toggle). It is clearly labelled as a prototype gate, not authentication. Real authentication remains future work.

### D-043 Test fixture
- **Chose:** `tests/fixtures/batch_1000.csv` has 980 real rows from the cleaned public synthetic dataset, with about 5% of amounts written as "12,50,000"-style text. It also has 20 deliberately bad rows at known positions: blank, non-numeric, decimal, out-of-range, zero, negative and infinite values across all columns.

### D-044 Testing the upload path
- **Found:** Streamlit 1.40's AppTest cannot drive `st.file_uploader`.
- **Chose:** the page tests replace `st.file_uploader` with a stub (monkeypatch) and point storage at a temporary file. The post-upload path (summary, filters, saving) is then exercised headlessly.

## Phase 8: Analytics and About pages

### D-045 Feature importance on the Analytics page
- **Chose:** mean absolute SHAP share on the training data (`explain.feature_importance`):
  - CIBIL 57%
  - loan term 19%
  - total assets 12%
  - income 7%
  - loan-to-income 4%
- **Why it differs from the model card:** the model card's "CIBIL is 74% of total gain" is XGBoost's split-gain measure. Both are correct, and the page labels its measure.
- The loan term's large share comes from the synthetic short-term quirk, and the page says so. It is cached per model version with `st.cache_data`, and the training data is cached too.

### D-046 Charts reused and added
- **Chose:** the Analytics page uses the Phase 2 functions `approval_by_cibil_band`, `approval_rate_bar` (loan term) and `approval_by_quantile_band` (loan size). Two small generic functions were added to `charts.py`: `feature_importance_bar` and `counts_bar` (latest batch: top rejection reasons and likelihood bands).

### D-047 About page
- **Chose:** the About page shows:
  - the "approval, not default" framing first
  - data source and model metadata (version, training date, CV metrics, read from the artifact)
  - the illustrative-placeholders notice
  - a table of every current `policy.yaml` value with its enforce setting (review decision 5)
  - `reports/model_card.md`, rendered as is
  - future work (real authentication, real data)
- The model card now also describes the CIBIL-margin borderline rule and the likelihood bands.

### D-048 Consistent look
- **Chose:** every page calls `ui_common.setup_page` (page config, sidebar branding, prototype notice, title) and ends with `ui_common.footer()` (disclaimer). A test checks the footer and title on all five pages. Navigation is Streamlit's multipage sidebar, plus links on Home.

## State on resume (before the UI restyle, Phase 9 and Phase 10)

- **Found:** Phases 0-8 committed (last commit `b0569b4`). A stopped session had left uncommitted restyle work: `src/loanlens/theme.py` (new), `.streamlit/config.toml` theme, CSS and header injection in `app/ui_common.py`, restyled customer, bulk and analytics pages, themed `charts.py`, notebooks 02/03 importing the theme (and re-executed), and `reports/example_decisions.md` regenerated with ✅/❌.
- **Kept:** all of it. Each file was reviewed, `ruff` passed and the full test suite passed (251 tests, including the new `tests/test_theme.py`), with no earlier test modified.
- **Discarded:** nothing. Two defects found while verifying in a real browser were fixed rather than discarded (D-050).
- Re-executing `03_modelling.ipynb` re-runs its final cell, which retrains and re-saves the production model. Training is seeded and deterministic, so only the `trained_at` timestamp changed; all model tests still pass. From Phase 9 on, nothing touches `models/`.

## UI restyle (visual only)

### D-049 Theme module and how styling is attached
- **Chose:** every colour lives in `src/loanlens/theme.py` (palette, darker "ink" text shades, status mapping, CSS, Plotly template, HTML snippets). `app/ui_common.setup_page` injects one CSS block and the header strip on every page; `charts.py` and the notebooks use the shared Plotly template. `.streamlit/config.toml` forces `base = "light"` with the palette; a test keeps it in sync with `theme.STREAMLIT_THEME`.
- **How elements are coloured:** Streamlit 1.40 adds a CSS class `st-key-<key>` to keyed containers, so cards, banners, panels and metric cards are `st.container(key="card_rejected_...")`, `key="banner_approved"`, `key="kpi_warning_..."` etc., styled by CSS. Alerts are recoloured by kind. This kept Streamlit's own `st.success` / `st.error` / `st.metric` elements, so **no earlier test had to change**.
- **Customer result:** banner = keyed container holding the status alert ("✅ Approved" / "❌ Rejected", restyled as a large heading), the amber borderline pill beside it, and the likelihood metric with its band and "indicative only" label. The existing amber borderline note below is kept (it carries the reason). Policy checks are now a list with ✓ / ✗ / ! icons plus the words Pass / Fail / Advisory, instead of a table.
- **Bulk Check:** six metric cards (total scored blue, approved green, rejected red, borderline amber, skipped grey, approval rate blue). The table shows "✅ Approved" / "❌ Rejected" text, coloured with a pandas Styler. Styler marshalling took 0.26 s for 1,000 rows and 0.61 s for 5,000, so colours are applied up to `theme.STYLED_ROWS_LIMIT` = 5,000 visible rows; above that the icon text alone is shown with a caption (filtering brings colours back). The download is still built from the raw results, so its columns and values are unchanged.
- **Skipped rows:** shown inside an amber panel (amber chosen over red because skipped rows are a data warning, not a rejection).

### D-050 Accessibility and two rendering fixes
- **Contrast (WCAG AA, checked in `tests/test_theme.py`):** navy text on white 16.9:1, muted text on white 5.6:1, navy on every tint above 14:1. The brand green, red and amber reach only 3.1-4.6:1 on their tints, and white on the primary blue is 4.38:1. So brand colours are used for borders, icons, chart marks and large headings (3:1 is enough there), while small coloured text uses darker ink shades: green `#157A45` (4.8:1 on its tint), red `#B42318` (5.8:1), amber `#8A5A12` (5.4:1), and buttons / header use blue `#1D5FCF` (5.9:1 with white). Status is never shown by colour alone: always ✅/❌/⚠ plus the word.
- **Fix 1:** Streamlit's fixed toolbar overlapped the header strip; the top padding was increased.
- **Fix 2:** Streamlit's front end replaced a plot background written as `#FFFFFF` with the soft-panel colour. Charts now pin the background as `rgb(255, 255, 255)`, and the Analytics page passes `theme=None` so Streamlit's chart theme does not override the LoanLens template.
- Approval-*rate* bars, feature importance and likelihood-band counts are neutral series, so they use the primary blue; status splits use green/red; rejection-reason counts are red. The approval-rate heatmap uses a red-amber-green scale from the palette.

### D-051 Example applicants
- `reports/example_decisions.md` now shows "✅ Approved" / "❌ Rejected", "⚠️ Borderline: manual review recommended", and ✅/❌/⚠️ on policy checks. Values and outcomes are unchanged.
- The example applicants are not displayed anywhere in the app (no example buttons, not on the About page). Adding them would be a new feature, so nothing was added; see Suggestions.

### D-052 Screenshots
- Playwright is not installed. Screenshots were captured with the locally installed Microsoft Edge in headless mode, driven over the DevTools protocol by a throwaway script kept outside the repository. Files: `reports/screenshots/01_home.png` to `07_about.png` (the eligibility page approved, and rejected + borderline with CIBIL 540; Bulk Check after uploading the 1,000-row test fixture).

## Phase 9: Benchmark on `bank_loan_data.csv`

### D-053 Profile and cleaning
- **Found:** 45,000 rows, 14 columns, no missing values, no duplicates, exactly 10,000 approved / 35,000 rejected (22%). Currency is not stated; amounts look like USD (median income about 67,000, loans 500 to 35,000). Credit scores 390 to 850 (FICO-style scale, not CIBIL's 300-900). Impossible values (ages up to 144, experience up to 125 years) confirm it is synthetic.
- **Chose:** drop the 7 rows with age above 100 (no row has experience longer than age - 14, so that check removes nothing); map `previous_loan_defaults_on_file` to 0/1; drop `person_gender` **and `person_age`** before any modelling. Age is not named in CLAUDE.md, but it is a sensitive attribute, so it is excluded as well.
- Education is kept as a feature (it has no effect in either dataset).

### D-054 Label caution
- **Found:** the dataset card defines `loan_status` 1 = approved, but approval rises with interest rate, loan-to-income and renting. That matches the *default* label of the credit-risk dataset it was derived from. Every applicant with a previous default is rejected, which does match an approval label.
- **Chose:** treat it as the approval decision, as documented, and state clearly in the notebook and `reports/benchmark.md` that those directions are not lessons.

### D-055 Modelling setup
- **Chose:** the same algorithms and hyperparameters as `03_modelling`, the same `cross_validate` / `summary_table` helpers from `loanlens.model`, stratified 5-fold CV with seed 42, preprocessing inside each fold, threshold 0.5. Class imbalance is handled with `class_weight="balanced"` (logistic regression, random forest) and `scale_pos_weight` = rejected / approved (XGBoost). `n_jobs=-1` is used for speed; results do not depend on it.
- The benchmark pipeline lives only in the notebook (it is analysis code, not app logic), so `src/loanlens` is unchanged apart from the About page text.
- **Model safety:** the notebook imports neither `train_final` nor `save_artifact`; the SHAP model is fitted in memory only. The SHA-256 of `models/loanlens_model.joblib` was identical before and after running the notebook, and a test checks the notebook source.

### D-056 Results
- XGBoost ROC-AUC 0.978, PR-AUC 0.938, F1 0.816; random forest ROC-AUC 0.974, F1 0.833; logistic regression ROC-AUC 0.954, F1 0.741.
- Ablations: credit score alone 0.501 (chance); removing it changes ROC-AUC from 0.978 to 0.977; removing previous defaults drops it to 0.935.
- SHAP share: previous defaults 58%, income 8%, interest rate 8%, loan purpose 7%, home ownership 7%, loan-to-income 7%, credit score 3%.
- **Conclusion:** each synthetic dataset is dominated by one rule-like field (CIBIL in the primary, previous defaults in the benchmark). A real system needs previous defaults, employment experience, home ownership, loan purpose, the offered rate and existing EMIs. Details in `reports/benchmark.md`; a short summary is on the About page.

## Phase 10: Hardening and handover

### D-057 Manager gate reads its password from the environment or secrets (review decision 3)
- **Chose:** `src/loanlens/access.py` resolves the password from `LOANLENS_MANAGER_PASSWORD`, then the Streamlit secret `manager_password`, then the documented local-demo default `loanlens-demo` (the sidebar says when the demo default is in use). The comparison is constant-time (`hmac.compare_digest`). The page reads `st.secrets` only when a secrets file exists, because otherwise Streamlit shows its own "No secrets found" error box.
- `.streamlit/secrets.toml` is gitignored; `.streamlit/config.toml` stays tracked. A search of the repository found no other password, token or key.
- **Test change:** the three test helpers that switch on manager mode (`tests/test_batch.py`, `tests/test_pages.py`, `tests/test_theme.py`) now also type the demo password, one added line each. This is required by the new behaviour, not by styling. New tests cover wrong, missing, environment and secrets passwords.

### D-058 One feature-importance measure (review decision 1)
- **Chose:** mean absolute SHAP share is the only headline measure, on the Analytics page, the About page (through the model card) and in `reports/model_card.md` (new "Feature importance" table: CIBIL 57%, loan term 19%, total assets 12%, income 7%, loan-to-income 4%). The model card's old "74% of total gain" headline was replaced, with one sentence explaining why gain gives a different number. The modelling notebook still prints gain as analysis.

### D-059 Hardening walk-through
- **Checked headlessly (AppTest), with no exception and no stack trace in any element:**
  - Customer page: zero income, zero loan, all-zero assets, maximum values in every box, CIBIL 300, CIBIL 540 (borderline flagged), CIBIL 560 with a 25-year term (correctly *not* borderline), 1-year term.
  - Bulk Check: no file, empty file, header-only file, binary junk, missing columns, huge / negative / text values, **50,000 rows (scored through the page in 16 s)** and **51,000 rows** ("The file has 51,000 rows, but the maximum is 50,000 rows per file. Please split it into smaller files.").
- **Coverage:** 98% of `src/loanlens` (`pytest --cov=loanlens`). New tests target the important gaps: the fallback reason that guarantees every rejection has a reason, the cp1252 CSV fallback, binary files, empty batches, CIBIL candidates near 900, non-finite display values, and the single-row "what would change" wrapper.
- `pytest-cov` was added to `requirements.txt` (dev tooling) so coverage can be re-run.

### D-060 Data files and licences (review decision 5)
- **Found:** the Kaggle licences could not be verified from inside the project, and `data/processed/loan_approval_clean.csv` (a full cleaned copy of the primary dataset) had been committed in Phase 1.
- **Chose:** all three raw CSVs stay gitignored. `data/processed/` is now gitignored too and the processed file was removed from the index (it remains in earlier commits; history was not rewritten). `python -m loanlens.model` rebuilds it automatically. README lists the sources and download links. The source page of the 381-row `loan_data.csv` was never recorded, so README describes it without inventing a link.
- `tests/fixtures/batch_1000.csv` (980 sample rows plus 20 synthetic bad rows) is kept so the tests can run; remove it if the dataset licence turns out not to allow redistribution.

### D-061 Fresh-clone setup
- **Chose:** `requirements.txt` ends with `-e .`, so installing the requirements also installs the `loanlens` package (three commands: create the venv, install, run). `python -m loanlens.model` now builds the cleaned dataset first if it is missing, and stops with a clear message if `data/raw/loan_approval_dataset.csv` is absent. The package version is now 1.0.0.

## State on resume (before the reframe and publication)

- **Found:** working tree clean on `master`, last commit `c73df48` ("Phase 10: fresh-clone verification recorded"), tag `v1.0` on it, no remote. The fresh-clone verification had in fact been recorded in `progress.md`. No leftover `.fresh_clone_test/` folder and no `big_50k.csv` / `big_51k.csv` (or any file over 5 MB outside `.venv`) remained. Baseline: `ruff check .` passed, `pytest` 281 passed.
- **Kept:** everything. **Discarded:** nothing.

## Reframe and publication

### D-062 Reframed as an independent proof of concept
- **Found:** 56 occurrences of the former affiliation / reviewer wording across 16 files (22 in `config/policy.yaml` comments; the rest in CLAUDE.md, README, USER_GUIDE, two app pages, `presentation.py` and `rules.py` user-facing text, notebook 02 and 04 markdown cells, and five reports).
- **Chose:** LoanLens is an independent proof of concept by Anshu Raj, to be pitched to lenders, with no bank affiliation or endorsement. Every placeholder note now reads "PLACEHOLDER - illustrative value; a lender would replace it with its own credit policy" or "illustrative until replaced by a lender's real credit policy"; review notes are "for a lender's credit-policy team to review". `reports/rules_vs_labels.md` was regenerated from `rules.py` and matches. No test asserted the old wording; `test_thresholds_note_mentions_placeholders` now also checks the new wording and that no bank is named. Behaviour is unchanged.

### D-063 Dataset credits re-checked
- **Found:** README credited `bank_loan_data.csv` to a different Kaggle upload (`taweilo/loan-approval-classification-data`). The file was actually downloaded from https://www.kaggle.com/datasets/udaymalviya/bank-loan-data. Kaggle's metadata API (the HTML pages render no content to a script) shows: `udaymalviya/bank-loan-data`, MIT licence, 45,000 records, 14 columns matching ours, described as synthetic, with `loan_status` described as 1 = repaid, 0 = defaulted; `architsharma01/loan-approval-prediction-dataset`, MIT licence. The source of the 381-row `loan_data.csv` could not be verified.
- **Chose:** README now cites the two verified pages with "licence shown: MIT" (and asks readers to check before redistributing) and says "source not verified" for `loan_data.csv`. `reports/benchmark.md` adds one sentence noting that the source page itself calls the label repaid/defaulted, which strengthens the existing label caution (D-054). The benchmark notebook's analysis and numbers are unchanged.

### D-064 Fully synthetic test fixture
- **Found:** `tests/fixtures/batch_1000.csv` held 980 rows sampled from the primary Kaggle dataset, and its 20 bad rows were built on one real row.
- **Chose:** replaced it with a fully synthetic file from `scripts/make_batch_fixture.py` (seed 20261106): CIBIL uniform 300-900, income 2-99 lakh, loan 1.5x-4x income, even terms 2-20 years, assets scaled to income, about 5% of incomes and loan amounts written with Indian grouping, and the same 20 bad rows (same line numbers and error types) so `tests/test_batch.py` needed no change. Scored result: 980 valid rows, 547 Approved, 433 Rejected, 80 borderline; all 281 tests pass. Since nothing in the repository now comes from the Kaggle files, the earlier caveat in D-060 about redistributing the fixture no longer applies.

### D-065 Screenshots retaken with Playwright
- **Chose:** Playwright 1.49.1 with Chromium installed *inside* the virtual environment (`PLAYWRIGHT_BROWSERS_PATH=0`), listed in a new `requirements-dev.txt` rather than `requirements.txt`. A throwaway capture script (kept outside the repository) starts the app, fills the form with built-in example applicants (approved: example 1; rejected: example 3, CIBIL 480; rejected + borderline: example 6, CIBIL 540) and uploads the synthetic fixture, with the skipped-rows report expanded.
- **Password:** the server was started with a random, never-printed `LOANLENS_MANAGER_PASSWORD`, so neither a real nor the demo password was typed on screen (the field shows only masked dots) and the "demo password in use" note does not appear.
- **Files:** the seven existing names were kept and `08_eligibility_rejected.png` was added for the plain rejected result. Each PNG was quantised to 256 colours (48-194 KB) and checked visually: no blank pages, errors or bank names. Old screenshots in the git history showed the former wording, so they are removed from history during the rewrite (D-066).

## Suggestions
- In the modelling phase, consider adding loan-to-income (and possibly EMI-to-income) as a model feature. It explains most of the gap between 98.2% and 99.6%.
- In the explainability phase, limit "what would change" to directions that make lending sense (raise CIBIL, lower the loan) and never suggest increasing the loan or shortening the term just because the synthetic data rewards it.
- Settle the EMI-to-income cap (D-012) with a lender's credit-policy team before building `rules.py`.
- In the app phase, display probabilities above 99% as ">99%" and below 1% as "<1%" (isotonic output reaches exactly 0 and 1), and show the model probability alongside any rule-based rejection with a clear "policy rule applied" label.
- In the batch phase, vectorise `decide()` (rules via `rule_pass_frame`, a single `predict_proba`, and SHAP on the whole batch) instead of calling it row by row. At about 16 ms per row, 1,000 rows would take about 16 s.
- Consider a co-applicant income field later; the dataset has none, so it was not modelled.
- For uploads above 50,000 rows, XGBoost could use more threads (`n_jobs`) at scoring time only; training stays single-threaded for determinism.
- Optional "Try an example" buttons on the customer page that load the six hypothetical examples, shown with the same ✅/❌ styling.
- Add a LICENSE file (for example MIT) so others know how they may reuse the code; the datasets keep their own licences.
- Add GitHub repository topics (streamlit, explainable-ai, credit-scoring, xgboost, shap) and a short description.
- Add a GitHub Actions workflow running `ruff` and the data-free part of `pytest` on each push.
