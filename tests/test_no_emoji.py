"""No emoji anywhere in the app: source files, UI-text modules and every rendered page.

Status is shown by colour plus plain words ("Approved", "Rejected", "Borderline - manual
review recommended", "Passed" / "Failed"), never by icon characters (decisions_log D-068).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from app_support import open_page

from loanlens import storage
from loanlens.config import PROJECT_ROOT
from loanlens.examples import EXAMPLES

EMOJI = re.compile(
    "["
    "\U0001f000-\U0001faff"  # emoticons, pictographs, transport, flags, supplemental symbols
    "\U000e0000-\U000e007f"  # tag characters (flag sequences)
    "\u2190-\u21ff"  # arrows
    "\u2300-\u23ff"  # misc technical (watch, hourglass, ...)
    "\u25a0-\u25ff"  # geometric shapes
    "\u2600-\u27bf"  # misc symbols and dingbats (check marks, crosses, warning, ...)
    "\u2b00-\u2bff"  # misc symbols and arrows (stars, ...)
    "\u203c\u2049\u2122\u2139\u20e3\u3030\u303d\u3297\u3299"
    "\ufe00-\ufe0f"  # variation selectors
    "\u200d"  # zero-width joiner
    "]"
)
# Streamlit shortcodes such as :white_check_mark: or :material/check: (Sphinx roles like
# :func:`x` in docstrings are followed by a backtick and are not matched).
SHORTCODE = re.compile(r"(?<![\w`:]):[a-z0-9_+\-]+(?:/[a-z0-9_]+)?:(?![\w`:/])")

UI_SOURCES = sorted((PROJECT_ROOT / "app").rglob("*.py")) + sorted(
    (PROJECT_ROOT / "src" / "loanlens").glob("*.py")
)
RENDERED_TEXT = [
    *sorted((PROJECT_ROOT / "config" / "policies").glob("*.yaml")),
    PROJECT_ROOT / "reports" / "model_card.md",
]
PAGES = [
    "Home.py",
    "pages/0_Sign_In.py",
    "pages/1_Check_My_Eligibility.py",
    "pages/2_Bulk_Check.py",
    "pages/3_Analytics.py",
    "pages/4_About.py",
    "pages/5_Users.py",
    "pages/6_Account.py",
]
FIXTURE = Path(__file__).parent / "fixtures" / "batch_1000.csv"


def find_emoji(text: str) -> list[str]:
    """Every emoji character or shortcode in ``text``."""
    return EMOJI.findall(text) + SHORTCODE.findall(text)


def test_detector_catches_known_emoji() -> None:
    samples = (
        "\u2705", "\u274c", "\u26a0\ufe0f", "\u2696", "\U0001f50e", "\u2139\ufe0f", "\u27a1",
        "\u25ce", "\u2713", "\u2717", ":white_check_mark:", ":material/check:",
    )  # fmt: skip
    for sample in samples:
        assert find_emoji(f"x {sample} y"), sample
    for clean in ("Approved", "Borderline - manual review recommended", ":func:`decide`",
                  "12:30:45", "https://example.com", "Rs 12,50,000 (12.5 lakh)"):  # fmt: skip
        assert not find_emoji(clean), clean


@pytest.mark.parametrize("path", UI_SOURCES + RENDERED_TEXT, ids=lambda p: p.name)
def test_no_emoji_in_source(path: Path) -> None:
    found = find_emoji(path.read_text(encoding="utf-8"))
    assert not found, f"{path.relative_to(PROJECT_ROOT)}: {found}"


# Rendered pages ---------------------------------------------------------------------------


def _strings(message) -> Iterator[str]:
    """Every string field inside a protobuf message (recursively)."""
    for field, value in message.ListFields():
        values = value if field.label == field.LABEL_REPEATED else [value]
        for v in values:
            if isinstance(v, str):
                yield v
            elif hasattr(v, "ListFields"):
                yield from _strings(v)


def _visible_text(node) -> Iterator[str]:
    proto = getattr(node, "proto", None)
    if proto is not None and hasattr(proto, "ListFields"):
        yield from _strings(proto)
    value = getattr(node, "value", None) if type(node).__name__ == "Dataframe" else None
    if isinstance(value, pd.DataFrame):
        yield from (str(c) for c in value.columns)
        yield from (str(v) for v in value.astype(str).to_numpy().ravel())
    for child in getattr(node, "children", {}).values():
        yield from _visible_text(child)


def _assert_clean(at, what: str) -> None:
    assert not at.exception, at.exception
    text = "\n".join(_visible_text(at._tree))
    assert "LoanLens" in text  # sanity: the walk sees the page
    assert not find_emoji(text), f"{what}: {find_emoji(text)}"


def _app(app_path: str, page: str):
    return open_page(page)


@pytest.mark.parametrize("page", PAGES)
def test_no_emoji_on_rendered_pages(app_path, artifact, page) -> None:
    at = _app(app_path, page).run()
    _assert_clean(at, page)


@pytest.mark.parametrize("index", [0, 2, 4], ids=["approved", "rejected", "borderline"])
def test_no_emoji_in_customer_results(app_path, artifact, index) -> None:
    title, applicant, expected = EXAMPLES[index]
    at = _app(app_path, "pages/1_Check_My_Eligibility.py").run()
    for name, value in applicant.items():
        at.number_input(key=f"form_{name}").set_value(value)
    at.button[0].click().run()
    text = "\n".join(_visible_text(at._tree))
    assert expected["status"] in text, title
    if expected["borderline"]:
        assert "Borderline - manual review recommended" in text
    assert "Passed" in text  # policy checks use words
    _assert_clean(at, title)


def test_no_emoji_on_bulk_check_with_fixture(app_path, artifact, monkeypatch, tmp_path) -> None:
    import streamlit as st

    class _Upload:
        def getvalue(self) -> bytes:
            return FIXTURE.read_bytes()

    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: _Upload())
    monkeypatch.setattr(storage, "db_path", lambda policy=None: tmp_path / "page.sqlite")
    at = _app(app_path, "pages/2_Bulk_Check.py").run()
    labels = [m.label for m in at.metric]
    assert {"Approved", "Rejected", "Borderline"} <= set(labels)
    _assert_clean(at, "Bulk Check with fixture")
