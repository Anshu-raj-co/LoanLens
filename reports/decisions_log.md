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

- **Found:** Phases 0-8 committed (last commit `b0569b4`). A stopped session had left uncommitted restyle work: `src/loanlens/theme.py` (new), `.streamlit/config.toml` theme, CSS and header injection in `app/ui_common.py`, restyled customer, bulk and analytics pages, themed `charts.py`, notebooks 02/03 importing the theme (and re-executed), and `reports/example_decisions.md` regenerated with [tick]/[cross].
- **Kept:** all of it. Each file was reviewed, `ruff` passed and the full test suite passed (251 tests, including the new `tests/test_theme.py`), with no earlier test modified.
- **Discarded:** nothing. Two defects found while verifying in a real browser were fixed rather than discarded (D-050).
- Re-executing `03_modelling.ipynb` re-runs its final cell, which retrains and re-saves the production model. Training is seeded and deterministic, so only the `trained_at` timestamp changed; all model tests still pass. From Phase 9 on, nothing touches `models/`.

## UI restyle (visual only)

### D-049 Theme module and how styling is attached
- **Chose:** every colour lives in `src/loanlens/theme.py` (palette, darker "ink" text shades, status mapping, CSS, Plotly template, HTML snippets). `app/ui_common.setup_page` injects one CSS block and the header strip on every page; `charts.py` and the notebooks use the shared Plotly template. `.streamlit/config.toml` forces `base = "light"` with the palette; a test keeps it in sync with `theme.STREAMLIT_THEME`.
- **How elements are coloured:** Streamlit 1.40 adds a CSS class `st-key-<key>` to keyed containers, so cards, banners, panels and metric cards are `st.container(key="card_rejected_...")`, `key="banner_approved"`, `key="kpi_warning_..."` etc., styled by CSS. Alerts are recoloured by kind. This kept Streamlit's own `st.success` / `st.error` / `st.metric` elements, so **no earlier test had to change**.
- **Customer result:** banner = keyed container holding the status alert ("[tick] Approved" / "[cross] Rejected", restyled as a large heading), the amber borderline pill beside it, and the likelihood metric with its band and "indicative only" label. The existing amber borderline note below is kept (it carries the reason). Policy checks are now a list with [tick mark] / [cross mark] / ! icons plus the words Pass / Fail / Advisory, instead of a table.
- **Bulk Check:** six metric cards (total scored blue, approved green, rejected red, borderline amber, skipped grey, approval rate blue). The table shows "[tick] Approved" / "[cross] Rejected" text, coloured with a pandas Styler. Styler marshalling took 0.26 s for 1,000 rows and 0.61 s for 5,000, so colours are applied up to `theme.STYLED_ROWS_LIMIT` = 5,000 visible rows; above that the icon text alone is shown with a caption (filtering brings colours back). The download is still built from the raw results, so its columns and values are unchanged.
- **Skipped rows:** shown inside an amber panel (amber chosen over red because skipped rows are a data warning, not a rejection).

### D-050 Accessibility and two rendering fixes
- **Contrast (WCAG AA, checked in `tests/test_theme.py`):** navy text on white 16.9:1, muted text on white 5.6:1, navy on every tint above 14:1. The brand green, red and amber reach only 3.1-4.6:1 on their tints, and white on the primary blue is 4.38:1. So brand colours are used for borders, icons, chart marks and large headings (3:1 is enough there), while small coloured text uses darker ink shades: green `#157A45` (4.8:1 on its tint), red `#B42318` (5.8:1), amber `#8A5A12` (5.4:1), and buttons / header use blue `#1D5FCF` (5.9:1 with white). Status is never shown by colour alone: always [tick]/[cross]/[warning sign] plus the word.
- **Fix 1:** Streamlit's fixed toolbar overlapped the header strip; the top padding was increased.
- **Fix 2:** Streamlit's front end replaced a plot background written as `#FFFFFF` with the soft-panel colour. Charts now pin the background as `rgb(255, 255, 255)`, and the Analytics page passes `theme=None` so Streamlit's chart theme does not override the LoanLens template.
- Approval-*rate* bars, feature importance and likelihood-band counts are neutral series, so they use the primary blue; status splits use green/red; rejection-reason counts are red. The approval-rate heatmap uses a red-amber-green scale from the palette.

