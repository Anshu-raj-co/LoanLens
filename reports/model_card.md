# Model Card: LoanLens approval model v1.0.0

> **This model predicts the loan *approval decision* in a synthetic public dataset. It does not predict default.** Default means a disbursed loan that later goes unpaid (NPA, 90+ days overdue), and there is no repayment data here. LoanLens is a pre-screening and decision-support prototype, not a lending decision. No real-world accuracy is claimed.

All numbers below come from `notebooks/03_modelling.ipynb` (stratified 5-fold cross-validation, seed 42).

## Model details

| | |
|---|---|
| Artifact | `models/loanlens_model.joblib` (+ `.json` metadata), version `1.0.0` |
| Algorithm | XGBoost classifier (300 trees, max depth 4, learning rate 0.1) |
| Calibration | Isotonic (`CalibratedClassifierCV`, 5-fold, `ensemble=False`) |
| Monotone constraints | Approval can only **rise** with `cibil_score` and only **fall** with `loan_to_income` |
| Features | `cibil_score`, `loan_term`, `loan_to_income` (loan / annual income), `income_annum`, `total_assets` (sum of the 4 asset values) |
| Not used | Education, self-employment, dependents (no effect in EDA); individual asset columns (no gain over the total); raw `loan_amount` (see "Constraints"); `loan_id` |
| Never used | Gender, marital status (not in the data; blocked in code) |
| Training rows | 4,269 |
| Train | `python -m loanlens.model` |

## Intended use

- **For:** illustrating explainable pre-screening, i.e. how a profile compares with past approval decisions, plus what would likely change the outcome.
- **Not for:** real lending decisions, credit-risk or default estimation, or any use on real customer data without re-training and validation on real bank data.

## How a decision is made

The model is one step in `decision.py`: input validation, then the policy rules (`config/policy.yaml`), then the model, then the borderline flag. **An enforced rule failure (for example CIBIL below 550) always means Rejected, whatever the model says.** All policy thresholds are placeholders, illustrative until replaced by a lender's real credit policy.

A result is flagged **borderline (manual review recommended)** in two cases. The first is when no enforced rule failed and the probability is between 40% and 60%. The second is when the CIBIL score is within 25 points of the enforced minimum, on either side. The status is still Approved or Rejected.

The score is shown as a percentage that never reads 0% or 100% (">99%" / "<1%"), together with a verbal band: Very likely (85% or more), Likely (65 to 85%), Borderline (35 to 65%), Unlikely (15 to 35%), or Very unlikely (under 15%). It is labelled "model score on synthetic data - indicative only". Stored probabilities are unchanged.

## Data

- **Source:** `loan_approval_dataset.csv`, a public synthetic dataset from Kaggle. 4,269 applicants, amounts in INR, CIBIL 300 to 900, 62.2% approved.
- **Cleaning:** whitespace stripped, target mapped to 1/0, and 28 rows with residential assets of exactly -1,00,000 set to 0 (see `notebooks/01_audit.ipynb`).
- **Ranges seen in training:** income Rs 2,00,000 to Rs 99,00,000; loan Rs 3,00,000 to Rs 3,95,00,000; term 2 to 20 years (even values only); loan-to-income 1.5 to 4.0. Inputs outside these ranges produce a warning.

## Metrics

### Final model (stratified 5-fold CV, threshold 0.5)

| Metric | Mean | Std |
|---|---|---|
| ROC-AUC | 0.9942 | 0.0020 |
| PR-AUC | 0.9946 | 0.0019 |
| Precision | 0.9527 | 0.0136 |
| Recall | 0.9759 | 0.0203 |
| F1 | 0.9639 | 0.0058 |
| Accuracy | 0.9546 | 0.0069 |
| Brier score | 0.0257 | 0.0032 |

Out-of-fold confusion matrix:

| | Predicted rejected | Predicted approved |
|---|---|---|
| **Actually rejected** | 1,483 | 130 |
| **Actually approved** | 64 | 2,592 |

**Full decision (enforced CIBIL rule, then model) against the labels:** precision 0.995, recall 0.929, F1 0.961, accuracy 0.953. Recall is lower because the hard CIBIL rule rejects 185 low-CIBIL applicants who were approved in the synthetic data.

### Model comparison (unconstrained, 5-fold CV)

| Model | Feature set | ROC-AUC | PR-AUC | F1 |
|---|---|---|---|---|
| Logistic regression | all columns + loan-to-income | 0.9687 | 0.9799 | 0.9312 |
| Random forest | all columns + loan-to-income | 0.9985 | 0.9988 | 0.9970 |
| XGBoost | all columns + loan-to-income | 0.9993 | 0.9996 | 0.9955 |
| Logistic regression | compact | 0.9689 | 0.9802 | 0.9322 |
| Random forest | compact | 0.9989 | 0.9992 | 0.9970 |
| XGBoost | compact | 0.9992 | 0.9995 | 0.9957 |

