"""UI restyle: the theme module, status colours, contrast and that every page still renders."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pandas as pd
import plotly.io as pio
import pytest

from loanlens import charts, theme
from loanlens.config import PROJECT_ROOT

REQUIRED = {
    "background": "#FFFFFF",
    "soft_panel": "#F4F7FE",
    "border": "#E3E9F5",
    "primary": "#2E74E9",
    "indigo": "#5271FF",
    "text": "#0F1B3D",
    "muted": "#5B6785",
    "approved": "#1E9E5A",
    "approved_tint": "#E8F6EE",
    "rejected": "#D93636",
    "rejected_tint": "#FDECEC",
    "warning": "#B7791F",
    "warning_tint": "#FFF4DB",
}

PAGES = [
    "Home.py",
    "pages/1_Check_My_Eligibility.py",
    "pages/2_Bulk_Check.py",
    "pages/3_Analytics.py",
    "pages/4_About.py",
]


def test_palette_defines_every_colour() -> None:
    assert {k: v.upper() for k, v in theme.PALETTE.items()} == REQUIRED


def test_status_colour_mapping() -> None:
    assert theme.status_colour("Approved") == REQUIRED["approved"]
    assert theme.status_colour("Rejected") == REQUIRED["rejected"]
    assert theme.status_style("Approved")["tint"] == REQUIRED["approved_tint"]
    assert theme.status_style("Rejected")["tint"] == REQUIRED["rejected_tint"]
    assert theme.status_label("Approved") == "✅ Approved"
    assert theme.status_label("Rejected") == "❌ Rejected"
    with pytest.raises(ValueError):
        theme.status_colour("Maybe")


def test_streamlit_config_matches_theme() -> None:
    config = tomllib.loads((PROJECT_ROOT / ".streamlit" / "config.toml").read_text("utf-8"))
    assert config["client"]["showErrorDetails"] is False
    for key, value in theme.STREAMLIT_THEME.items():
        assert config["theme"][key] == value


def test_text_contrast_meets_wcag_aa() -> None:
    """Body text and small coloured text reach 4.5:1 on the backgrounds they are used on."""
    pairs = [
        (theme.TEXT, theme.BACKGROUND),
        (theme.TEXT, theme.SOFT_PANEL),
        (theme.MUTED, theme.BACKGROUND),
        (theme.MUTED, theme.SOFT_PANEL),
        (theme.TEXT, theme.APPROVED_TINT),
        (theme.TEXT, theme.REJECTED_TINT),
        (theme.TEXT, theme.WARNING_TINT),
        (theme.APPROVED_INK, theme.APPROVED_TINT),
        (theme.REJECTED_INK, theme.REJECTED_TINT),
        (theme.WARNING_INK, theme.WARNING_TINT),
        ("#FFFFFF", theme.PRIMARY_INK),
        ("#FFFFFF", theme.PRIMARY_INK_HOVER),
    ]
    for fg, bg in pairs:
        assert theme.contrast_ratio(fg, bg) >= 4.5, (fg, bg)


def test_status_table_styling_pairs_colour_with_text() -> None:
    frame = theme.status_display_frame(pd.DataFrame({"status": ["Approved", "Rejected"]}))
    assert list(frame["status"]) == ["✅ Approved", "❌ Rejected"]
    html = theme.style_status_column(frame).to_html()
    assert theme.APPROVED_TINT.lower() in html.lower()
    assert theme.REJECTED_TINT.lower() in html.lower()


def test_policy_checks_use_tick_and_cross() -> None:
    rows = pd.DataFrame(
        {"Check": ["A", "B"], "Result": ["Pass", "Fail"], "Details": ["ok", "<bad>"]}
    )
    out = theme.policy_checks_html(rows)
    assert "ll-check-pass" in out and "✓" in out and "ll-check-fail" in out and "✗" in out
    assert "&lt;bad&gt;" in out  # escaped


def test_css_uses_only_theme_colours() -> None:
    css = theme.app_css()
    assert theme.PRIMARY in css and theme.APPROVED in css and theme.REJECTED in css
    assert "@import" not in css and "http" not in css  # no external font downloads


def test_charts_use_theme_colours(clean_df) -> None:
    assert theme.PLOTLY_TEMPLATE_NAME in pio.templates
    fig = charts.distribution_by_status(clean_df, "cibil_score")
    colours = {t.name: t.marker.color for t in fig.data}
    assert colours == {"Approved": theme.APPROVED, "Rejected": theme.REJECTED}
    bar = charts.approval_by_cibil_band(clean_df)
    assert bar.data[0].marker.color == theme.PRIMARY
    assert bar.layout.template.layout.plot_bgcolor == theme.BACKGROUND
    assert bar.layout.template.layout.font.color == theme.TEXT
    reasons = charts.counts_bar({"a": 2}, "t", "", horizontal=True)
    assert reasons.data[0].marker.color == theme.REJECTED


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_with_theme(app_path, artifact, page) -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(Path(app_path) / page), default_timeout=120).run()
    if page.endswith("Bulk_Check.py"):
        at.toggle(key="manager_mode").set_value(True).run()
    assert not at.exception, at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "ll-header" in html and "LoanLens" in html
