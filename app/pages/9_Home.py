"""Home (any signed-in user): a role-aware welcome, the user's pages and how results work."""

from __future__ import annotations

import streamlit as st
from ui_common import PAGES, footer, get_policy, home_cards, page_link, require_user, setup_page

from loanlens.presentation import thresholds_note
from loanlens.theme import hero_html, steps_html, trust_html

STEPS = [
    ("Inputs are checked", "Missing or impossible values are caught before anything else."),
    ("Policy rules apply", "A failed enforced rule, such as a minimum CIBIL score, means "
     "Rejected, whatever the model says."),
    ("The model scores", "It estimates how similar the application is to past approvals in "
     "the synthetic data."),
    ("Borderline is flagged", "Results close to the cut-off are marked for manual review."),
    ("Reasons are explained", "Plain-language reasons and what would likely change the result."),
]  # fmt: skip
TRUST = [
    ("Explainable", "Every rejection comes with reasons in plain language."),
    ("Policy-checked", "Enforced rules are applied before the model."),
    ("Audit-logged", "Each decision is kept in an append-only record."),
    ("Synthetic data", "No real customer or lender data is used."),
]

setup_page("Home", header=False)
principal = require_user()
policy = get_policy()

name = principal.email.split("@", 1)[0].strip()
greeting = f"Welcome back, {name}" if name else "Welcome back"
role_line = (
    "Run bulk checks, review analytics and the audit trail, and manage accounts."
    if principal.is_manager
    else "Check your own eligibility and see the reasons behind every result."
)
cta = "bulk" if principal.is_manager else "check"

with st.container(key="hero"):
    st.markdown(
        hero_html(
            greeting,
            "LoanLens",
            "Explainable loan pre-eligibility: a clear result, the reasons behind it and what "
            f"would likely change it. {role_line}",
        ),
        unsafe_allow_html=True,
    )
    page_link(cta, PAGES[cta].title, ":material/arrow_forward:")

st.info(thresholds_note(policy), icon=":material/info:")

st.subheader("What you can do")
cards = home_cards(principal)
per_row = 4
for start in range(0, len(cards), per_row):
    row = cards[start : start + per_row]
    for col, key in zip(st.columns(per_row), row, strict=False):
        spec = PAGES[key]
        with col, st.container(key=f"feature_{key}"):
            with st.container(key=f"fticon_{key}"):
                st.markdown(spec.icon)
            st.markdown(f"#### {spec.title}")
            st.markdown(spec.blurb)
            page_link(key, "Open", ":material/arrow_forward:")

st.subheader("How a result is decided")
st.markdown(steps_html(STEPS), unsafe_allow_html=True)

st.markdown(trust_html(TRUST), unsafe_allow_html=True)
footer()
