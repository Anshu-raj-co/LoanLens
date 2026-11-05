"""Analytics: approval patterns in the training data, model drivers and the latest batch."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from ui_common import footer, get_model, get_policy, setup_page

from loanlens import charts, cleaning, explain, storage
from loanlens import model as model_mod

setup_page("Analytics", "📊")
policy = get_policy()
artifact = get_model()


@st.cache_data(show_spinner="Loading the training data...")
def load_training_data() -> pd.DataFrame | None:
    """Cleaned primary dataset (synthetic), or None if it has not been built."""
    if not cleaning.PROCESSED_PATH.exists():
        return None
    return pd.read_csv(cleaning.PROCESSED_PATH)


@st.cache_data(show_spinner="Working out what drives the model...")
def load_importance(model_version: str, trained_at: str) -> pd.Series | None:
    """Mean |SHAP| share per feature on the training data (cached per model version)."""
    df = load_training_data()
    if df is None:
        return None
    return explain.feature_importance(artifact, model_mod.build_frame(df))


df = load_training_data()
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
    importance = load_importance(str(artifact.get("version")), str(artifact.get("trained_at")))
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
        latest = storage.latest_summary(storage.db_path(policy))
        history = storage.list_summaries(10, storage.db_path(policy))
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
            ("warning", "⚠ Borderline", f"{latest['borderline']:,}"),
            ("approved", "✅ Approval rate", "n/a" if rate is None else f"{rate:.0%}"),
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