### D-051 Example applicants
- `reports/example_decisions.md` now shows "[tick] Approved" / "[cross] Rejected", "[warning sign] Borderline: manual review recommended", and [tick]/[cross]/[warning sign] on policy checks. Values and outcomes are unchanged.
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

### D-066 History rewrite before publication
- **Found:** before the rewrite, 14 of 18 commits contained the former affiliation / reviewer wording (no commit *message* did). Every commit's author and committer used a personal email. Earlier commits also held `data/processed/loan_approval_clean.csv` (a full cleaned copy of the Kaggle data, D-060), the old Kaggle-sample test fixture, and old screenshots showing the former wording.
- **Chose:** the GitHub repository was empty, so rewriting was safe. A backup bundle of the original history was made first (`../loanlens-backup.bundle`, verified, unchanged afterwards). Then `git filter-repo` (2.45.0, installed in the venv) ran with:
  - `--replace-text` / `--replace-message`: the specific phrasings mapped to the Step 1 wording, followed by case-insensitive safety nets;
  - `--mailmap`: every author and committer set to `Anshu Raj <59351492+Anshu-raj-co@users.noreply.github.com>` (GitHub no-reply address, so no personal email is exposed);
  - `--strip-blobs-with-ids`: the 15 historical versions of the processed dataset, the old fixture and the old screenshots. The current synthetic fixture and screenshots are kept. Historical commits therefore lack those files, and their tests would not run as-is; only the final commit is meant to be run.
- **Result:** 17 commits (one became empty and was pruned). `git log --all -p` finds 0 matches for the scrubbed terms. ruff passes and 281 tests pass on the rewritten `main`. Tag `v1.0` was deleted before the rewrite and recreated on the final commit. The repository's `user.name` / `user.email` are set to the same identity.

### D-067 Pre-push audit
- **Tracked files (77):** code, tests, the synthetic `tests/fixtures/`, notebooks, `reports/` (with screenshots), `config/policy.yaml`, `.streamlit/config.toml`, requirements files and documentation. No tracked file is over 1 MB; the largest blob in history is a notebook (946 KB).
- **Confirmed ignored:** `data/raw/`, `data/processed/`, `models/`, `.venv/`, `.fresh_clone_test/`, `__pycache__/`, `.streamlit/secrets.toml`, `.env`, `*.db`, `*.sqlite*`, notebook checkpoints and `.coverage`. Two gaps were closed: `*.sqlite*` (journal files) and `big_*.csv` (stress-test files).
- **Secret scan (tracked files and full history):** no keys, tokens or private keys. The only hard-coded password is the documented local demo default `loanlens-demo`, plus the README example value `"choose-a-password"`. The only email addresses in history are the GitHub no-reply address and the co-author attribution address.

## Visual cleanup: no emoji, no disclaimer box, simpler header (visual only)

### D-068 Emoji removed, status shown by colour plus words
- **Found:** emoji or icon characters in page titles and `page_icon` values, Home card titles and page-link icons, result banners, the borderline pill and warning, the reason, change and positive-factor lines, Bulk Check and Analytics metric labels, `theme.STATUS_ICONS`, the [tick mark] / [cross mark] / ! policy-check marks and the [ring logo] header logo. `config/policy.yaml` and `reports/model_card.md` (shown on About) had none.
- **Chose:** every one removed, and the colours left as they were. Status is now the word "Approved" / "Rejected" (`theme.status_label` returns the plain status). The pill reads "Borderline - manual review recommended". Policy checks show the coloured word "Passed", "Failed" or, for the advisory EMI rule, "Advisory" (the task names only Passed / Failed; "Advisory" keeps the existing third state as a word). Lines that used to start with an emoji now show their text alone, with nothing in its place.
- **`page_icon`:** the argument is no longer passed (`setup_page(title)` has no icon parameter), so the browser tab shows Streamlit's default favicon. No icon character is used anywhere.
- **Also covered:** `scripts/example_decisions.py` now writes "Passed / Failed / Advisory" and plain status words; `reports/example_decisions.md` was regenerated from it. Emoji were removed from README, USER_GUIDE and PROJECT_EXPLAINED. Typographic arrows (→) in PROJECT_EXPLAINED are not emoji and the app never shows them, so they were kept. Older entries in this log and in `progress.md` are historical records and were left unchanged.
- **Guard:** `tests/test_no_emoji.py` checks every Python file under `app/` and `src/loanlens/`, `config/policy.yaml` and `reports/model_card.md` for emoji and shortcodes. It also checks the visible text of all five rendered pages, of an approved, a rejected and a borderline customer result, and of Bulk Check after the fixture is uploaded. The emoji pattern covers the common Unicode emoji ranges, variation selectors and the ZWJ. The shortcode pattern ignores Sphinx roles such as `:func:` in docstrings.

