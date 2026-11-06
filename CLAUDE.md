# LoanLens: Explainable Loan Pre-Eligibility Platform

Independent proof of concept by Anshu Raj (GitHub: Anshu-raj-co), built to be demonstrated and pitched to lenders. Read this file fully before every task. It covers the whole project: what was built in v1.0 (sections 1 to 13) and the platform phase now underway (sections 14 and 15).

## 1. What this project is

LoanLens is a pre-screening and decision-support tool. It estimates whether a loan application is likely to be approved or rejected, shows how confident the model is, and explains the result in plain language, including what would likely change it.

Users (updated for v2.0):
1. Applicants: sign up and sign in, check their own eligibility, see reasons and "what would likely change this", and view their own history.
2. Bank managers (staff of a lender): sign in, upload a CSV or Parquet file of many applicants, get Approved or Rejected with reasons for each, download results, see analytics, the audit trail and user management.
3. Systems: a REST API exposes the same decision engine (platform phase).

## 2. Honest framing (never weaken)

- The project is an independent proof of concept. It was not built for, with or by any bank. Never imply affiliation or endorsement.
- It predicts the approval decision recorded in a public synthetic dataset. It does NOT predict default (a disbursed loan that later goes unpaid, 90+ days overdue). There is no repayment data. Never write "predicts default".
- The data is synthetic and public. No real customer or lender data is used. No real-world accuracy is claimed.
- Every policy threshold and the assumed interest rate are illustrative placeholders that a lender would replace with its own board-approved credit policy. Do not claim the checks are prescribed, approved or endorsed by any regulator, and do not claim regulatory compliance.
- Policy profiles (personal, home, vehicle) change rules and assumptions only. They share one trained model.
- Wording rule for all files: no emoji; do not name any bank, employer or other institution, and do not claim any affiliation. The only author name is Anshu Raj.

## 3. Data

Files live in `data/raw/` and are never modified or committed:

| File | Role |
|---|---|
| `loan_approval_dataset.csv` | Primary. 4,269 rows, INR, CIBIL 300 to 900. Powers the app and the model. Credited in the README to its Kaggle source. |
| `bank_loan_data.csv` | Benchmark only. 45,000 rows. Source: https://www.kaggle.com/datasets/udaymalviya/bank-loan-data . Never merged with the primary data. |
| `loan_data.csv` | 381 rows, many nulls, source not verified. Sanity check only. |

Verified facts about the primary dataset:
- Column names and values have stray leading spaces; strip them.
- Columns: loan_id, no_of_dependents, education, self_employed, income_annum, loan_amount, loan_term (years), cibil_score, residential_assets_value, commercial_assets_value, luxury_assets_value, bank_asset_value, loan_status.
- Target: loan_status (Approved = 1, Rejected = 0), about 62% approved.
- 28 rows have negative residential_assets_value, all exactly -1,00,000. Default treatment: set to 0 (configurable: set to 0, drop, or mark missing).
- CIBIL dominates: about 99.5% approved above 550 and about 10.6% at or below. A CIBIL-only tree scores about 95.4%. A random forest scores 98.2% on raw features and 99.6% when loan-to-income is added.
- Education, self-employment and dependents have no effect on approval.
- Quirk of the synthetic data: among low-CIBIL applicants with 2 or 4 year loans, approval rises with loan-to-income (none approved at or below 2.5, 96 to 100% above 3.0). The product must never exploit or suggest this ("borrow more" or "take a shorter loan").
- Loan-to-income only spans about 1.5 to 4.0 in the data; inputs outside the training ranges get a warning.
- Never use gender, marital status, age or any other sensitive attribute as a model feature.

Benchmark dataset (bank_loan_data.csv): no missing values, 22.2% positive class, amounts that look like US dollars, credit scores 390 to 850. A previous default on file fully determines the negative class, and credit score alone scores about 0.50 ROC-AUC. The Kaggle page describes loan_status as repaid versus defaulted, so its label meaning is ambiguous; it is used for comparison only and documented with that caution (reports/benchmark.md). Gender and age were excluded from its models.

