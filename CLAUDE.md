# LoanLens: Explainable Loan Pre-Eligibility & Risk Insights

Independent proof of concept by Anshu Raj, to be pitched to lenders. It is not affiliated with or endorsed by any bank. Read this file fully before every task.

## 1. What we are building

A Streamlit app that predicts whether a loan application is likely to be **approved or rejected**, and explains **why**.

Two user modes:

1. **Customer mode**: a person enters their own details in a form and gets Approved / Rejected, an approval probability, and, if rejected, plain-language reasons plus what would change the outcome.
2. **Bank manager mode**: upload a CSV with many applicants. The app validates it, scores every row, and returns a table with Approved / Rejected, probability and reasons per applicant. Results are downloadable as CSV.

Plus an **Analytics** page (approval trends, feature importance, batch summary).

## 2. Honest framing (must appear in the UI and README)

- This is a **pre-screening and decision-support prototype**. It is not a final lending decision.
- The target is **approval decision (approved / rejected)**, NOT default. Default means a disbursed loan that later went unpaid (NPA, 90+ days overdue). We have no repayment data. Never write "predicts default".
- Training data is **synthetic / public** (Kaggle). Do not claim real-world accuracy.
- Never use real customer data. Never commit any bank data.

## 3. Data

Files live in `data/raw/` (never modify raw files):

| File | Role |
|---|---|
| `loan_approval_dataset.csv` | **Primary.** 4,269 rows, INR, CIBIL 300-900. Powers the app. |
| `bank_loan_data.csv` | **Secondary benchmark.** ~45k rows. Used only in the benchmark notebook, never merged with primary. |
| `loan_data.csv` | 381 rows, many nulls. Sanity check only, otherwise unused. |

Known facts about the primary dataset (verified):
- Columns/values have stray leading spaces. Strip them.
- Columns: `loan_id, no_of_dependents, education, self_employed, income_annum, loan_amount, loan_term (years), cibil_score, residential_assets_value, commercial_assets_value, luxury_assets_value, bank_asset_value, loan_status`.
- Target: `loan_status` (Approved=1, Rejected=0). About 62% approved.
- 28 rows have negative `residential_assets_value`. Treat as data errors and document the handling.
- **CIBIL dominates**: approval is about 99% above 550 and about 10% at or below 550. A CIBIL-only tree gets about 95% accuracy. A random forest gets about 98.2% on the raw features and about 99.6% once loan-to-income is added (5-fold CV; corrected from an earlier 99.9% claim, see decisions_log D-010).
- Education, self-employed and dependents show **no effect** on approval.
- Almost all low-CIBIL approvals have loan_term of 2 or 4 years, a quirk of the synthetic data. Document it. Do not present it as real policy.
- Second quirk: among low-CIBIL (<= 550) applicants with 2 or 4 year loans, approval *rises* with loan-to-income (none approved at or below 2.5, 96-100% approved above 3.0). This is a synthetic artefact, the opposite of sound lending logic. Never present it as advice (see decisions_log D-011).
- Loan-to-income only ranges 1.5 to 4.0, so predictions outside the training range are unreliable. Warn the user.
- **Never use gender or marital status** as model features.

## 4. Tech stack

Python 3.11, pandas, numpy, scikit-learn, XGBoost, SHAP, Streamlit, Plotly, Pydantic v2, SQLite (stdlib `sqlite3`), PyYAML, pytest, ruff, Git. Jupyter for EDA notebooks. Pin versions in `requirements.txt`.

## 5. Decision logic (single source of truth: `src/loanlens/decision.py`)

For every application, in order:

1. **Validate** input (Pydantic). Invalid input returns a clear error and no decision.
2. **Policy rules** from `config/policy.yaml`. Any hard-rule failure means **Rejected**, with that rule as the reason. Rules: `min_cibil`, `max_emi_to_income`, `max_loan_to_income`, `max_loan_to_assets`, min and max loan term.
   - EMI uses the standard formula with an **assumed annual interest rate** from config (placeholder, because the dataset has no rate).
   - Thresholds are placeholders, illustrative until replaced by a lender's real credit policy. Mark them clearly in the config file.
3. **Model**: calibrated probability `p`. If `p >= approval_threshold` (default 0.5) then Approved, else Rejected.
4. **Borderline flag**: if `p` is within the configured band (default 0.4 to 0.6), set `borderline=True` ("manual review recommended"). The status is still Approved or Rejected.
5. **Reasons** (see section 6).

The output object (`DecisionResult`) always contains: `status`, `probability`, `borderline`, `reasons[]`, `what_would_change[]`, `rule_results[]`, `warnings[]`.

## 6. Reasons and explainability

Every Rejected result must have at least one reason. Reasons come from two sources, merged and ranked (max 5):

- **Rule failures**: explicit and exact, e.g. "CIBIL score 480 is below the minimum 650."
- **Model drivers**: top negative SHAP contributions, translated to plain language with the applicant's actual value vs the benchmark.