### D-069 Disclaimer box removed from Home; header shows the title only
- **Found:** the yellow box with `presentation.DISCLAIMER` was rendered only on Home. The other yellow boxes ("Prototype - not a lending decision...", "Approval, not default" on About, borderline and warnings) are different text, so they stay.
- **Chose:** removed `st.warning(DISCLAIMER)` from Home. The disclaimer text still appears in every page footer, including About (a test checks it is on About), and in README.
- **Header:** the strip now shows only "LoanLens", in white at 2.4rem, weight 800. The tagline and logo are gone. `align-items: center` with a 4.4rem minimum height centres the title vertically. The strip keeps its colour, padding and margin, and the main container's 3.6rem top padding keeps it clear of Streamlit's toolbar (checked in the screenshots).
- **Unchanged (verified):** decision logic, thresholds, model, reason wording, batch processing, pages and navigation. For the six built-in examples, `decide()` gives byte-identical status, probability, borderline flag, reasons, what-would-change, rule results and warnings before and after the change.

## Milestone 1: database layer, policy profiles, model registry

### State on resume (before Milestone 1)
- **Found:** clean tree at `2fe6607` (visual cleanup pushed). 316 tests passing, ruff clean. One policy file (`config/policy.yaml`), one unversioned model file (`models/loanlens_model.joblib`, SHA-256 `49b800ef9416...`), and `storage.py` on stdlib `sqlite3`. A local `data/loanlens.sqlite` (gitignored) held 13 batch summaries created by the old code.
- **Step 0:** section 14 (platform phase rules) appended to CLAUDE.md verbatim and committed on its own (`3c403ba`).
- **Baseline:** before any change, `decide()` output for the six built-in examples (status, probability, borderline, reasons, what-would-change, rule results, warnings) was saved and compared again after each part. It stayed byte-identical throughout.

### D-070 Database layer (SQLAlchemy 2 + Alembic)
- **Chose:** `src/loanlens/db/engine.py` handles the URL, engine and sessions, and `db/models.py` holds the tables. The URL comes from `DATABASE_URL`, defaulting to `sqlite:///data/loanlens.sqlite`; relative SQLite paths resolve against the project root. `postgresql://` and `postgresql+psycopg2://` URLs are rewritten to `postgresql+psycopg://`.
- **Pinned versions:** SQLAlchemy 2.0.57, alembic 1.20.1, psycopg[binary] 3.3.8 (all on the allowed list).
- **Schema identical to the old one:** `batch_summaries` is an ORM class. `batch_rows` stays a Core table because the original schema has no primary key, and adding one would change existing databases. Inserts into it are parameterised Core statements.
- **Migrations:** they live inside the package (`src/loanlens/db/migrations/`, revision `0001_initial`), so the app can apply them itself. `ensure_schema()` runs `upgrade head` once per URL per process on the app's own connection, and `env.py` only reconfigures logging when run from the `alembic` CLI. The initial migration creates each table only if it is missing, so the existing local database was adopted. Checked on a copy: 13 rows kept, `alembic_version` = `0001_initial`. In offline `--sql` mode the existence check is skipped. `alembic.ini` sits at the project root.
- **Storage behaviour unchanged:** same function signatures, return values, NaN rate stored as NULL, newest first, and `None` / empty table when the SQLite file does not exist yet (no file is created on read). The URL is chosen in this order: an explicit `path` (tests), then `DATABASE_URL`, then `storage.db_path` from the policy. Existing tests that redirect `storage.db_path` keep working.
- **Friendly failures:** every SQLAlchemy error becomes a `DatabaseError` with a fixed plain message. It never includes the URL, host or password, and the driver error is suppressed (`from None`). PostgreSQL connections time out after 5 seconds; without a timeout an unreachable server hung for more than two minutes in a first check. Bulk Check shows the message as a note under the results, and Analytics shows it in its error box.
- **Tests:** `tests/test_db.py` covers migrations, round trip, IDs off by default, legacy upgrade, URL order and normalisation, the friendly errors and the `alembic` CLI (upgrade, downgrade, `--sql`). They run on SQLite always and on PostgreSQL only when `LOANLENS_TEST_POSTGRES_URL` is set.
- **PostgreSQL not exercised here:** Docker 29.6.2 is installed, but its engine was not running, and starting Docker Desktop would act outside the project, so it was not started. The three PostgreSQL tests were skipped. No PostgreSQL run is claimed.
- **Test isolation:** an autouse fixture in `tests/conftest.py` removes `DATABASE_URL` and `LOANLENS_MODEL_VERSION` for every test, so a developer's settings never leak in.

