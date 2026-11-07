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
    key_figures,
    present,
    profile_caption,
    profile_label,
    thresholds_note,
)
from loanlens.schema import ValidationFailure
from loanlens.theme import meter_html, pill_html, policy_checks_html, status_label

# Layout only: which form fields share a card (every field appears once, in schema order).
SECTIONS = [
    ("credit", ":material/credit_score:", "Credit and income", ["cibil_score", "income_annum"]),
    ("loan", ":material/request_quote:", "The loan", ["loan_amount", "loan_term"]),
    ("assets", ":material/account_balance:", "What you own",
     ["residential_assets_value", "commercial_assets_value", "luxury_assets_value",
      "bank_asset_value"]),
]  # fmt: skip
FIELDS = {f.name: f for f in FORM_FIELDS}

setup_page(
    "Check My Eligibility",
    "Enter your details for an instant, explained pre-eligibility result.",
)
principal = require_user()
get_policy()  # stops with a friendly message if the policy files cannot be read
artifact = get_model()

st.warning(
    f"**{PROTOTYPE_NOTICE}.** This is an indicative pre-screening check only.",
    icon=":material/info:",
)
profiles = list_profiles()
type_col, note_col = st.columns([1, 2], vertical_alignment="bottom")
with type_col:
    loan_type = st.selectbox(
        "Loan type",
        profiles,
        index=profiles.index(DEFAULT_PROFILE),
        format_func=profile_label,
        help=PROFILE_NOTE,
        key="form_loan_type",
    )
policy = load_profile(loan_type)
with note_col:
    st.caption(f"{policy.description} {PROFILE_NOTE}")
st.caption(thresholds_note(policy))
st.caption(PRIVACY_NOTE)

# ---- Form ----------------------------------------------------------------------------------
st.subheader("Your details")
values: dict[str, float] = {}
left, right = st.columns(2, gap="medium")
for (key, icon, heading, names), column in zip(SECTIONS, [left, right, left], strict=True):
    with column, st.container(key=f"form_section_{key}"):
        st.markdown(f"#### {icon} {heading}")
        inner = st.columns(2) if len(names) > 2 else [st.container()]
        for i, name in enumerate(names):
            f = FIELDS[name]
            with inner[i % len(inner)]:
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
with right:
    checked = st.button(
        "Check eligibility", type="primary", use_container_width=True,
        icon=":material/fact_check:",
    )  # fmt: skip
    st.caption("Each check is saved to My History and to the decision audit trail.")

# ---- Result --------------------------------------------------------------------------------
if checked:
    try:
        scored = services.score_applicant(
            principal, values, product=loan_type, channel=services.UI, artifact=artifact
        )
        result = scored if isinstance(scored, ValidationFailure) else scored.result
    except auth.AuthorisationError as exc:
        st.error(f"{exc} Open Sign In from the menu.")
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
        tone = "approved" if view.approved else "rejected"
        with st.container(key=f"banner_{tone}"):
            badge_col, score_col = st.columns([3, 2], vertical_alignment="center", gap="large")
            with badge_col:
                alert = st.success if view.approved else st.error
                icon = ":material/check_circle:" if view.approved else ":material/cancel:"
                alert(f"### {status_label(view.status)}\n{view.headline}", icon=icon)
                if view.borderline:
                    st.markdown(
                        pill_html("Borderline - manual review recommended", "warning"),
                        unsafe_allow_html=True,
                    )
            with score_col:
                st.metric("Approval likelihood", view.likelihood)
                band = policy.model.borderline_band
                st.markdown(
                    meter_html(
                        result.probability, policy.model.approval_threshold,
                        (band.lower, band.upper), view.approved,
                        f"Approval likelihood {view.likelihood}",
                    ),
                    unsafe_allow_html=True,
                )  # fmt: skip
                st.caption(view.score_label)
        st.caption(f"{profile_caption(policy)} Model v{result.model_version}.")

        figures = key_figures(result)
        if figures:
            with st.container(key="result_figures"):
                for col, fig in zip(st.columns(len(figures)), figures, strict=True):
                    with col:
                        st.metric(fig.label, fig.value)
                        st.caption(fig.detail)

        if view.borderline:
            st.warning(
                f"**Borderline: manual review recommended.** {view.borderline_note}",
                icon=":material/flag:",
            )
        st.info(f"**{view.notice}.**", icon=":material/info:")

        if view.reasons:
            st.markdown("#### Why")
            for i, reason in enumerate(view.reasons):
                with st.container(key=f"card_rejected_reason_{i}"):
                    st.markdown(f":material/report: **{reason.message}**")
                    st.caption(f"Your value: {reason.your_value}  |  Benchmark: {reason.benchmark}")
                    if reason.suggestion:
                        st.markdown(reason.suggestion)

        if not view.approved:
            st.markdown("#### What would likely change this")
            with st.container(key="card_primary_change"):
                st.markdown(f":material/lightbulb: {view.change_summary}")
                st.caption("Estimates only: a change is never a guarantee of approval.")

        if view.positives:
            st.markdown("#### What is working in your favour")
            for i, reason in enumerate(view.positives):
                with st.container(key=f"card_approved_positive_{i}"):
                    st.markdown(f":material/verified: {reason.message}")

        for warning in view.warnings:
            st.warning(warning, icon=":material/warning:")

        with st.expander("Policy checks"):
            st.markdown(policy_checks_html(view.rule_rows), unsafe_allow_html=True)

footer()
