# Benchmark: primary dataset vs `bank_loan_data.csv`

All numbers come from `notebooks/04_benchmark_bank_loan_data.ipynb` (benchmark) and `notebooks/03_modelling.ipynb` / `reports/model_card.md` (primary). Stratified 5-fold cross-validation, seed 42, in both.

> Both datasets record a loan **approval decision**, not default, and both are synthetic. Nothing here is evidence of real-world accuracy. The benchmark dataset was **not merged** with the primary one, and the production model in `models/` was **not changed** (its file hash was checked before and after the notebook ran).

## The two datasets

| | Primary: `loan_approval_dataset.csv` | Benchmark: `bank_loan_data.csv` |
|---|---|---|
| Role | Powers the app | Benchmark only |
| Rows | 4,269 | 45,000 (44,993 after dropping 7 rows with age above 100) |
| Approved | 62% | 22% (exactly 10,000 of 45,000) |
| Missing values | none | none |
| Currency | INR (amounts in lakhs and crores) | Not stated; looks like USD (median income about 67,000, loans 500 to 35,000) |
| Credit score | CIBIL, 300 to 900 | FICO-style, 300 to 850 scale (390 to 850 observed) |
| Sensitive fields | none in the data | gender and age, both excluded from features |
| Signs of synthetic data | perfectly clean, even loan terms only, quirky low-CIBIL approvals | ages up to 144, 125 years of work experience, round 10,000 / 35,000 class split, identical approval rates across genders |

Scores, amounts and ratios are on different scales, so values cannot be compared one-to-one across the two datasets. A CIBIL of 650 and a FICO-style score of 650 do not mean the same thing.

## Which features matter

| | Primary | Benchmark |
|---|---|---|
| Dominant feature | **CIBIL score** | **Previous loan defaults on file** |
| Hard rule hidden in the data | Approval about 99% above CIBIL 550, about 10% at or below | 0% approval with a previous default, 45% without |
| Credit score | Decisive | **No effect**: about 21-23% approval in every score band; score alone ROC-AUC 0.50 (chance) |
| Mean absolute SHAP share of the top feature | CIBIL 57% | previous defaults 58% (credit score about 3%) |
| Other features | Loan term and loan-to-income (synthetic quirks) | Income, interest rate, loan purpose, home ownership, loan-to-income (each 7-8%) |
| Education | No effect | No effect |

**Ablations (XGBoost, ROC-AUC):**

| Benchmark | ROC-AUC | F1 |
|---|---|---|
| All features | 0.978 | 0.816 |
| Without credit score | 0.977 | 0.812 |
| Without previous defaults | 0.935 | 0.760 |
| Without credit score and previous defaults | 0.936 | 0.760 |
| Previous defaults only | 0.827 | 0.622 |
| Credit score only | 0.501 | 0.309 |

In the primary data the equivalent picture is the reverse: CIBIL alone reaches ROC-AUC 0.960 and removing it drops the model to 0.584 (model card, "CIBIL dominance and the leakage check").

## How performance differs

| Model (5-fold CV) | Primary ROC-AUC | Benchmark ROC-AUC | Benchmark PR-AUC | Benchmark F1 |
|---|---|---|---|---|
| Logistic regression | 0.969 | 0.954 | 0.854 | 0.741 |
| Random forest | 0.999 | 0.974 | 0.929 | 0.833 |
| XGBoost | 0.999 | 0.978 | 0.938 | 0.816 |

- Primary figures are the unconstrained models on the compact feature set; the production model (monotone-constrained, calibrated) has ROC-AUC 0.994 and F1 0.964.
- Benchmark models use class weights (`class_weight="balanced"`, or `scale_pos_weight` for XGBoost) because only 22% are approved. This lifts recall on the approved class (0.92 for XGBoost) at the cost of precision (0.73). Random forest has the best F1 (0.833) and precision (0.857).
- The benchmark is harder (no single field separates the classes as cleanly) but still scores far higher than real credit decisions usually allow, because one rule-like field (previous defaults) dominates.

## Cautions

- **Label direction in the benchmark:** approval *rises* with interest rate (about 9% to 49% across fifths), with loan-to-income (11% to 55%) and for renters. That is the opposite of sound lending logic and matches the *default* label of the credit-risk dataset this one was derived from. The label may mix approval and default semantics, so these directions must not be read as lessons.
- **Neither dataset reflects any real lender's policy.** The difference in dominant feature (CIBIL vs previous defaults) shows how much a synthetic generator decides what a model learns.

## What a real system should collect

The benchmark has several fields that the primary data lacks and that a real pre-eligibility check would need:

1. **Previous defaults / repayment history** (the strongest field in the benchmark, and the basis for any future default-risk model).
2. **Employment type and experience** (stability of income).
3. **Home ownership** (rented, owned, mortgaged).
4. **Loan purpose** (home, education, vehicle, personal, business).
5. **Offered interest rate and existing EMIs** (so the EMI-to-income rule no longer needs an assumed 10% rate).
6. **Length of credit history.**
7. Real **repayment outcomes** after disbursal, if default risk is ever to be modelled.

Gender, age and marital status should not be used as model features.

## Conclusion

The primary dataset's near-perfect accuracy comes from one synthetic rule (CIBIL above or below 550), and the benchmark's from another (previous defaults). Credit score, decisive in one, is irrelevant in the other. LoanLens therefore keeps its framing: a transparent, rule-plus-model pre-screening prototype whose thresholds and model must be re-built on a real lender's data, with credit-history fields such as previous defaults, before any real use.