### D-071 Policy profiles
- **Layout:** `config/policy.yaml` was moved with `git mv` to `config/policies/personal.yaml`. Its only changes are the header comment and three new keys: `profile: personal`, `version: "1.0.0"`, `description`. Every rule, EMI, model, display, batch, storage and cleaning value is unchanged. `home.yaml` and `vehicle.yaml` contain only the decision sections (rules, emi, model, display).
- **Illustrative differences** (all marked PLACEHOLDER):
  - **Home:** term 5-30 years, 6.0x income, 2.0x assets, 8.5% rate.
  - **Vehicle:** term 1-7 years, 1.5x income, 1.0x assets, 11% rate.
  - **Same in all three:** minimum CIBIL, EMI cap and every model setting (threshold, band, margin), so a profile changes rules and assumptions only.
  - These numbers are not taken from any lender. They only show the mechanism.
- **App-wide settings:** batch limits, storage and cleaning are read from the default profile only, because one upload can mix loan types.
- **Content hash:** SHA-256 of the validated settings as canonical JSON (`model_dump`, sorted keys), not of the raw file bytes. Comment or spacing edits do not change it; any value change does. Exposed as `Policy.content_hash`, a cached property computed when the file loads.
- **Names:** `load_profile()` ignores case and spaces, and blank means personal. A name must match `^[a-z][a-z0-9_]{0,31}$` and have a file. Anything else, including path tricks such as `../personal`, raises `UnknownProfileError`, whose message lists the valid names.
- **Backward compatibility:** `load_policy()` and `POLICY_PATH` now point at the personal profile, and `cleaning.py` reads `cleaning.negative_assets_strategy` from it. `decide()` and `decide_many()` accept `profile=`; an explicit `policy=` still wins.
- **New result fields:** `DecisionResult` gains `profile`, `policy_version` and `policy_hash` (with `model_version`, which already existed). These four fields are the only change to the output.
- **Batch:**
  - The optional `product` column also accepts the headers loan_type, product_type, loan_product and profile.
  - Blank means personal. An unknown value is a row error that names the valid types.
  - Within each chunk, rows are grouped by product and decided under their own profile, and row order is kept.
  - Results gain a `product` column.
  - The download template is unchanged; the `product` column is documented on the page and in USER_GUIDE.
- **UI:** a "Loan type" selector at the top of the customer form, whose caption and thresholds note follow the selection. A provenance line under the result gives profile, policy version, settings hash and model version. About shows all profiles side by side, with version and hash. Every place states that loan types change the rules and assumptions, not the trained model.
- **Tests:** `tests/test_profiles.py`:
  - personal reproduces the six example decisions, pinned to their pre-profile probabilities, and is identical to the default;
  - each profile's term, income-multiple, asset-multiple and interest-rate rules apply;
  - unknown and malicious names are rejected;
  - hash stability and semantic-version validation;
  - the `product` column, aliases, mixed products across chunks and the loan-type selector on the page.
