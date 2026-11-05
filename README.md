# LoanLens: Explainable Loan Pre-Eligibility & Risk Insights

LoanLens is a **pre-screening and decision-support prototype** that estimates whether a loan
application is likely to be **approved or rejected**, and explains why.

> **Disclaimer.** This is a prototype, not a lending decision. It predicts the *approval decision*
> in a public synthetic dataset (Kaggle). It does **not** predict default. No real customer or
> bank data is used, and no real-world accuracy is claimed. All policy thresholds in
> `config/policy.yaml` are placeholders, illustrative until replaced by a lender's real credit policy.

## Status

Work in progress. See `reports/progress.md` for completed phases and `reports/decisions_log.md`
for design decisions.

## Setup (Windows, Python 3.11)

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Place the datasets in `data/raw/` (they are not committed):

- `loan_approval_dataset.csv` (primary)
- `bank_loan_data.csv` (benchmark only)
- `loan_data.csv` (sanity check only)

## Development

```bash
pip install -e .                 # make `loanlens` importable
python -m loanlens.cleaning       # build data/processed/loan_approval_clean.csv
ruff check .
pytest
```
