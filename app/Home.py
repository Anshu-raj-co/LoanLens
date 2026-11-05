"""LoanLens home page: purpose, disclaimer and navigation."""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from ui_common import footer, get_policy, setup_page

from loanlens.presentation import DISCLAIMER, thresholds_note

APP_DIR = Path(__file__).resolve().parent

setup_page("LoanLens: Loan Pre-Eligibility", "🔎")
policy = get_policy()

st.markdown(
    "LoanLens gives a quick, explainable **pre-eligibility check** for a loan application: "
    "whether it is likely to be approved or rejected, how confident the model is, and, if it "
    "is likely to be rejected, the main reasons and what would likely change the outcome."
)
st.warning(DISCLAIMER)
st.info(thresholds_note(policy))

st.subheader("Choose what you want to do")
PAGES = [
    ("pages/1_Check_My_Eligibility.py", "🙋 Check my eligibility",
     "For individuals: enter your own details and get an instant, explained result."),
    ("pages/2_Bulk_Check.py", "🏦 Bulk check (bank staff)",
     "Upload a CSV of many applicants, review every result and download them."),
    ("pages/3_Analytics.py", "📊 Analytics",
     "Approval patterns in the training data, model drivers and the latest batch."),
    ("pages/4_About.py", "ℹ️ About and model card",
     "Data source, metrics, assumptions, limitations and current policy settings."),
]  # fmt: skip
available = [p for p in PAGES if (APP_DIR / p[0]).exists()]
for start in range(0, len(available), 2):
    for col, (path, title, text) in zip(st.columns(2), available[start : start + 2], strict=False):
        with col, st.container(border=True):
            st.markdown(f"#### {title}")
            st.write(text)
            st.page_link(path, label=f"Open {title.split(' ', 1)[1].lower()}", icon="➡️")

st.subheader("How a result is decided")
st.markdown(
    "1. **Your inputs are checked** for missing or impossible values.\n"
    "2. **Policy rules** are applied (for example a minimum CIBIL score). A failed rule means "
    "*rejected*, whatever the model says.\n"
    "3. **The model** estimates how similar the application is to past approvals.\n"
    "4. Results close to the cut-off are flagged as **borderline: manual review "
    "recommended**.\n"
    "5. **Reasons** are explained in plain language, with what would likely change the result."
)
footer()