- **Text references updated:** the old path is replaced in code, UI text, `rules.py`, which regenerated `reports/rules_vs_labels.md` (one line changed), the model card, notebook 01 (one markdown cell, no outputs touched) and three path mentions in CLAUDE.md sections 5, 8 and 10, which are factual paths, not rules. `reports/example_decisions.md` regenerated byte-identical.

### D-072 Model registry
- **Format:** `src/loanlens/registry.py` keeps `models/registry.json`, validated with Pydantic. Each entry records `version`, `created_at`, `training_data_hash`, `n_train`, `features`, `kind`, `calibration`, `cv_metrics`, `artifact`, `artifact_sha256`, `artifact_bytes`, `status` and `notes`. Exactly one entry is active, and writes are atomic (temporary file, then replace).
- **Training:**
  - `python -m loanlens.model` trains a new version: the next minor version by default, or `--version X.Y.Z`.
  - It saves `loanlens_model_<version>.joblib` and registers it.
  - It activates the new version unless `--no-activate` is given. Activating by default matches the old behaviour, where training replaced the model.
  - Older artifacts are kept.
- **CLI:** `--list` prints the registry. `--activate <version>` verifies the file's hash before switching.
- **Loading:** `load_artifact()` with no path uses `LOANLENS_MODEL_VERSION` or the active version, and checks the SHA-256 before loading (about 0.4 MB, hashed on each call). A mismatch raises `ArtifactIntegrityError`, which the app shows as a plain message. `load_artifact(path)` still loads a given file directly, which older tests and notebooks use.
- **Existing artifact:** `migrate_legacy_artifact()` runs once when no registry exists. It renames `models/loanlens_model.joblib` (and its JSON sidecar) to `loanlens_model_1.0.0.joblib` and registers it as active.
  - SHA-256 is the same before and after: `49b800ef9416d983454038326513a400ed3bddf129c9f1b2d5f4c61ac86797f4`, so predictions are unchanged.
  - Its training-data hash (`4cbe223d...`) was computed at registration time from the current `data/processed/loan_approval_clean.csv`, not at original training time; the entry's `notes` field says so. The row count matches (4,269).
  - `MODEL_PATH` is kept as an alias of the legacy path, for notebook 03.
- **Committed files:** `.gitignore` now un-ignores `models/registry.json`, `models/loanlens_model_1.0.0.joblib` (397,777 bytes) and its `.json`, so a fresh clone can score without retraining. The artifact contains the model plus aggregate metadata (feature ranges, approved-applicant medians), no data rows. Archived versions stay local. After activating another version, the two artifact lines in `.gitignore` must be updated by hand (noted in the file).
- **Tests:** `tests/test_registry.py` covers:
  - the committed registry (one active entry, verified hash, metrics);
  - predictions unchanged through the registry;
  - round trip, activation, duplicates and the environment override;
  - hash mismatch on load and on activate, missing files, an invalid registry file and version-name checks;
  - legacy migration (bytes unchanged, runs once), training with older versions kept, and the CLI.

### D-073 Documentation for Milestone 1
- README, USER_GUIDE, PROJECT_EXPLAINED (Part 1 gained two jargon-free sections: "Different kinds of loan" and "Keeping a record"), the model card, `.env.example` (names only) and the screenshots were updated. The 02 form now shows the loan-type selector, and 07 About shows model versions and the profile table.
- README now says the earlier fresh-clone verification predates Milestone 1 and was not repeated.

## Milestone 2: authentication and roles

### State on resume (before Milestone 2)
- **Found:** `main` at `199b235` (Milestone 1), two commits ahead of `origin/main`, not pushed. The only uncommitted change was CLAUDE.md, which the owner had restructured (sections 1 to 15, with the platform-phase status table). That change is kept and included in the Milestone 2 commit, together with this milestone's status update, as section 14 asks.
- **Baseline:** 376 tests passed, 3 PostgreSQL tests skipped, ruff clean. The six example decisions were compared again at the end and are byte-identical to the saved baseline.

