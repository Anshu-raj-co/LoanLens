# LoanLens: Explainable Loan Pre-Eligibility & Risk Insights

LoanLens is a **pre-screening and decision-support prototype**, an independent proof of concept. It estimates whether a loan application is likely to be **approved or rejected**, shows how confident the model is, and explains **why** in plain language, including what would likely change the result.

> **Approval, not default.** LoanLens predicts the loan *approval decision* recorded in a public, **synthetic** dataset. It does **not** predict default (a disbursed loan that later goes unpaid, NPA / 90+ days overdue), because there is no repayment data. It is not a lending decision, no real customer or bank data is used, and no real-world accuracy is claimed. Every policy threshold is a placeholder, illustrative until replaced by a lender's real credit policy.

![Check My Eligibility: rejected and borderline result](reports/screenshots/04_eligibility_rejected_borderline.png)

## Contents

- [Quick start (fresh clone)](#quick-start-fresh-clone)
- [Data](#data)
- [The pages](#the-pages)
- [How a decision is made](#how-a-decision-is-made)
- [Bank manager password (prototype gate)](#bank-manager-password-prototype-gate)
- [Project structure](#project-structure)
- [Development](#development)
- [Limitations](#limitations)
- [Future work](#future-work)

## Quick start (fresh clone)

Requires **Python 3.11** (Windows commands shown; on macOS/Linux use `python3.11 -m venv .venv` and `source .venv/bin/activate`).

**1. Get the code and put the data in place.** Download the three CSV files listed under [Data](#data) and save them in `data/raw/` with exactly these names:

```
data/raw/loan_approval_dataset.csv   # primary: powers the app (required)
data/raw/bank_loan_data.csv          # benchmark notebook only
data/raw/loan_data.csv               # sanity check only
```

**2. Three commands to install and run:**

```bash
py -3.11 -m venv .venv && .venv\Scripts\activate     # 1. create and activate the virtual environment
pip install -r requirements.txt                       # 2. install pinned packages + LoanLens itself
streamlit run app/Home.py                             # 3. start the app (http://localhost:8501)
```

**Before the first run, build the model once** (the `models/` folder is not committed):

```bash
python -m loanlens.model
```

This cleans `data/raw/loan_approval_dataset.csv` into `data/processed/`, cross-validates the final model and saves `models/loanlens_model.joblib` (about a minute). If you start the app without it, every page shows a friendly message telling you to run this command; nothing crashes.

This whole sequence was verified from a fresh `git clone` in an empty folder (see `reports/progress.md`, Phase 10).

## Data

The CSV files are third-party Kaggle datasets. They are **not committed** to this repository (`data/raw/` and `data/processed/` are gitignored), so the licence terms of each source apply. Download them from:

| File in `data/raw/` | Source | Role |
|---|---|---|
| `loan_approval_dataset.csv` | Kaggle, "Loan-Approval-Prediction-Dataset" (Archit Sharma): https://www.kaggle.com/datasets/architsharma01/loan-approval-prediction-dataset | **Primary.** 4,269 rows, INR, CIBIL 300-900. Powers the app. |
| `bank_loan_data.csv` | Kaggle, "Loan Approval Classification Data" (Ta-wei Lo): https://www.kaggle.com/datasets/taweilo/loan-approval-classification-data (downloaded as `loan_data.csv`; rename it) | **Benchmark only** (`notebooks/04_benchmark_bank_loan_data.ipynb`). Never merged with the primary data. |
| `loan_data.csv` | A 381-row copy of the widely shared "Loan Prediction" practice dataset (columns `Loan_ID ... Loan_Status`). The exact Kaggle page it came from was not recorded; see `reports/decisions_log.md`. | Sanity check only, otherwise unused. |

Please check each page's licence before redistributing the files. The 1,000-row test file `tests/fixtures/batch_1000.csv` is a small sample of the primary dataset used only by the tests.

## The pages

| Page | What it does |
|---|---|
| **Home** | Purpose, the "approval, not default" disclaimer, the placeholder-thresholds notice and links to every page. |
| **Check My Eligibility** (customers) | An 8-field form with ranges, hints and Indian-grouped amounts (e.g. "= Rs 1,50,00,000"). Returns a green ✅ Approved or red ❌ Rejected banner with the likelihood (e.g. "96% - Very likely", labelled "model score on synthetic data - indicative only"), an amber borderline pill when relevant, reason cards, "what would likely change this", positive factors, warnings and the policy checks. **Nothing entered is stored or logged.** |
| **Bulk Check** (bank staff) | Behind the manager gate. Download the CSV template, upload up to **50,000 rows**, see invalid rows listed and skipped (with spreadsheet row numbers), a progress bar, summary cards (total, approved, rejected, borderline, skipped, approval rate), top rejection reasons, a results table with status / borderline / search filters, and a CSV download. Only an **anonymised summary** of each batch is saved (`data/loanlens.sqlite`). Measured: 1,000 rows about 0.7 s, 50,000 rows about 16-32 s. |
| **Analytics** | Approval rate by CIBIL band, loan term and loan size in the training data; what drives the model (mean absolute SHAP share); and the latest batch summary. |
| **About** | The framing, data source, model metrics, every current policy value with its enforce setting, how the borderline flag works, the benchmark summary and the full model card. |

| | |
|---|---|
| ![Home](reports/screenshots/01_home.png) | ![Approved result](reports/screenshots/03_eligibility_approved.png) |
| ![Bulk Check](reports/screenshots/05_bulk_check.png) | ![Analytics](reports/screenshots/06_analytics.png) |

More screenshots: `reports/screenshots/` (form, About page). Customer and bank-manager instructions: [USER_GUIDE.md](USER_GUIDE.md).

## How a decision is made

Single source of truth: `src/loanlens/decision.py`. Customer mode and Bulk Check use the same vectorised core, so they always agree. For every application, in order:

1. **Validate** the input (Pydantic). Missing or impossible values return a clear message and no decision.
2. **Policy rules** from `config/policy.yaml`. Each rule has a `value` and an `enforce` flag:
   - *Enforced* rules (minimum CIBIL 550, loan at most 4.0x annual income, loan at most 1.5x total assets, term 2 to 20 years): a failure means **Rejected**, whatever the model says, with that rule as the reason.
   - *Advisory* rules (EMI at most 50% of monthly income, using an **assumed 10% interest rate** because the data has no rate): a failure only adds a warning.
3. **Model**: a calibrated XGBoost probability `p` (features: CIBIL, loan term, loan-to-income, income, total assets; monotone so a higher CIBIL never lowers, and a bigger loan never raises, the score). `p >= 0.5` means Approved.
4. **Borderline flag** ("manual review recommended"): when `p` is between 40% and 60% with no enforced rule failed, or when the CIBIL score is within 25 points of the minimum and no *other* enforced rule failed. The status stays Approved or Rejected.
5. **Reasons**: rule failures first, then the strongest negative model drivers (SHAP) in plain English with "your value" vs a benchmark; at most 5. Every rejection has at least one reason. Approvals get positive factors.
6. **What would change**: the smallest CIBIL increase or loan reduction that would likely flip a rejection ("would likely", never "guaranteed"). It never suggests a shorter term or a bigger loan.

The displayed score never reads 0% or 100% (">99%" / "<1%") and carries a verbal band (Very likely, Likely, Borderline, Unlikely, Very unlikely).

## Bank manager password (prototype gate)

Bulk Check sits behind a sidebar **Bank manager mode** switch plus a password. **This is a prototype gate, not real authentication**: there are no user accounts, roles, lockouts or audit trail.

The password is read, in order, from:

1. the environment variable `LOANLENS_MANAGER_PASSWORD`, or
2. the Streamlit secret `manager_password` in `.streamlit/secrets.toml` (gitignored; never commit it):

   ```toml
   manager_password = "choose-a-password"
   ```

3. otherwise the **local demo default `loanlens-demo`**, and the sidebar says that the demo password is in use. Set your own password before showing the app to anyone else.

No other password or secret exists in the code or the repository.

## Project structure

```
CLAUDE.md                 project brief and working agreement
README.md, USER_GUIDE.md
requirements.txt          pinned packages (+ `-e .` for the loanlens package)
pyproject.toml            package, ruff and pytest settings
config/policy.yaml        every threshold, enforce flag and display setting (all PLACEHOLDERS)
.streamlit/config.toml    light theme; stack traces hidden from users
data/raw/                 the three Kaggle CSVs (not committed)
data/processed/           cleaned primary dataset (built by `python -m loanlens.model`)
models/                   saved model artifact (built, not committed)
notebooks/                01_audit, 02_eda, 03_modelling, 04_benchmark_bank_loan_data
src/loanlens/
  schema.py               Pydantic input/output models, friendly validation messages
  cleaning.py             cleaning of the primary dataset
  features.py             EMI, ratios, total assets, CIBIL bands
  rules.py                policy rules (enforced vs advisory)
  model.py                train, cross-validate, calibrate, save, load
  explain.py              SHAP reasons, positive factors, what-would-change search
  decision.py             orchestrates everything (single source of truth)
  batch.py                CSV in, validation, scoring, results out
  storage.py              SQLite, anonymised batch summaries only
  presentation.py         display text and views used by the pages
  formatting.py           Indian digit grouping, score display
  theme.py                every colour, the app CSS and the Plotly template
  charts.py               Plotly charts (Analytics page and notebooks)
  access.py               the prototype manager gate
  config.py, examples.py  policy loading; six hypothetical example applicants
app/                      Streamlit pages (layout only; all logic is in src/loanlens)
reports/                  model card, benchmark, decisions log, progress, examples, screenshots
scripts/                  example_decisions.py
tests/                    pytest suite (unit tests and headless page tests)
```

## Development

```bash
python -m loanlens.model             # (re)build cleaned data and the model
python -m loanlens.rules             # write reports/rules_vs_labels.md
python scripts/example_decisions.py  # write reports/example_decisions.md
ruff check .
pytest                               # 281 tests
pytest --cov=loanlens                # coverage of src/loanlens (98%)
```

Tests that need the dataset or model skip themselves if `data/raw/` is empty.

## Limitations

- **Synthetic data.** The patterns reflect how the Kaggle dataset was generated, not any real lender's policy or real borrowers. Scores are near-perfect for that reason, not because the problem is easy in reality.
- **CIBIL dominates.** About 99% of applicants above CIBIL 550 are approved and about 10% at or below; CIBIL has 57% of the model's influence. The second feature, loan term, matters only because of a synthetic quirk (short-term, low-CIBIL approvals), and "what would change" never suggests changing the term.
- **Approval, not default.** Nothing here measures repayment risk.
- **Placeholder thresholds.** Every value in `config/policy.yaml` (minimum CIBIL, loan-to-income, loan-to-assets, term limits, EMI cap, borderline band and margin, likelihood bands, which rules are enforced) is illustrative until replaced by a lender's real credit policy.
- **Assumed interest rate.** The data has no rate or existing EMIs, so EMI uses an assumed 10% a year and the EMI-to-income rule is advisory only.
- **Narrow training ranges.** Loan-to-income only spans 1.5 to 4.0 in the data; inputs outside the training ranges get a warning.
- **Prototype gate.** The manager password is not real authentication.

## Future work

- **Real repayment data**, so that default risk could be studied.
- **Real policy thresholds** (and enforce settings) from a lender, replacing every placeholder.
- **Authentication** for bank staff (accounts, roles, audit log) instead of the prototype gate.
- **A default-risk model**, as a separate model with its own target, once repayment outcomes exist.
- **Power BI dashboard** fed by exported, dashboard-ready CSVs.
- Collecting the fields the benchmark shows are missing: previous defaults, employment experience, home ownership, loan purpose, offered interest rate and existing EMIs (`reports/benchmark.md`).