**Choice rule:** the simplest model within about 1% ROC-AUC of the best. Logistic regression is more than 2.5 points behind, so it is out. Constrained XGBoost and constrained random forest tie at 0.9942. XGBoost is the smaller model (about 3,000 leaves vs about 30,000), so XGBoost was chosen.

## CIBIL dominance and the leakage check

The scores are near-perfect because the synthetic label is close to a deterministic rule, not because of leakage.

| Ablation (XGBoost, compact features) | ROC-AUC | F1 |
|---|---|---|
| All compact features | 0.9992 | 0.9957 |
| CIBIL only | 0.9603 | 0.9607 |
| Without CIBIL | 0.5837 | 0.6980 |
| Without loan term | 0.9822 | 0.9547 |
| Without loan-to-income | 0.9948 | 0.9663 |

- CIBIL has the largest share of the model's influence (57%, see "Feature importance" below). In the data, 99.5% of applicants above CIBIL 550 are approved, against 10.6% at or below.
- Shuffled labels give ROC-AUC 0.499 (chance). No identifier or target-derived feature is used, and there are no duplicate rows.
- The remaining signal (loan term, loan-to-income) comes from a synthetic quirk. Among low-CIBIL applicants, 2 and 4 year loans with a *high* loan-to-income ratio were approved.

## Feature importance

One measure is used for every headline figure in LoanLens (this card, the Analytics page and the About page): the **mean absolute SHAP share**, i.e. each feature's average influence on the model score across the 4,269 training applicants, as a share of the total.

| Feature | Share of influence |
|---|---|
| CIBIL score | 57% |
| Loan term | 19% |
| Total assets | 12% |
| Annual income | 7% |
| Loan-to-income ratio | 4% |

Loan term's share comes from the synthetic short-term quirk described above, not from real lending policy. (An earlier version of this card quoted XGBoost's internal "gain", which put CIBIL at about 74%. Gain measures how much each feature improves the tree splits during training, not how much it moves an applicant's score, so it gives a different number for the same model. It is no longer used as a headline.)

## Constraints (why the model disagrees with some labels)

Without constraints, the model learns the quirk: "for a low-CIBIL short-term applicant, a bigger loan raises approval". In a probe that raised every loan by 25%, approval probability went *up* for 41% of low-CIBIL short-term rows. That is the opposite of sound lending logic. With the monotone constraints, and with raw `loan_amount` removed (otherwise the model routes around the loan-to-income constraint), no row's probability goes up.

Cost: 0.40 ROC-AUC points, under the 1% limit. On the rows the model actually decides (CIBIL >= 550), and for the full rule + model decision, the cost is zero (system F1 0.9611 constrained vs 0.9609 unconstrained). The F1 drop against the raw labels, from 0.996 to 0.964, sits entirely in rows the hard CIBIL rule rejects anyway.

## Calibration

| Method | ROC-AUC | Brier | Log loss |
|---|---|---|---|
| None | 0.9952 | 0.0275 | 0.0868 |
| Sigmoid (Platt) | 0.9952 | 0.0310 | 0.1143 |
| **Isotonic (chosen)** | 0.9942 | 0.0257 | 0.0803 |

The calibration curve is in the notebook. Isotonic calibration is step-shaped, so many applicants share the same probability, and probabilities near 0.5 (the borderline band) are rare.

## Limitations

- **Synthetic data:** the patterns reflect how the dataset was generated, not any real lender's policy or real borrowers.
- **Approval, not default:** nothing here measures repayment risk.
- **Narrow ranges:** predictions outside the training ranges are unreliable, and the app warns.
- **No interest rate, existing EMIs or employment history in the data.** The EMI-to-income rule therefore uses an assumed 10% rate and is advisory only.
- **Loan term:** the model still uses term, and short terms are linked to approval in the synthetic data. The "what would change" feature never suggests changing the term.
- **Probabilities** are calibrated to the synthetic labels only.

## Assumptions

- Assumed annual interest rate of 10% for EMI (placeholder).
- Every policy threshold and enforce flag in `config/policy.yaml` is a placeholder, illustrative until replaced by a lender's real credit policy.
- Approval threshold 0.5; borderline band 0.4 to 0.6; borderline CIBIL margin of +/- 25 points; likelihood band cut-offs 85 / 65 / 35 / 15% (all placeholders).
