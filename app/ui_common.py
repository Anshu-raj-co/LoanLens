"""Shared look and safety helpers for every LoanLens page (layout only, no business logic)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from loanlens import model as model_mod
from loanlens import registry
from loanlens.config import Policy, load_policy
from loanlens.presentation import DISCLAIMER, PROTOTYPE_NOTICE
from loanlens.theme import css_block, header_html

APP_NAME = "LoanLens"


def setup_page(title: str) -> None:
    """Page config, sidebar branding and the page title. Call first on every page."""
    st.set_page_config(page_title=f"{APP_NAME} | {title}", layout="wide")
    st.markdown(css_block(), unsafe_allow_html=True)
    st.markdown(header_html(APP_NAME), unsafe_allow_html=True)
    with st.sidebar:
        st.markdown(f"### {APP_NAME}")
        st.caption("Explainable loan pre-eligibility prototype")
        st.caption(PROTOTYPE_NOTICE)
    st.title(title)


def footer() -> None:
    """Disclaimer footer shown at the bottom of every page."""
    st.divider()
    st.caption(f"**{PROTOTYPE_NOTICE}.** {DISCLAIMER}")


def get_policy() -> Policy:
    """Load the policy file, or stop the page with a friendly message."""
    try:
        return load_policy()
    except Exception:  # noqa: BLE001 - never show a stack trace to the user
        st.error(
            "The policy settings files (config/policies/) could not be read. "
            "Please ask the administrator to check it."
        )
        footer()
        st.stop()
        raise  # pragma: no cover - st.stop() ends the script


@st.cache_resource(show_spinner="Loading the model...")
def _cached_artifact() -> dict[str, Any]:
    return model_mod.load_artifact()


def get_model() -> dict[str, Any]:
    """Load (once per server) the trained model, or stop with a friendly message."""
    try:
        return _cached_artifact()
    except FileNotFoundError:
        st.error(
            "The prediction model has not been trained yet, so results cannot be shown. "
            "Ask the administrator to run `python -m loanlens.model` and reload this page."
        )
    except registry.RegistryError as exc:  # plain message, e.g. a fingerprint mismatch
        st.error(f"The prediction model could not be loaded. {exc}")
    except Exception:  # noqa: BLE001
        st.error(
            "The prediction model could not be loaded. Ask the administrator to retrain it "
            "with `python -m loanlens.model`."
        )
    footer()
    st.stop()
    raise RuntimeError  # pragma: no cover - st.stop() ends the script


def friendly_failure(context: str) -> None:
    """Show a generic friendly error (used in place of a stack trace)."""
    st.error(
        f"Sorry, something went wrong while {context}. Please check the inputs and try again. "
        "If the problem continues, contact the LoanLens administrator."
    )


def streamlit_secrets() -> Any:
    """``st.secrets`` if a secrets file exists, else None.

    Reading ``st.secrets`` without a file makes Streamlit show its own error box, so the
    usual locations are checked first.
    """
    project = Path(__file__).resolve().parents[1]
    candidates = [
        Path.home() / ".streamlit" / "secrets.toml",
        Path.cwd() / ".streamlit" / "secrets.toml",
        project / ".streamlit" / "secrets.toml",
    ]
    return st.secrets if any(c.exists() for c in candidates) else None