### D-074 Account tables
- **Chose:** two tables in the same database as the batch summaries (`storage.resolve_url()`: `DATABASE_URL`, else the local SQLite file), added by Alembic revision `0002_auth`.
  - `users`: id, `audit_ref` (random UUID, unique, separate from the id), email (unique, lower-case), `password_hash`, role (check constraint: `applicant` or `manager`), `is_active`, `must_change_password`, `created_at`, `last_login_at`, `failed_attempts`, `locked_until`.
  - `auth_events`: id, `occurred_at`, `user_id`, `actor_id`, `event_type`, `success`, `reason`.
- **Two small departures from the prompt's wording:**
  - The timestamp column is named `occurred_at` rather than `timestamp`, which is also an SQL type name.
  - `actor_id` was added, so manager actions (deactivate, temporary password, create manager) record who acted.
- **Deletion:** both event links use `ON DELETE SET NULL`, and `delete_own_account` also clears them explicitly. A deleted account leaves no link from older events, and the deletion itself is logged with no user id.
- **Times** are stored in UTC. SQLite returns them without a time zone, so they are read back as UTC.

### D-075 Passwords and email addresses
- **Hashing:** argon2id through argon2-cffi 25.1.0 with the library defaults (time cost 3, 64 MiB, parallelism 4; the RFC 9106 low-memory profile), with the type pinned to argon2id. If the parameters ever change, the hash is refreshed at the next successful sign-in.
- **Policy:**
  - 10 to 128 characters;
  - not on `src/loanlens/auth/common_passwords.txt` (about 130 widely published common passwords, plus project-specific ones such as the old demo password `loanlens-demo`), compared case-insensitively;
  - not equal to the email.
  - The messages are plain sentences listing each problem.
- **Email:** trimmed, lower-cased and checked with a regular expression (a single `@`, a dotted domain, length limits, no double dots). `email-validator`, which Pydantic's `EmailStr` needs, is not on the allowed dependency list.
- **Input validation:** Pydantic models (`NewAccount`, `NewPassword`) with `hide_input_in_errors=True`. Their errors are turned into `InputError` and never echo the input.

### D-076 Sign-in and lockout
- **One message for every failure:** "Incorrect email or password", whether the email is unknown or malformed, the password is wrong, the account is locked or the account is deactivated. The reason is recorded only as a code in `auth_events`.
- **Timing:** unknown or malformed emails and locked accounts still run one argon2 check against a dummy hash, so response time does not reveal whether an account exists.
- **Lockout:**
  - The fifth wrong password in a row sets `locked_until` to 15 minutes later and resets the counter.
  - While locked, even the right password is refused.
  - When the lock expires, counting starts again; a successful sign-in also resets the counter.
- **Configuration:** `LOANLENS_LOCKOUT_ATTEMPTS`, `LOANLENS_LOCKOUT_MINUTES` and `LOANLENS_SESSION_MINUTES`, validated with Pydantic. An invalid value stops the app with a message naming the variable.
- **Known trade-off:** sign-up says "An account with this email already exists", which reveals that an email is registered. Without email verification there is no way to hide this and still give a useful message. Logged under Suggestions.

### D-077 Sessions (JWT)
- **Token:** HS256 via PyJWT 2.10.1. Claims: `sub` (user id), `role`, `iat`, `exp`, `iss=loanlens`, all required on decode, with the algorithm list fixed to HS256 (so `alg: none` is rejected). No email or other personal data is in the token.
- **Revalidation:** on every page load, `principal_from_token` checks the signature and expiry, then re-reads the account. It must exist, be active and still have the role named in the token. Deactivating an account or changing its role therefore ends its sessions at once.
- **Secret:**
  - Comes from `LOANLENS_JWT_SECRET` and must be at least 32 characters; shorter is refused.
  - Missing in local development: one temporary key is generated per process, a warning is logged once and the sidebar shows it.
  - Missing with `LOANLENS_ENV=production` or `LOANLENS_HOSTED=1` (also `true`, `yes`, `on`): every page shows "LoanLens cannot start" and stops.
- **Storage:** the token and principal live only in `st.session_state`. That is why a page refresh ends the session (a documented limitation).
- **No revocation list:** a token issued before a password change stays valid until it expires (at most 60 minutes) unless the account is deactivated. Logged under Suggestions.