## 4. Tech stack

v1.0: Python 3.11, pandas, numpy, scikit-learn, XGBoost, SHAP, Streamlit, Plotly, Pydantic v2, SQLite (stdlib), PyYAML, pytest, ruff, Jupyter, Playwright (screenshots, dev only), Git. Pin versions in requirements.txt.

Platform phase (v2.0), the only allowed new dependencies, pinned: SQLAlchemy 2.x, Alembic, psycopg (binary), FastAPI, uvicorn, python-multipart, argon2-cffi, PyJWT, pyarrow, psutil, httpx (tests), locust (dev only). No Redis, Celery, Kubernetes, message queues or cloud SDKs.

## 5. Decision logic (single source of truth: `src/loanlens/decision.py`)

For every application, in order:
1. Validate the input with Pydantic. Invalid input returns plain-English errors and no decision.
2. Apply policy rules from the selected policy profile. Each rule has a value and an enforce flag. A failed enforced rule means Rejected, whatever the model says (the model can never approve an applicant who fails an enforced rule). A failed advisory rule only adds a warning.
3. Model: calibrated approval probability p. Approved if p is at least approval_threshold (default 0.5).
4. Borderline flag ("manual review recommended"): raised when p is inside the borderline band and no enforced rule failed, or when CIBIL is within borderline_cibil_margin points of the enforced minimum and no other enforced rule failed. The status stays Approved or Rejected.
5. Reasons, positive factors and "what would change".

Current placeholder values (personal profile): minimum CIBIL 550 (enforced), loan at most 4.0 times annual income (enforced), loan at most 1.5 times total assets (enforced), term 2 to 20 years (enforced), EMI at most 50% of monthly income (advisory only, because enforcing it would reject about 47% of applicants who were approved), assumed interest rate 10% a year, approval threshold 0.5, borderline band 0.4 to 0.6, CIBIL margin 25 points, likelihood bands 85, 65, 35 and 15 percent.

DecisionResult always contains: status, probability, likelihood band, borderline, reasons, positive_factors, what_would_change, rule_results, warnings, model_version, and (updated for v2.0) profile, policy_version and policy_hash. The displayed probability never reads 0% or 100% (use ">99%" and "<1%").

One vectorised core (decide_many) serves single and batch modes, so an applicant always gets an identical result in both.

## 6. Reasons and explainability

- Every Rejected result has at least one reason; Approved results carry no rejection reasons and get positive factors.
- Reasons merge rule failures (exact, for example "CIBIL score 480 is below the minimum of 550") with the strongest negative SHAP drivers in plain English (your value versus a benchmark and a suggestion). At most 5.
- Loan term is never given as a reason, even though the model uses it.
- "What would change this": one-feature-at-a-time search, only CIBIL increase or loan reduction. Worded "would likely", never a guarantee. It never suggests borrowing more or changing the term, and tests enforce this.

## 7. The application (updated for v2.0)

Streamlit pages in `app/` contain layout only; all logic is in `src/loanlens/`:
- Home (public): purpose, navigation, the illustrative-placeholders notice. No yellow disclaimer box.
- Sign in (public): tabs for Sign in and Create account (applicants only).
- Check My Eligibility (any signed-in user): form with ranges, hints, Indian digit grouping, a Loan type selector; result banner, likelihood band, borderline pill, reason cards, what would change, positive factors, warnings, policy checks.
- My History (applicant): own past checks with CSV export.
- Account (any signed-in user): change password, delete account.
- Bulk Check (manager): upload CSV or Parquet, choose loan type, background job with progress, job list, downloadable results and errors files. Header aliases accepted; invalid rows are listed with row numbers and skipped, never crash the app; blank asset cells are errors, not zeros.
- Analytics (manager): approval patterns, model drivers, latest batch summary.
- Audit (manager): filterable decision audit with CSV export.
- Users (manager): list users, create managers, deactivate or reactivate, set a temporary password.
- About (public): framing, data source, metrics, active model version, every policy profile's values and enforce settings, borderline explanation, benchmark summary, model card.

