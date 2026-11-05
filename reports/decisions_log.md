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

## Suggestions
- In the modelling phase, consider adding loan-to-income (and possibly EMI-to-income) as a model feature. It explains most of the gap between 98.2% and 99.6%.
- In the explainability phase, limit "what would change" to directions that make lending sense (raise CIBIL, lower the loan) and never suggest increasing the loan or shortening the term just because the synthetic data rewards it.
- Settle the EMI-to-income cap (D-012) with a lender's credit-policy team before building `rules.py`.
- In the app phase, display probabilities above 99% as ">99%" and below 1% as "<1%" (isotonic output reaches exactly 0 and 1), and show the model probability alongside any rule-based rejection with a clear "policy rule applied" label.
- In the batch phase, vectorise `decide()` (rules via `rule_pass_frame`, a single `predict_proba`, and SHAP on the whole batch) instead of calling it row by row. At about 16 ms per row, 1,000 rows would take about 16 s.
- Consider a co-applicant income field later; the dataset has none, so it was not modelled.
