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

## Run the app

```bash
python -m loanlens.model          # once, if models/loanlens_model.joblib is missing
streamlit run app/Home.py
```

- **Check My Eligibility**: customer form with an instant, explained result. Nothing is stored.
- **Bulk Check**: turn on *Bank manager mode* in the sidebar, download the CSV template, and upload up to **50,000 rows** per file (measured: about 0.7 s per 1,000 rows, about 32 s for 50,000). Invalid rows are listed and skipped. Results can be filtered and downloaded. Only anonymised batch summaries are saved, to `data/loanlens.sqlite`.
- **Analytics**: approval by CIBIL band, loan term and loan size in the training data, what drives the model, and the latest batch summary.
- **About**: the "approval, not default" framing, data source, metrics, current policy settings and the model card (`reports/model_card.md`).

All policy thresholds in `config/policy.yaml` are illustrative placeholders illustrative until replaced by a lender's real credit policy.

## Development

```bash
pip install -e .                 # make `loanlens` importable
python -m loanlens.cleaning       # build data/processed/loan_approval_clean.csv
python -m loanlens.rules          # write reports/rules_vs_labels.md
python -m loanlens.model          # train and save models/loanlens_model.joblib
python scripts/example_decisions.py  # write reports/example_decisions.md
ruff check .
pytest
```
