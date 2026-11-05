"""Customer mode: check my eligibility. Nothing entered here is stored or logged."""

from __future__ import annotations

import streamlit as st
from ui_common import footer, friendly_failure, get_model, get_policy, setup_page

from loanlens.decision import decide
from loanlens.presentation import (
    FORM_FIELDS,
    PRIVACY_NOTE,
    PROTOTYPE_NOTICE,
    amount_hint,
    present,
    thresholds_note,
)
from loanlens.schema import ValidationFailure

setup_page("Check My Eligibility", "🙋")
policy = get_policy()
artifact = get_model()

st.warning(f"**{PROTOTYPE_NOTICE}.** This is an indicative pre-screening check only.")
st.caption(thresholds_note(policy))
st.caption(PRIVACY_NOTE)

# ---- Form ----------------------------------------------------------------------------------
st.subheader("Your details")
values: dict[str, float] = {}
columns = st.columns(2)
for i, f in enumerate(FORM_FIELDS):
    with columns[i % 2]:
        values[f.name] = st.number_input(
            f.label,
            min_value=f.min_value,
            max_value=f.max_value,
            value=f.default,
            step=f.step,
            help=f.help,
            key=f"form_{f.name}",
        )
        if f.is_amount:
            st.caption(f"= {amount_hint(values[f.name])}")

checked = st.button("Check eligibility", type="primary", use_container_width=True)

# ---- Result --------------------------------------------------------------------------------
if checked:
    try:
        result = decide(values, policy=policy, artifact=artifact)
    except Exception:  # noqa: BLE001 - never show a stack trace
        friendly_failure("checking your eligibility")
        result = None

    if isinstance(result, ValidationFailure):
        st.error("Please correct the following and try again:")
        for err in result.errors:
            st.markdown(f"- {err.message}")
    elif result is not None:
        view = present(result, policy)
        st.divider()
        st.subheader("Your result")
        badge_col, score_col = st.columns([2, 1])
        with badge_col:
            if view.approved:
                st.success(f"### ✅ {view.status}\n{view.headline}")
            else:
                st.error(f"### ❌ {view.status}\n{view.headline}")
        with score_col:
            st.metric("Approval likelihood", view.likelihood)
            st.caption(view.score_label)
        if view.borderline:
            st.warning(f"⚖️ **Borderline: manual review recommended.** {view.borderline_note}")
        st.info(f"**{view.notice}.**")

        if view.reasons:
            st.markdown("#### Why")
            for reason in view.reasons:
                with st.container(border=True):
                    st.markdown(f"**{reason.message}**")
                    st.caption(f"Your value: {reason.your_value}  |  Benchmark: {reason.benchmark}")
                    if reason.suggestion:
                        st.markdown(f"💡 {reason.suggestion}")

        if not view.approved:
            st.markdown("#### What would likely change this")
            st.markdown(view.change_summary)
            st.caption("Estimates only: a change is never a guarantee of approval.")

        if view.positives:
            st.markdown("#### What is working in your favour")
            for reason in view.positives:
                with st.container(border=True):
                    st.markdown(f"✔️ {reason.message}")

        for warning in view.warnings:
            st.warning(warning)

        with st.expander("Policy checks"):
            st.dataframe(view.rule_rows, hide_index=True, use_container_width=True)

footer()
