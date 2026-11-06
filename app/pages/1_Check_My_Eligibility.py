"""Check my eligibility (any signed-in user). Each check is saved to the account history."""

from __future__ import annotations

import streamlit as st
from ui_common import footer, friendly_failure, get_model, get_policy, require_user, setup_page

from loanlens import auth, services
from loanlens.config import DEFAULT_PROFILE, list_profiles, load_profile
from loanlens.db.engine import DatabaseError
from loanlens.presentation import (
    FORM_FIELDS,
    PRIVACY_NOTE,
    PROFILE_NOTE,
    PROTOTYPE_NOTICE,
    amount_hint,
    present,
    profile_caption,
    profile_label,
    thresholds_note,
)
from loanlens.schema import ValidationFailure
from loanlens.theme import pill_html, policy_checks_html, status_label

setup_page("Check My Eligibility")
principal = require_user()
get_policy()  # stops with a friendly message if the policy files cannot be read
artifact = get_model()

st.warning(f"**{PROTOTYPE_NOTICE}.** This is an indicative pre-screening check only.")
profiles = list_profiles()
loan_type = st.selectbox(
    "Loan type",
    profiles,
    index=profiles.index(DEFAULT_PROFILE),
    format_func=profile_label,
    help=PROFILE_NOTE,
    key="form_loan_type",
)
policy = load_profile(loan_type)
st.caption(f"{policy.description} {PROFILE_NOTE}")
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
        scored = services.score_applicant(
            principal, values, product=loan_type, channel=services.UI, artifact=artifact
        )
        result = scored if isinstance(scored, ValidationFailure) else scored.result
    except auth.AuthorisationError as exc:
        st.error(f"{exc} Open Sign in in the sidebar.")
        result = None
    except DatabaseError:
        st.error(
            "Your check could not be saved to your history, so no result is shown. Please try "
            "again later or contact the LoanLens administrator."
        )
        result = None
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
        with st.container(key=f"banner_{'approved' if view.approved else 'rejected'}"):
            badge_col, score_col = st.columns([2, 1], vertical_alignment="center")
            with badge_col:
                alert = st.success if view.approved else st.error
                alert(f"### {status_label(view.status)}\n{view.headline}")
                if view.borderline:
                    st.markdown(
                        pill_html("Borderline - manual review recommended", "warning"),
                        unsafe_allow_html=True,
                    )
            with score_col:
                st.metric("Approval likelihood", view.likelihood)
                st.caption(view.score_label)
        st.caption(f"{profile_caption(policy)} Model v{result.model_version}.")
        if view.borderline:
            st.warning(f"**Borderline: manual review recommended.** {view.borderline_note}")
        st.info(f"**{view.notice}.**")

        if view.reasons:
            st.markdown("#### Why")
            for i, reason in enumerate(view.reasons):
                with st.container(key=f"card_rejected_reason_{i}"):
                    st.markdown(f"**{reason.message}**")
                    st.caption(f"Your value: {reason.your_value}  |  Benchmark: {reason.benchmark}")
                    if reason.suggestion:
                        st.markdown(reason.suggestion)

        if not view.approved:
            st.markdown("#### What would likely change this")
            with st.container(key="card_primary_change"):
                st.markdown(view.change_summary)
                st.caption("Estimates only: a change is never a guarantee of approval.")

        if view.positives:
            st.markdown("#### What is working in your favour")
            for i, reason in enumerate(view.positives):
                with st.container(key=f"card_approved_positive_{i}"):
                    st.markdown(reason.message)

        for warning in view.warnings:
            st.warning(warning)

        with st.expander("Policy checks"):
            st.markdown(policy_checks_html(view.rule_rows), unsafe_allow_html=True)

footer()
