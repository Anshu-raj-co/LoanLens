"""Analytics (bank managers only): approval patterns, model drivers and the latest batch."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from ui_common import footer, get_model, get_policy, require_user, setup_page

from loanlens import auth, charts, services
from loanlens.db.engine import DatabaseError

setup_page("Analytics")
principal = require_user(auth.MANAGER)
policy = get_policy()
artifact = get_model()

try:
    with st.spinner("Loading the training data..."):
        df = services.training_data(principal)
except auth.AuthorisationError as exc:
    st.error(f"{exc} Open Sign in in the sidebar.")
    footer()
    st.stop()
st.caption(
    "Charts 1 to 3 describe approval decisions in the **public synthetic training data**. "
    "They are not results from any real lender and say nothing about repayment or default."
)

tab_data, tab_model, tab_batch = st.tabs(
    ["Approval patterns", "What drives the model", "Latest batch"]
)

with tab_data:
    if df is None:
        st.error(
            "The cleaned training data was not found. Ask the administrator to run "
            "`python -m loanlens.cleaning`."
        )
    else:
        st.plotly_chart(charts.approval_by_cibil_band(df), use_container_width=True, theme=None)
        st.caption("CIBIL dominates: approval is near-certain above 550 and rare at or below it.")
        left, right = st.columns(2)
        with left:
            st.plotly_chart(
                charts.approval_rate_bar(
                    df, "loan_term", "Approval rate by loan term", "Loan term (years)"
                ),
                use_container_width=True,
                theme=None,
            )
            st.caption(
                "Short terms look better only because of a quirk among low-CIBIL applicants "
                "in the synthetic data. This is not lending advice."
            )
        with right:
            st.plotly_chart(
                charts.approval_by_quantile_band(
                    df, "loan_amount", q=5, title="Approval rate by loan size (quintiles, Rs)"
                ),
                use_container_width=True,
                theme=None,
            )
            st.caption("Loan size on its own makes little difference in this data.")

with tab_model:
    with st.spinner("Working out what drives the model..."):
        importance = services.feature_importance(principal, artifact)
    if importance is None:
        st.error("Feature importance needs the cleaned training data (see the first tab).")
    else:
        st.plotly_chart(
            charts.feature_importance_bar(
                importance, "What drives the model (mean absolute SHAP, training data)"
            ),
            use_container_width=True,
            theme=None,
        )
        st.caption(
            f"Model v{artifact.get('version')} ({artifact.get('kind')}, "
            f"{artifact.get('calibration')} calibration). Share of each feature's average "
            "influence on the model score (mean absolute SHAP share). This is the one measure "
            "LoanLens uses for feature importance, here, on the About page and in the model "
            "card. Loan term ranks second only because of a quirk in the synthetic data. "
            "Policy rules are applied separately and are not included here."
        )

with tab_batch:
    try:
        latest = services.latest_batch_summary(principal, policy)
        history = services.recent_batch_summaries(principal, 10, policy)
    except DatabaseError as exc:  # plain message, never a stack trace
        latest, history = None, pd.DataFrame()
        st.error(f"The batch history could not be read. {exc}")
    except Exception:  # noqa: BLE001 - never show a stack trace
        latest, history = None, pd.DataFrame()
        st.error("The batch history could not be read.")
    if latest is None:
        st.info("No batch has been checked yet. Run one on the **Bulk Check** page.")
    else:
        st.markdown(f"**Batch #{latest['id']}**, checked {latest['created_at']} (UTC)")
        rate = latest["approval_rate"]
        cards = [
            ("primary", "Rows in file", f"{latest['total_rows']:,}"),
            ("primary", "Scored", f"{latest['valid_rows']:,}"),
            ("neutral", "Skipped (invalid)", f"{latest['invalid_rows']:,}"),
            ("warning", "Borderline", f"{latest['borderline']:,}"),
            ("approved", "Approval rate", "n/a" if rate is None else f"{rate:.0%}"),
        ]
        columns = st.columns(len(cards))
        for i, (col, (tone, label, value)) in enumerate(zip(columns, cards, strict=True)):
            with col, st.container(key=f"kpi_{tone}_{i}"):
                st.metric(label, value)
        left, right = st.columns(2)
        with left:
            reasons = {r["reason"]: r["count"] for r in latest["top_rejection_reasons"]}
            if reasons:
                st.plotly_chart(
                    charts.counts_bar(reasons, "Top rejection reasons", "", horizontal=True),
                    use_container_width=True,
                    theme=None,
                )
            else:
                st.info("No rejections in this batch.")
        with right:
            order = ["Very unlikely", "Unlikely", "Borderline", "Likely", "Very likely"]
            bands = {b: latest["likelihood_bands"].get(b, 0) for b in order}
            st.plotly_chart(
                charts.counts_bar(bands, "Applicants by likelihood band", "Likelihood band"),
                use_container_width=True,
                theme=None,
            )
        if len(history) > 1:
            with st.expander("Recent batches (anonymised summaries)"):
                st.dataframe(history, hide_index=True, use_container_width=True)

footer()