### D-078 Roles are enforced in the service layer
- **Checks:** every function in `loanlens.auth.service` that acts for a user takes a `Principal` and calls `require_role`. Manager functions (`list_users`, `create_manager`, `set_active`, `set_temporary_password`) and own-account functions (`change_password`, `delete_own_account`) also re-load the acting account inside the same database session. A hand-built `Principal(role="manager")` is therefore refused (tested).
- **Pages:** they call `require_user(*roles)` in `app/ui_common.py`, which uses the same `require_role` and shows a plain message instead of the page.
- **Not yet covered:** batch scoring and the Analytics data functions are gated by their pages, not inside `batch.py` and `storage.py`. The shared service layer for those (used by the API and worker) belongs to Milestone 3 in CLAUDE.md section 15, so it was not built here. Logged under Suggestions.

### D-079 Creating managers
- **Command line:** `python -m loanlens.auth create-manager --email <email>` reads the password twice with `getpass` and has no password option (passing `--password` is an argparse error). It prints only a success line, never the password. Managers created this way do not have to change their password, because they chose it themselves.
- **Bootstrap:** uses `LOANLENS_BOOTSTRAP_MANAGER_EMAIL` and `_PASSWORD`, checked once per database per process when a page loads, and only if no manager exists.
  - The bootstrapped manager must change the password at first sign-in, because it sat in the environment.
  - Every outcome logs a warning without the email or password: created ("remove the settings now"), ignored because a manager exists, only one variable set, or the password failed the policy.
- **Manager actions:**
  - New managers created on the Users page must change their temporary password.
  - A manager cannot change their own status or set their own temporary password; they use the Account page.
  - The last active manager cannot delete their own account. Since managers cannot deactivate themselves, at least one active manager always remains.
- **Temporary password:** setting one also clears a lockout. It is the documented way to reset a forgotten password.

### D-080 Streamlit pages
- **New pages:** `0_Sign_In.py` (tabs Sign in and Create account, forms that clear on submit), `5_Users.py` (managers) and `6_Account.py` (change password, delete account with a checkbox plus password confirmation). The existing page file names are unchanged, so links and tests keep working.
- **Access:**
  - Home, Sign in and About are public.
  - Check My Eligibility and Account need any signed-in user; Bulk Check, Analytics and Users need a manager.
  - A user who must change their password is sent to Account first.
  - Missing access shows a plain message and a link to Sign in, never a stack trace.
- **Sidebar:** shows the signed-in email (Markdown-escaped, so user text is shown literally), the role and a Sign out button. Signing out clears the whole session state, including any Bulk Check results.
- **Links:** `ui_common.page_link` falls back to plain text when a page cannot be linked (for example a page run on its own in a test).
- **Privacy note:** "Nothing you enter on this page is stored or logged" stays on Check My Eligibility, because form inputs are still not stored in this milestone. Account data is described on the Sign in page and in the docs.

### D-081 Old shared-password gate removed
- **Removed:** `src/loanlens/access.py`, the "Bank manager mode" toggle and password box, `LOANLENS_MANAGER_PASSWORD`, the Streamlit-secret fallback, the `streamlit_secrets` helper, the demo password `loanlens-demo` and their tests. Every doc mention is gone.
- **Resolves** the Milestone 1 suggestion about the default demo password.
- `.streamlit/secrets.toml` stays gitignored, and `test_no_secret_committed` still checks it.

### D-082 Tests
- **Isolation:** every test gets its own empty SQLite database. The autouse fixture in `tests/conftest.py` redirects `storage.db_path`, so accounts and batch summaries both go to `tmp_path`. It also clears every account-related environment variable and disposes cached engines afterwards. A developer's database is never touched.
- **Generated secrets:** the signing key and test passwords are generated at run time (`secrets.token_urlsafe`); none are written in the repository.
- **Speed:** tests use cheap argon2id parameters. One test reloads the shipped module and checks that production uses argon2id with the library defaults.
- **Helpers:** `tests/app_support.py` creates an account and opens a page already signed in with the role it needs. Existing page tests now use it instead of the old gate.
- **New files:**
  - `tests/test_auth.py` (82 tests): service layer, settings, tokens, bootstrap, CLI and the no-secrets-at-rest check.
  - `tests/test_auth_pages.py` (41 tests): AppTest flows.
