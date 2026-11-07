"""LoanLens entry point: ``streamlit run app/Home.py``.

Signed-out visitors see only the Sign In page, with no menu. After sign-in the menu holds the
pages the account's stored role may open, and Home (``pages/9_Home.py``) is the dashboard.
Every page still checks the role itself. Layout only: all logic is in ``src/loanlens``.
"""

from __future__ import annotations

from ui_common import run_app

run_app()