UI rules: white background, blue brand colour; every colour lives in `src/loanlens/theme.py` (primary blue #2E74E9, indigo #5271FF, navy text #0F1B3D, soft panel #F4F7FE, approved green #1E9E5A, rejected red #D93636, borderline amber #B7791F). Approved is always green and Rejected always red, in banners, table cells and charts, always together with plain words. NO emoji anywhere in the app, docs or reports. The header strip shows only the large title "LoanLens". Never show raw stack traces to users.

## 8. Project structure

Existing (v1.0):
```
CLAUDE.md, README.md, PROJECT_EXPLAINED.md, USER_GUIDE.md
requirements.txt, requirements-dev.txt, pyproject.toml
config/policies/ personal.yaml (default), home.yaml, vehicle.yaml
.streamlit/config.toml
alembic.ini, .env.example
data/raw/ (not committed), data/processed/ (not committed)
models/ registry.json plus versioned artifacts (loanlens_model_1.0.0.joblib is active and committed)
notebooks/ 01_audit, 02_eda, 03_modelling, 04_benchmark_bank_loan_data
src/loanlens/ schema, cleaning, features, rules, model, registry, explain, decision,
              batch, storage, presentation, formatting, theme, charts,
              auth/ (service, passwords, tokens, settings, cli), config, examples,
              db/ (engine, models, Alembic migrations in db/migrations/)
app/ Home.py, ui_common.py, pages/
reports/ model_card, benchmark, rules_vs_labels, example_decisions,
         progress, decisions_log, screenshots/
scripts/ example_decisions.py, make_batch_fixture.py
tests/ (pytest suite, fixtures/)
```
Planned for v2.0 (create only when the milestone builds them): `src/loanlens/api/`, `src/loanlens/worker.py`, `scripts/benchmark_batch.py`, `scripts/build_hosted_assets.py`, `tests/load/locustfile.py`, `reports/performance.md`, `reports/load_test.md`, Dockerfile, docker-compose.yml, `.dockerignore`. (Already built in M1: `src/loanlens/db/`, `src/loanlens/registry.py`, `config/policies/`, `models/registry.json`, Alembic migrations, `.env.example`. Built in M2: `src/loanlens/auth/`, the Sign in, Users and Account pages, Alembic revision `0002_auth`.)

## 9. Modelling rules (as built, do not change without being asked)

- Final model: XGBoost with probability calibration, five features (CIBIL, loan term, loan-to-income, income, total assets), monotone constraints (higher CIBIL never lowers the approval chance; higher loan-to-income never raises it). Raw loan amount is not a feature, because the model otherwise rebuilds the ratio from it and the quirk returns.
- Stratified 5-fold cross-validation inside sklearn Pipelines, fixed seed 42. Cross-validated results: ROC-AUC 0.9942, PR-AUC 0.9946, precision 0.953, recall 0.976, F1 0.964, accuracy 0.955. Logistic regression (ROC-AUC 0.969) fell more than 1% behind; XGBoost and random forest tied and XGBoost is about ten times smaller.
- Ablations (unconstrained XGBoost, ROC-AUC): all features 0.9992, CIBIL only 0.960, without CIBIL 0.584, without loan term 0.982, without loan-to-income 0.995, shuffled labels 0.499 (no leakage). CIBIL carries about 74% of importance by one measure and 57% by mean absolute SHAP; one method is the headline everywhere with the difference explained.
- Batch and single decisions must match exactly (status, probability within 1e-6, reasons).
- Train and validation splits happen before any fitting of scalers or encoders.

## 10. Coding conventions

- Type hints, docstrings on public functions, small modules, no business logic in Streamlit files.
- All thresholds come from the policy files, never hard-coded.
- Amounts are INR, shown with Indian grouping.
- Friendly error messages; no raw stack traces.
- pytest for everything new. Run ruff and pytest before declaring any task done. Commit after every completed task or milestone with a clear message.

## 11. Definition of done

v1.0 (done, tagged v1.0 and pushed): 281 tests passing with 98% coverage of src/loanlens, ruff clean, customer decision in about 16 ms, 1,000 rows scored in about 0.7 s, 10,000 in about 6 s, 50,000 in about 32 s, every rejected row has a reason, bad input never crashes the app, README, USER_GUIDE, PROJECT_EXPLAINED and model card written.

After M1: 376 tests passing, 3 PostgreSQL tests skipped unless LOANLENS_TEST_POSTGRES_URL is set, 98% coverage, ruff clean.

After M2: 499 tests passing, 3 PostgreSQL tests skipped unless LOANLENS_TEST_POSTGRES_URL is set, 99% coverage, ruff clean.

v2.0: see section 15. A milestone is done only when ruff is clean, all tests pass, the example decisions are unchanged under the default personal profile, docs are updated and the work is committed.

## 12. Out of scope

Real lender data, a default-risk model, email services (verification and password-reset emails), single sign-on, Kubernetes, message queues, cloud SDKs, Power BI (optional later, export CSVs only), using gender or any sensitive attribute.

## 13. Working agreement

- This file is background context for the whole project. Build only what the current prompt asks for. Do not create code, pages, notebooks, stubs or features that belong to other tasks.
- You have permission to create, edit, rename and delete files inside the project directory and to run python, pytest, ruff, streamlit and git (and the tools listed in section 14). Never touch anything outside the project directory. Never print or store credentials.
- Make reasonable decisions yourself and log them in `reports/decisions_log.md` (what you found, what you chose, why). Do not stop to ask unless progress is genuinely impossible.
- If the data or code contradicts this file, use the corrected fact, log it and continue.
- Never fabricate metrics. Report what the code actually outputs.
- Suggested extras go under "Suggestions" in `reports/decisions_log.md`, not into the code.

## 14. Platform phase rules (apply to every v2.0 task)

- Permissions: you may create, edit, rename and delete files inside the project directory, install packages into the project's venv, and run python, pytest, ruff, streamlit, uvicorn, alembic, locust, docker (if installed) and git. Never touch anything outside the project directory. Never print or store credentials.
- Working mode: work continuously without asking questions. Decide yourself and log decisions in reports/decisions_log.md. Stop only if progress is impossible.
- Scope: do only the tasks in the current prompt. Extras go under "Suggestions" in the decisions log.
- Identity and wording: no emoji anywhere (UI, docs, reports, code comments, commit messages). Do not name any bank, employer or other institution, and do not claim any affiliation. The only author name is Anshu Raj. Git identity: name "Anshu Raj", email "59351492+Anshu-raj-co@users.noreply.github.com".
- Behaviour: the decisions for the built-in example applicants under the default personal profile must stay identical unless a prompt says otherwise. At the end of every milestone ruff is clean and all tests pass. Add tests for all new code.
- Security: no secrets or default passwords in the repository. Configuration comes from environment variables; `.env.example` documents names only. Passwords are hashed with argon2id. Never log passwords, tokens or personal data. Use the ORM or parameterised queries only. Validate all inputs with Pydantic.
- Allowed new dependencies (pinned): SQLAlchemy 2.x, Alembic, psycopg (binary), FastAPI, uvicorn, python-multipart, argon2-cffi, PyJWT, pyarrow, psutil, httpx (tests), locust (dev only). No Redis, Celery, Kubernetes, queues or cloud SDKs.
- Honest numbers: every performance figure must be measured on this machine and reported with the hardware, row counts and date. Never estimate or extrapolate.
- Docs: every milestone updates README.md, PROJECT_EXPLAINED.md (the plain-English part stays jargon-free), USER_GUIDE.md, reports/progress.md and the decisions log. Commit at the end of each milestone. Push only when a prompt says so. Never force push.
- At the end of every milestone, update the Status column in section 15 and any older section that the milestone changed, in the same commit.

## 15. Platform phase (v2.0): goals, architecture and status

Goal: turn the prototype into a platform that can be demonstrated as deployable and pitched to lenders, while keeping the decision logic and the results for the built-in example applicants unchanged under the default personal profile.

| Milestone | Scope | Status |
|---|---|---|
| M1 | Database layer (SQLAlchemy, Alembic, PostgreSQL-ready); versioned policy profiles (personal, home, vehicle) with content hashes; model registry with versions, hashes and activation | Done (commit 199b235; 376 tests passed, 3 PostgreSQL tests skipped because no PostgreSQL server was available, 98% coverage; example decisions unchanged) |
| M2 | Authentication: applicant and manager roles, sign in and sign up, lockout, JWT sessions, account page, user management, remove the old shared password | Done (commit "Milestone 2: authentication and roles"; 499 tests passed, 3 PostgreSQL tests skipped, 99% coverage; example decisions unchanged) |
| M3 | Append-only decision audit trail (database triggers block update and delete), applicant history page, manager audit page, REST API under /v1 with health endpoints and OpenAPI docs | Not started |
| M4 | Chunked, memory-safe batch pipeline; Parquet; background jobs with an embedded or external worker; measured benchmarks at 100k, 500k and 1M rows (reports/performance.md); load test (reports/load_test.md) | Not started |
| M5 | Hosted-ready assets (no data folder needed), Docker and docker-compose, deployment docs, final documentation and screenshots, secret scan, release v2.0 and push | Not started |

Target architecture: Streamlit UI, FastAPI API and a worker all call one shared service layer and one decision core. The database is SQLite locally and PostgreSQL in Docker or hosted. Streamlit calls the service layer directly (documented choice); the API serves other systems.

Roles and data:
- Applicants sign themselves up. Managers cannot self-register; they are created from the command line (`python -m loanlens.auth create-manager`, password read with getpass, never as an argument), from a one-time bootstrap environment variable pair when no manager exists, or by another manager. No default or demo passwords anywhere.
- Passwords: argon2id, 10 to 128 characters, common-password check. Login errors are generic ("Incorrect email or password"); 5 failed attempts lock the account for 15 minutes (configurable). Sessions are signed JWTs (60 minutes, configurable) with the secret from LOANLENS_JWT_SECRET; in hosted or production mode a missing secret stops the app.
- Stored per user: email, password hash, role, timestamps, a separate random audit reference. Decision records store the model input fields, outcome, reasons, versions and the audit reference, never email or name. Deleting an account removes the user row so remaining records can no longer be linked to a person.
- Signed-in applicant checks are saved to their history and the audit trail. This replaces the v1.0 rule that customer mode stores nothing; all notices and docs must say so accurately.

Known limitations to state honestly: no email verification, no self-service password reset (a manager resets it), the Streamlit session ends on page refresh, policy profiles share one trained model, the data is synthetic, every threshold is an illustrative placeholder, and Docker or PostgreSQL results are only claimed if they were actually run.

Deployment (after M5, done by the owner): a free host such as Streamlit Community Cloud runs only the Streamlit app, has about 1 GB of memory, sleeps after inactivity, and needs an external PostgreSQL database for accounts. Set LOANLENS_HOSTED=1, secrets and a lower, measured upload-row cap. The API and worker are demonstrated through Docker locally or on a Docker-capable host. Never use real applicant data on a public host.

Release history: v1.0 tagged and pushed to https://github.com/Anshu-raj-co/LoanLens . v2.0 will be tagged and pushed at the end of M5.