Each reason has: `code`, `message` (plain English, no jargon), `your_value`, `benchmark`, `suggestion`.

**"What would change this"**: for a rejection, search one feature at a time (CIBIL, loan amount, loan term) for the smallest change that flips the decision. Present as "Increasing CIBIL to about X, or reducing the loan to about Y, would likely change the result." Say "likely", not "guaranteed".

Approved applicants also get the top positive factors.

## 7. App pages (`app/`)

Multi-page Streamlit app:

1. **Home**: purpose, disclaimer, navigation.
2. **Check My Eligibility** (customer): form with the fields the model needs, input hints and ranges, a Check button. Shows a status badge, probability, reasons, and what would change. **Do not store personal data in this mode.** Show "Prototype, not a lending decision".
3. **Bulk Check** (bank manager): a downloadable CSV template, an upload widget, schema validation with a clear row-level error report (bad rows are flagged and skipped, never crash the app), progress indicator, results table (filter by status, borderline and search), a summary (counts, approval rate, top rejection reasons), and download results as CSV. Accept a reasonable max size (about 50k rows). Store only anonymised batch summaries in SQLite (no names or IDs unless explicitly enabled in config).
4. **Analytics**: Plotly charts (approval by CIBIL band, by loan size and term, feature importance, last batch summary).
5. **About / Model Card**: data source, metrics, limitations, assumptions.

Bank manager mode is simple password-gated or a sidebar toggle. This is a prototype. Do not build real authentication, but note it as future work.

CSV column mapping: if headers are slightly different (case or spaces), normalise them. If required columns are missing, show exactly which.

## 8. Project structure

```
loanlens/
  CLAUDE.md
  README.md
  requirements.txt
  config/policy.yaml
  data/raw/            # never edit; gitignored if large
  data/processed/
  notebooks/           # 01_audit, 02_eda, 03_modelling, 04_benchmark_bank_loan_data
  src/loanlens/
    schema.py          # Pydantic models, column maps
    cleaning.py
    features.py        # EMI, ratios, total assets
    rules.py
    model.py           # train, calibrate, save, load
    explain.py         # SHAP + reason translation + what-would-change
    decision.py        # orchestrates everything
    batch.py           # CSV in, results out
    storage.py         # SQLite
  app/
    Home.py
    pages/
  models/              # saved model artifacts
  reports/
  tests/
```

## 9. Modelling rules

- Compare logistic regression, random forest, XGBoost with stratified 5-fold CV. Metrics: ROC-AUC, PR-AUC, precision, recall, F1, plus a confusion matrix. Not just accuracy.
- Calibrate probabilities (isotonic or Platt) and show a calibration curve.
- Because scores are near-perfect, explicitly check for leakage and report it. Explain in the model card that CIBIL dominates.
- Prefer the simplest model that is within about 1% of the best. State the choice and why.
- Fix random seeds. Save the model together with its feature list and a version.
- Train/validation split happens before any fitting of scalers or encoders (use sklearn Pipelines).

## 10. Coding conventions

- Type hints, docstrings on public functions, small modules, no business logic inside Streamlit files (the app only calls `src/loanlens`).
- All thresholds come from `config/policy.yaml`, never hard-coded.
- Amounts are in INR. Display with Indian grouping where practical (e.g. 12,50,000).
- Friendly error messages. Never show raw stack traces to the user.
- Tests with pytest: cleaning, EMI calculation, each rule, decision orchestration, batch validation (good CSV, bad CSV, missing columns, empty file), reasons present on every rejection.
- Run `ruff` and `pytest` before declaring a task done.
- Commit after each completed phase with a clear message.

## 11. Definition of done

- Customer form returns a decision with reasons in under 2 seconds.
- Batch of 1,000 rows scores in a few seconds, with per-row reasons.
- Every Rejected row has at least one non-empty reason.
- Bad input never crashes the app.
- README has setup, run instructions, screenshots, limitations.
- Model card states data source, metrics, and the "approval not default" framing.

## 12. Out of scope (for now)

Power BI (last phase, optional: export dashboard-ready CSVs only), real authentication, real bank data, deployment, default prediction, using gender or marital status.

## 13. Working agreement

- This file is background context for the whole project. Build only what the current prompt asks for. Do not create code, pages, notebooks, stubs or features that belong to phases not listed in the current prompt.
- You have permission to create, edit, rename and delete files inside the project directory, and to run python, pytest, ruff, streamlit, jupyter and git for this work. Do not touch anything outside the project directory.
- Make reasonable decisions yourself and log them in `reports/decisions_log.md` (what you found, what you chose, why). Do not stop to ask unless progress is genuinely impossible.
- If something in the data contradicts this file, use the corrected fact, log it, and continue.
- Never fabricate metrics. Report what the code actually outputs.
- Suggested extras go in `reports/decisions_log.md` under "Suggestions", not into the code.
