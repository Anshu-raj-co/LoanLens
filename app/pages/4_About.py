"""About / model card: data source, metrics, assumptions, limitations, policy settings."""

from __future__ import annotations

import streamlit as st
from ui_common import footer, get_policy, setup_page

from loanlens import model as model_mod
from loanlens.config import PROJECT_ROOT
from loanlens.presentation import policy_table, thresholds_note

MODEL_CARD = PROJECT_ROOT / "reports" / "model_card.md"

setup_page("About LoanLens", "ℹ️")
policy = get_policy()

st.warning(
    "**Approval, not default.** LoanLens estimates whether an application looks like those "
    "that were *approved* in a public synthetic dataset. It does not predict default (a "
    "disbursed loan that later goes unpaid), because there is no repayment data. It is a "
    "pre-screening prototype, not a lending decision."
)

st.subheader("At a glance")
c1, c2 = st.columns(2)
with c1, st.container(border=True):
    st.markdown(
        "**Data source**\n\n"
        "`loan_approval_dataset.csv`: public, synthetic Kaggle data. 4,269 applicants, "
        "amounts in INR, CIBIL 300 to 900, 62% approved. No real customer or bank data is "
        "used."
    )
with c2, st.container(border=True):
    try:
        art = model_mod.load_artifact()
        m = art.get("cv_metrics", {})
        st.markdown(
            f"**Model v{art.get('version')}**: {art.get('kind')}, "
            f"{art.get('calibration')} calibration, trained {art.get('trained_at')} on "
            f"{art.get('n_train', 0):,} rows.\n\n"
            f"5-fold CV: ROC-AUC {m.get('roc_auc', float('nan')):.3f}, "
            f"PR-AUC {m.get('pr_auc', float('nan')):.3f}, F1 {m.get('f1', float('nan')):.3f}, "
            f"precision {m.get('precision', float('nan')):.3f}, "
            f"recall {m.get('recall', float('nan')):.3f}."
        )
    except FileNotFoundError:
        st.warning("The model has not been trained yet (run `python -m loanlens.model`).")

st.subheader("Current policy settings")
st.warning(thresholds_note(policy))
st.dataframe(policy_table(policy), hide_index=True, use_container_width=True)
st.caption(
    "Values come from `config/policy.yaml`. *Enforced* rules reject on failure; advisory "
    "rules only add a warning. Every value is a placeholder, illustrative until replaced by a "
    "lender's real credit policy."
)

st.subheader("Model card")
if MODEL_CARD.exists():
    with st.container(border=True):
        st.markdown(MODEL_CARD.read_text(encoding="utf-8"))
else:
    st.info("The model card (reports/model_card.md) was not found.")

st.subheader("Future work")
st.markdown(
    "- Real authentication for bank staff (the Bulk Check gate is a prototype switch).\n"
    "- Re-training and validation on real, consented bank data, with real policy thresholds.\n"
    "- Repayment data, if default risk is ever to be modelled (out of scope for this "
    "prototype)."
)
footer()
