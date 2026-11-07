"""Design system: the theme module, status colours, contrast, the logo and every page."""

from __future__ import annotations

import tomllib

import pandas as pd
import plotly.io as pio
import pytest
from app_support import open_page

from loanlens import charts, theme
from loanlens.config import PROJECT_ROOT

REQUIRED = {
    "background": "#FFFFFF",
    "canvas": "#F6F8FC",
    "soft_panel": "#F4F7FE",
    "border": "#E3E9F5",
    "border_strong": "#CBD5E5",
    "primary": "#2E74E9",
    "primary_tint": "#EAF1FD",
    "primary_deep": "#143A8F",
    "indigo": "#5271FF",
    "text": "#0F1B3D",
    "text_soft": "#364260",
    "muted": "#5B6785",
    "approved": "#1E9E5A",
    "approved_tint": "#E8F6EE",
    "rejected": "#D93636",
    "rejected_tint": "#FDECEC",
    "warning": "#B7791F",
    "warning_tint": "#FFF4DB",
}

PAGES = [
    "pages/9_Home.py",
    "pages/0_Sign_In.py",
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
    assert theme.status_label("Approved") == "Approved"  # plain word, no icon
    assert theme.status_label("Rejected") == "Rejected"
    assert "icon" not in theme.status_style("Approved")
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
        # The page canvas, tinted panels and the brand gradients
        (theme.TEXT, theme.CANVAS),
        (theme.MUTED, theme.CANVAS),
        (theme.TEXT_SOFT, theme.CANVAS),
        (theme.MUTED, theme.PRIMARY_TINT),
        (theme.PRIMARY_INK, theme.PRIMARY_TINT),
        (theme.TEXT_SOFT, theme.BACKGROUND),
        *[(theme.ON_BRAND, stop) for stop in theme.GRADIENT_STOPS],
        *[(theme.ON_BRAND_SOFT, stop) for stop in theme.GRADIENT_STOPS],
    ]
    for fg, bg in pairs:
        assert theme.contrast_ratio(fg, bg) >= 4.5, (fg, bg)


def test_status_table_styling_pairs_colour_with_text() -> None:
    frame = theme.status_display_frame(pd.DataFrame({"status": ["Approved", "Rejected"]}))
    assert list(frame["status"]) == ["Approved", "Rejected"]
    html = theme.style_status_column(frame).to_html()
    assert theme.APPROVED_TINT.lower() in html.lower()
    assert theme.REJECTED_TINT.lower() in html.lower()


def test_policy_checks_use_passed_and_failed_words() -> None:
    rows = pd.DataFrame(
        {
            "Check": ["A", "B", "C"],
            "Result": ["Pass", "Fail", "Advisory"],
            "Details": ["ok", "<bad>", "note"],
        }
    )
    out = theme.policy_checks_html(rows)
    assert '<span class="ll-check-status">Passed</span>' in out and "ll-check-pass" in out
    assert '<span class="ll-check-status">Failed</span>' in out and "ll-check-fail" in out
    assert '<span class="ll-check-status">Advisory</span>' in out and "ll-check-advisory" in out
    assert "&lt;bad&gt;" in out  # escaped


def test_css_uses_only_theme_colours() -> None:
    import re

    css = theme.app_css()
    assert theme.PRIMARY in css and theme.APPROVED in css and theme.REJECTED in css
    for name, value in theme.TOKENS.items():
        assert f"{name}: {value};" in css
    # The only external resource is the Inter font from Google Fonts, with system fallbacks.
    assert re.findall(r"https?://[^'\")\s]+", css) == [theme.FONT_URL]
    assert theme.FONT_URL.startswith("https://fonts.googleapis.com/")
    assert css.count("@import") == 1 and css.startswith("@import")
    assert theme.FONT_STACK.startswith('"Inter"') and theme.FONT_STACK.endswith("sans-serif")
    # The shared rules use the tokens, not colour literals.
    assert not re.findall(r"#[0-9A-Fa-f]{6}\b", theme._BASE_CSS)


def test_css_has_focus_reduced_motion_and_mobile_rules() -> None:
    css = theme.app_css()
    assert ":focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (max-width: 640px)" in css


def test_logo_files_match_the_theme() -> None:
    assets = PROJECT_ROOT / "app" / "assets"
    mark = (assets / "logo_mark.svg").read_text(encoding="utf-8").strip()
    wordmark = (assets / "logo_wordmark.svg").read_text(encoding="utf-8").strip()
    assert mark == theme.LOGO_MARK_SVG and wordmark == theme.LOGO_WORDMARK_SVG
    assert mark.startswith("<svg") and "<script" not in mark + wordmark
    assert theme.logo_mark_data_uri().startswith("data:image/svg+xml;base64,")


def test_html_components_escape_text() -> None:
    risky = "<b>x</b>"
    for snippet in (
        theme.hero_html(risky, risky, risky),
        theme.brand_panel_html(risky, risky, [risky]),
        theme.steps_html([(risky, risky)]),
        theme.trust_html([(risky, risky)]),
        theme.header_html(risky),
        theme.meter_html(0.5, 0.5, (0.4, 0.6), True, risky),
    ):
        assert "<b>" not in snippet and "&lt;b&gt;" in snippet


@pytest.mark.parametrize(("p", "width"), [(0.0, "1.0%"), (1.0, "99.0%"), (0.456, "45.6%")])
def test_meter_never_reaches_the_ends(p, width) -> None:
    html = theme.meter_html(p, 0.5, (0.4, 0.6), p >= 0.5, "x")
    assert (
        f'class="ll-meter-fill ll-meter-{"approved" if p >= 0.5 else "rejected"}" '
        f'style="width:{width}"' in html
    )
    assert "0%</span>" not in html.replace("Cut-off 50%", "")  # no 0% or 100% label
    assert "Cut-off 50%" in html


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
    at = open_page(page).run()
    assert not at.exception, at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "--ll-primary" in html  # the design system is applied
    assert "LoanLens" in html
    if page.endswith(("9_Home.py", "0_Sign_In.py")):
        assert "ll-hero-brand" in html  # the hero or the sign-in brand panel
    else:
        assert "ll-header" in html  # brand row above the page title