- `tests/test_db.py`: migration head `0002_auth`, the new tables in the CLI round trip, and a test that uses the real `storage.db_path`.

### D-083 Documentation, screenshots and packaging
- **Docs:** README (accounts and roles, quick start step 3, pages, security, structure, limitations), USER_GUIDE (new Part 0 on accounts, the Users page and the new messages) and PROJECT_EXPLAINED (Part 1 "Signing in" in plain words; Part 2 section 12 "Accounts and roles", with Security renumbered). Also `.env.example` (names only) and `requirements.txt` (argon2-cffi 25.1.0 and PyJWT 2.10.1, both on the allowed list).
- **Screenshots:** four new ones, 09 Sign in, 10 Users, 11 Account and 12 applicant blocked, and all earlier ones retaken.
  - The run used a throwaway database in the scratchpad, a generated signing key and generated passwords.
  - It signed up an applicant, checked the three examples and showed the applicant blocked from Bulk Check.
  - It then signed in as the bootstrapped manager, completed the forced password change, uploaded the 1,000-row file and opened Analytics, Users and About.
  - The server log had no errors and contained none of the passwords.
- **Packaging:** `pyproject.toml` now lists `auth/common_passwords.txt` and the Alembic template as package data, so a non-editable install has them.

## Suggestions
- In the modelling phase, consider adding loan-to-income (and possibly EMI-to-income) as a model feature. It explains most of the gap between 98.2% and 99.6%.
- In the explainability phase, limit "what would change" to directions that make lending sense (raise CIBIL, lower the loan) and never suggest increasing the loan or shortening the term just because the synthetic data rewards it.
- Settle the EMI-to-income cap (D-012) with a lender's credit-policy team before building `rules.py`.
- In the app phase, display probabilities above 99% as ">99%" and below 1% as "<1%" (isotonic output reaches exactly 0 and 1), and show the model probability alongside any rule-based rejection with a clear "policy rule applied" label.
- In the batch phase, vectorise `decide()` (rules via `rule_pass_frame`, a single `predict_proba`, and SHAP on the whole batch) instead of calling it row by row. At about 16 ms per row, 1,000 rows would take about 16 s.
- Consider a co-applicant income field later; the dataset has none, so it was not modelled.
- For uploads above 50,000 rows, XGBoost could use more threads (`n_jobs`) at scoring time only; training stays single-threaded for determinism.
- Optional "Try an example" buttons on the customer page that load the six hypothetical examples, shown with the same [tick]/[cross] styling.
- Add a LICENSE file (for example MIT) so others know how they may reuse the code; the datasets keep their own licences.
- Add GitHub repository topics (streamlit, explainable-ai, credit-scoring, xgboost, shap) and a short description.
- Add a GitHub Actions workflow running `ruff` and the data-free part of `pytest` on each push.
- **Default demo password (resolved in Milestone 2, D-081):** CLAUDE.md section 14 now says "no secrets or default passwords in the repository", but `src/loanlens/access.py` still falls back to the documented local demo password `loanlens-demo`, and README, USER_GUIDE and the tests describe it. Removing it changes the Bulk Check gate's behaviour and was not part of Milestone 1, so it was left as is. Suggested: drop the fallback (require `LOANLENS_MANAGER_PASSWORD`, stored as an argon2id hash) in a later milestone.
- Run the PostgreSQL tests (`LOANLENS_TEST_POSTGRES_URL`) against a disposable database, for example a local Docker container once Docker's engine is running, or in CI.
- When another model version is activated, update the artifact lines in `.gitignore` (or move to a release-asset workflow for artifacts).
- Revoke open sessions when a password changes, for example with a per-user token version checked in `principal_from_token` (today a token stays valid until it expires unless the account is deactivated).
- When the shared service layer is built (Milestone 3), make batch scoring and analytics functions take a `Principal` and check the manager role there as well, not only in the pages.
- Rate-limit sign-up and sign-in per client, and consider a larger breached-password list; sign-up currently reveals whether an email is registered (D-076).
