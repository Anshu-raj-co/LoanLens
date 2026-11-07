"""LoanLens design system: colour tokens, the shared app CSS, HTML components and Plotly.

This is the only place colours, fonts, radii, shadows and spacing are defined. The Streamlit
pages (through ``apply_theme`` in ``app/ui_common.py``), ``charts.py`` and the notebooks
import from here, so the whole product looks the same. Styling only: nothing here affects a
decision.
"""

from __future__ import annotations

import base64
import html

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

# ---- Palette -------------------------------------------------------------------------------
# Surfaces and neutrals
BACKGROUND = "#FFFFFF"  # cards, inputs, tables and charts
BACKGROUND_RGB = "rgb(255, 255, 255)"  # same colour; see style_figure
CANVAS = "#F6F8FC"  # the page behind the cards
SOFT_PANEL = "#F4F7FE"  # tinted panels, sidebar hover, info callouts
BORDER = "#E3E9F5"
BORDER_STRONG = "#CBD5E5"
TEXT = "#0F1B3D"  # navy body text
TEXT_SOFT = "#364260"  # secondary body text
MUTED = "#5B6785"  # captions and labels (AA on white, canvas and soft panel)

# Brand: royal blue with a deeper shade for gradients and an indigo accent
PRIMARY = "#2E74E9"
PRIMARY_TINT = "#EAF1FD"
PRIMARY_DEEP = "#143A8F"
INDIGO = "#5271FF"

# Semantic: green = Approved, red = Rejected, amber = Borderline
APPROVED = "#1E9E5A"
APPROVED_TINT = "#E8F6EE"
REJECTED = "#D93636"
REJECTED_TINT = "#FDECEC"
WARNING = "#B7791F"
WARNING_TINT = "#FFF4DB"

# Darker "ink" shades of the brand colours, used only for small coloured text on a tint (or
# white text on blue) so it meets WCAG AA 4.5:1. The brand colours above are used for
# borders, icons, chart marks and large headings (3:1 is enough there).
PRIMARY_INK = "#1D5FCF"
PRIMARY_INK_HOVER = "#174CA8"
APPROVED_INK = "#157A45"
REJECTED_INK = "#B42318"
WARNING_INK = "#8A5A12"
NEUTRAL = "#6B7280"
NEUTRAL_TINT = "#F1F3F7"
NEUTRAL_INK = "#4B5563"
ON_BRAND = "#FFFFFF"  # text on the blue gradients
ON_BRAND_SOFT = "#DCE7FF"  # secondary text on the blue gradients

# The hero and sign-in gradient (every stop keeps white text above 4.5:1).
GRADIENT_STOPS = (PRIMARY_INK, "#1846AE", PRIMARY_DEEP)

PALETTE: dict[str, str] = {
    "background": BACKGROUND,
    "canvas": CANVAS,
    "soft_panel": SOFT_PANEL,
    "border": BORDER,
    "border_strong": BORDER_STRONG,
    "primary": PRIMARY,
    "primary_tint": PRIMARY_TINT,
    "primary_deep": PRIMARY_DEEP,
    "indigo": INDIGO,
    "text": TEXT,
    "text_soft": TEXT_SOFT,
    "muted": MUTED,
    "approved": APPROVED,
    "approved_tint": APPROVED_TINT,
    "rejected": REJECTED,
    "rejected_tint": REJECTED_TINT,
    "warning": WARNING,
    "warning_tint": WARNING_TINT,
}

# Inter is loaded from Google Fonts; every platform falls back to a good system font when it
# cannot be loaded (offline, in a locked-down network or in Docker without internet).
FONT_NAME = "Inter"
FONT_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
FONT_STACK = (
    '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, '
    '"Noto Sans", sans-serif'
)

# ---- Status -> colour ----------------------------------------------------------------------
STATUS_COLOURS = {"Approved": APPROVED, "Rejected": REJECTED}
_TONES: dict[str, tuple[str, str, str]] = {  # tone -> (brand colour, tint, ink)
    "approved": (APPROVED, APPROVED_TINT, APPROVED_INK),
    "rejected": (REJECTED, REJECTED_TINT, REJECTED_INK),
    "warning": (WARNING, WARNING_TINT, WARNING_INK),
    "primary": (PRIMARY, SOFT_PANEL, PRIMARY_INK),
    "neutral": (NEUTRAL, NEUTRAL_TINT, NEUTRAL_INK),
}


def status_colour(status: str) -> str:
    """Brand colour for a decision status: green for Approved, red for Rejected."""
    try:
        return STATUS_COLOURS[status]
    except KeyError:
        raise ValueError(f"Unknown status: {status!r}") from None


def status_style(status: str) -> dict[str, str]:
    """Colour, tint and readable text colour for a status."""
    tone = "approved" if status == "Approved" else "rejected"
    colour, tint, ink = _TONES[tone] if status in STATUS_COLOURS else _TONES["neutral"]
    return {"colour": colour, "tint": tint, "ink": ink}


def status_label(status: str) -> str:
    """Plain-text status label, e.g. 'Approved'. The word always appears with the colour."""
    return str(status).strip()


# ---- Accessibility -------------------------------------------------------------------------
def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.x contrast ratio between two hex colours (1 to 21)."""
    a, b = _luminance(foreground), _luminance(background)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# ---- Logo ----------------------------------------------------------------------------------
# The logo mark: a magnifying lens with a check mark on a blue tile. It is a vector image (not
# an emoji); app/assets/logo_mark.svg holds the same markup (a test keeps them equal).
LOGO_MARK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
    '<defs><linearGradient id="llg" x1="0" y1="0" x2="1" y2="1">'
    f'<stop offset="0" stop-color="{PRIMARY}"/><stop offset="1" stop-color="{PRIMARY_DEEP}"/>'
    "</linearGradient></defs>"
    '<rect width="64" height="64" rx="16" fill="url(#llg)"/>'
    '<circle cx="28" cy="28" r="13" fill="none" stroke="#FFFFFF" stroke-width="5"/>'
    '<path d="M37.5 37.5 L47 47" stroke="#FFFFFF" stroke-width="6" stroke-linecap="round"/>'
    '<path d="M22 28.5 L26.5 33 L34 24" fill="none" stroke="#FFFFFF" stroke-width="3.6" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)


# The sidebar logo: the mark followed by the product name (system fonts inside the image).
LOGO_WORDMARK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="172" height="40" viewBox="0 0 172 40">'
    '<g transform="scale(0.625)">' + LOGO_MARK_SVG.split(">", 1)[1].rsplit("</svg>", 1)[0] + "</g>"
    '<text x="50" y="28" font-family="Inter, Segoe UI, Roboto, Arial, sans-serif" '
    f'font-size="22" font-weight="800" letter-spacing="-0.5" fill="{TEXT}">LoanLens</text>'
    "</svg>"
)


def logo_mark_data_uri() -> str:
    """The logo mark as a ``data:`` URI for an ``<img>`` tag."""
    encoded = base64.b64encode(LOGO_MARK_SVG.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _logo_img(size: int, extra_class: str = "") -> str:
    return (
        f'<img class="ll-logo-mark {extra_class}" src="{logo_mark_data_uri()}" width="{size}" '
        f'height="{size}" alt="">'
    )


# ---- HTML snippets (all user text escaped) -------------------------------------------------
def pill_html(text: str, tone: str = "warning") -> str:
    """A small rounded label, e.g. the amber borderline pill."""
    return f'<span class="ll-pill ll-pill-{tone}">{html.escape(text)}</span>'


def header_html(name: str) -> str:
    """The brand row at the top of every page: the logo mark and the product name only."""
    return (
        f'<div class="ll-header">{_logo_img(30)}'
        f'<span class="ll-brand">{html.escape(name)}</span></div>'
    )


def hero_html(eyebrow: str, title: str, line: str) -> str:
    """The Home hero: logo mark, product name, a greeting and the one-line value proposition."""
    return (
        '<div class="ll-hero-body">'
        f'<div class="ll-hero-brand">{_logo_img(44, "ll-logo-hero")}'
        f'<span class="ll-hero-name">{html.escape(title)}</span></div>'
        f'<p class="ll-hero-eyebrow">{html.escape(eyebrow)}</p>'
        f'<p class="ll-hero-line">{html.escape(line)}</p>'
        "</div>"
    )


def brand_panel_html(title: str, line: str, points: list[str]) -> str:
    """The gradient brand panel beside the sign-in card (stacks above it on small screens)."""
    items = "".join(f"<li>{html.escape(p)}</li>" for p in points)
    return (
        '<div class="ll-brand-panel">'
        f'<div class="ll-hero-brand">{_logo_img(48, "ll-logo-hero")}'
        f'<span class="ll-hero-name">{html.escape(title)}</span></div>'
        f'<p class="ll-hero-line">{html.escape(line)}</p>'
        f'<ul class="ll-brand-points">{items}</ul>'
        "</div>"
    )


def steps_html(steps: list[tuple[str, str]]) -> str:
    """A numbered step flow (timeline) from ``(title, text)`` pairs."""
    items = "".join(
        f'<li class="ll-step"><span class="ll-step-num" aria-hidden="true">{i}</span>'
        f'<div class="ll-step-body"><p class="ll-step-title">{html.escape(title)}</p>'
        f'<p class="ll-step-text">{html.escape(text)}</p></div></li>'
        for i, (title, text) in enumerate(steps, start=1)
    )
    return f'<ol class="ll-steps">{items}</ol>'


def trust_html(items: list[tuple[str, str]]) -> str:
    """A row of short trust statements from ``(title, text)`` pairs."""
    cells = "".join(
        '<div class="ll-trust-item"><span class="ll-trust-tick" aria-hidden="true"></span>'
        f'<div><p class="ll-trust-title">{html.escape(title)}</p>'
        f'<p class="ll-trust-text">{html.escape(text)}</p></div></div>'
        for title, text in items
    )
    return f'<div class="ll-trust">{cells}</div>'


def meter_html(
    probability: float, threshold: float, band: tuple[float, float], approved: bool, label: str
) -> str:
    """A confidence meter: the model score as a bar, with the cut-off and the borderline band.

    The bar never reaches either end (as the shown percentage never reads 0% or 100%). Display
    only: the numbers come from the decision result and the policy profile.
    """
    pct = min(max(probability * 100.0, 1.0), 99.0)
    low, high = (min(max(v * 100.0, 0.0), 100.0) for v in band)
    cut = min(max(threshold * 100.0, 0.0), 100.0)
    tone = "approved" if approved else "rejected"
    return (
        f'<div class="ll-meter" role="img" aria-label="{html.escape(label)}">'
        '<div class="ll-meter-track">'
        f'<div class="ll-meter-band" style="left:{low:.1f}%;width:{max(high - low, 0):.1f}%">'
        "</div>"
        f'<div class="ll-meter-fill ll-meter-{tone}" style="width:{pct:.1f}%"></div>'
        f'<div class="ll-meter-cut" style="left:{cut:.1f}%"></div>'
        "</div>"
        '<div class="ll-meter-scale"><span>Less likely</span>'
        f"<span>Cut-off {threshold:.0%}</span><span>More likely</span></div>"
        "</div>"
    )


# ---- Tables --------------------------------------------------------------------------------
# Above this many rows the results table is shown as plain status text (no cell colours), so
# a very large upload stays fast. Display setting only.
STYLED_ROWS_LIMIT = 5_000


def status_display_frame(frame: pd.DataFrame, column: str = "status") -> pd.DataFrame:
    """Copy of a results frame for display, with the status shown as plain text."""
    shown = frame.copy()
    if column in shown.columns:
        shown[column] = shown[column].map(lambda s: status_label(str(s)))
    return shown


def style_status_column(frame: pd.DataFrame, column: str = "status"):  # -> Styler
    """Pandas Styler colouring a status column ('Approved' or 'Rejected').

    Approved cells get the green tint with dark-green text, Rejected the red tint with
    dark-red text. Display only: the downloaded CSV is built from the raw results.
    """

    def cell(value: object) -> str:
        text = str(value)
        if "Approved" in text:
            return f"background-color: {APPROVED_TINT}; color: {APPROVED_INK}; font-weight: 600"
        if "Rejected" in text:
            return f"background-color: {REJECTED_TINT}; color: {REJECTED_INK}; font-weight: 600"
        return ""

    styler = frame.style
    if column in frame.columns:
        styler = styler.map(cell, subset=[column])
    return styler


# ---- Plotly --------------------------------------------------------------------------------
PLOTLY_TEMPLATE_NAME = "loanlens"
SEQUENCE = [PRIMARY, INDIGO, APPROVED, WARNING, REJECTED, MUTED]
# Diverging scale for approval-rate heatmaps: red (0%) through amber to green (100%).
RATE_SCALE = [[0.0, REJECTED], [0.5, "#F2C66D"], [1.0, APPROVED]]


def plotly_template() -> go.layout.Template:
    """White background, light grid, navy text, the Inter font stack, brand colour sequence."""
    axis = {
        "gridcolor": BORDER,
        "linecolor": BORDER,
        "zerolinecolor": BORDER,
        "tickfont": {"color": MUTED},
        "title": {"font": {"color": TEXT_SOFT}},
        "automargin": True,
    }
    return go.layout.Template(
        layout={
            "font": {"family": FONT_STACK, "color": TEXT, "size": 13},
            "title": {
                "font": {"family": FONT_STACK, "color": TEXT, "size": 16},
                "x": 0.0,
                "xanchor": "left",
            },
            "paper_bgcolor": BACKGROUND,
            "plot_bgcolor": BACKGROUND,
            "colorway": SEQUENCE,
            "xaxis": axis,
            "yaxis": axis,
            "legend": {"font": {"color": TEXT}, "bgcolor": "rgba(255,255,255,0)"},
            "hoverlabel": {
                "bgcolor": BACKGROUND,
                "bordercolor": BORDER,
                "font": {"family": FONT_STACK, "color": TEXT},
            },  # fmt: skip
            "colorscale": {"sequential": RATE_SCALE},
            "margin": {"l": 10, "r": 10, "t": 56, "b": 10},
            "bargap": 0.35,
        }
    )


def style_figure(fig: go.Figure) -> go.Figure:
    """Apply the LoanLens template and pin its key colours on the figure itself.

    Pinning matters because Streamlit's front end replaces some colours with its own theme
    colours. The backgrounds are written as ``rgb(...)`` (the same white as ``BACKGROUND``)
    because Streamlit swapped the hex spelling for the soft-panel colour (decisions_log D-050).
    """
    axis = {"gridcolor": BORDER, "linecolor": BORDER, "zerolinecolor": BORDER}
    fig.update_layout(
        template=plotly_template(),
        paper_bgcolor=BACKGROUND_RGB,
        plot_bgcolor=BACKGROUND_RGB,
        font={"family": FONT_STACK, "color": TEXT},
    )
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


def register_plotly_template(make_default: bool = True) -> str:
    """Register the LoanLens Plotly template (and make it the default). Returns its name."""
    pio.templates[PLOTLY_TEMPLATE_NAME] = plotly_template()
    if make_default:
        pio.templates.default = PLOTLY_TEMPLATE_NAME
    return PLOTLY_TEMPLATE_NAME


# ---- Streamlit -----------------------------------------------------------------------------
# Native theme options (also written in .streamlit/config.toml; a test keeps them equal).
# Streamlit 1.40 offers only "sans serif", "serif" or "monospace" as the theme font, so Inter
# is applied by the CSS below.
STREAMLIT_THEME = {
    "base": "light",
    "primaryColor": PRIMARY,
    "backgroundColor": BACKGROUND,
    "secondaryBackgroundColor": SOFT_PANEL,
    "textColor": TEXT,
}

# Design tokens, emitted as CSS variables on :root.
TOKENS: dict[str, str] = {
    "--ll-font": FONT_STACK,
    "--ll-bg": BACKGROUND,
    "--ll-canvas": CANVAS,
    "--ll-panel": SOFT_PANEL,
    "--ll-border": BORDER,
    "--ll-border-strong": BORDER_STRONG,
    "--ll-text": TEXT,
    "--ll-text-soft": TEXT_SOFT,
    "--ll-muted": MUTED,
    "--ll-primary": PRIMARY,
    "--ll-primary-tint": PRIMARY_TINT,
    "--ll-primary-ink": PRIMARY_INK,
    "--ll-primary-hover": PRIMARY_INK_HOVER,
    "--ll-primary-deep": PRIMARY_DEEP,
    "--ll-indigo": INDIGO,
    "--ll-approved": APPROVED,
    "--ll-approved-tint": APPROVED_TINT,
    "--ll-approved-ink": APPROVED_INK,
    "--ll-rejected": REJECTED,
    "--ll-rejected-tint": REJECTED_TINT,
    "--ll-rejected-ink": REJECTED_INK,
    "--ll-warning": WARNING,
    "--ll-warning-tint": WARNING_TINT,
    "--ll-warning-ink": WARNING_INK,
    "--ll-on-brand": ON_BRAND,
    "--ll-on-brand-soft": ON_BRAND_SOFT,
    "--ll-gradient": (
        f"linear-gradient(135deg, {GRADIENT_STOPS[0]} 0%, {GRADIENT_STOPS[1]} 55%, "
        f"{GRADIENT_STOPS[2]} 100%)"
    ),
    "--ll-radius-sm": "10px",
    "--ll-radius": "14px",
    "--ll-radius-lg": "18px",
    "--ll-space-1": "0.25rem",
    "--ll-space-2": "0.5rem",
    "--ll-space-3": "0.75rem",
    "--ll-space-4": "1rem",
    "--ll-space-5": "1.5rem",
    "--ll-space-6": "2rem",
    "--ll-shadow-sm": "0 1px 2px rgba(15, 27, 61, 0.05), 0 1px 3px rgba(15, 27, 61, 0.05)",
    "--ll-shadow-md": "0 6px 16px rgba(15, 27, 61, 0.08)",
    "--ll-shadow-lg": "0 14px 34px rgba(15, 27, 61, 0.13)",
    "--ll-shadow-brand": "0 10px 24px rgba(29, 95, 207, 0.28)",
    "--ll-focus": "0 0 0 3px rgba(46, 116, 233, 0.35)",
    "--ll-ease": "cubic-bezier(0.2, 0.7, 0.2, 1)",
}

# Every rule below uses only the variables above (no colour literals), so the palette lives in
# one place. Streamlit test ids are used where they exist; keyed containers get the class
# ``st-key-<key>`` and are styled through that.
_BASE_CSS = """
/* ---- Base and typography ---- */
html, body, .stApp { font-family: var(--ll-font); }
/* Text elements only: icon spans (and the spans that wrap them) keep the icon font. */
.stApp :where(p, li, label, a, input, textarea, select, small, strong, em, th, td,
  h1, h2, h3, h4, h5, h6, [data-testid="stMarkdownContainer"],
  [data-testid="stSidebarNavLink"] > span:last-child, [data-testid="stNavSectionHeader"],
  [data-baseweb="select"] div, [data-baseweb="tab"]) { font-family: var(--ll-font); }
/* Streamlit sizes element boxes in pixels; inside padded cards they must not overflow. */
[data-testid="stElementContainer"], [data-testid="stElementContainer"] > div {
  max-width: 100%; }
[data-testid="stHeaderActionElements"] { display: none; }
.stApp { background: var(--ll-canvas); color: var(--ll-text); }
[data-testid="stMain"] { background: var(--ll-canvas); }
[data-testid="stMainBlockContainer"] { max-width: 1240px; padding: 3.4rem 2.4rem 3rem; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stDecoration"] { display: none; }
[data-testid="stAppDeployButton"], [data-testid="stStatusWidget"] [kind="header"],
footer { display: none !important; }
.stMarkdown p, .stMarkdown li { font-size: 1rem; line-height: 1.65; color: var(--ll-text); }
h1, h2, h3, h4, h5 { color: var(--ll-text); letter-spacing: -0.02em; font-family: var(--ll-font); }
h1 { font-size: 2.15rem !important; font-weight: 800 !important; line-height: 1.2 !important;
  padding-bottom: 0.25rem !important; }
h2 { font-size: 1.5rem !important; font-weight: 750 !important; margin-top: 0.9rem; }
h3 { font-size: 1.22rem !important; font-weight: 700 !important; }
h4 { font-size: 1.05rem !important; font-weight: 700 !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p, .stCaption {
  color: var(--ll-muted) !important; font-size: 0.875rem; line-height: 1.55; }
a, a:visited { color: var(--ll-primary-ink); }
code { color: var(--ll-text-soft); background: var(--ll-panel); border-radius: 6px; }
hr { border-color: var(--ll-border) !important; }
*:focus-visible { outline: none; box-shadow: var(--ll-focus) !important; border-radius: 8px; }

/* ---- Brand row and page header ---- */
.ll-header { display: flex; align-items: center; gap: 0.6rem; margin: 0 0 0.35rem 0; }
.ll-header .ll-logo-mark { border-radius: 9px; box-shadow: var(--ll-shadow-sm); }
.ll-brand { font-size: 1.05rem; font-weight: 800; letter-spacing: -0.01em;
  color: var(--ll-text); }
.st-key-page_subtitle p { color: var(--ll-muted) !important; font-size: 1.02rem;
  margin-top: -0.35rem; }

/* ---- Sidebar ---- */
[data-testid="stSidebar"] { background: var(--ll-bg); border-right: 1px solid var(--ll-border); }
[data-testid="stSidebarHeader"] { padding-bottom: 0.4rem; }
[data-testid="stLogo"] { height: 2.1rem; max-width: 12rem; }
[data-testid="stSidebarNavItems"] { padding-top: 0.2rem; }
[data-testid="stNavSectionHeader"], [data-testid="stSidebarNavSeparator"] + div header {
  color: var(--ll-muted); font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; }
[data-testid="stSidebarNavLink"] { border-radius: var(--ll-radius-sm); margin: 1px 0.25rem;
  padding: 0.35rem 0.7rem; transition: background 0.15s var(--ll-ease); }
[data-testid="stSidebarNavLink"] span { color: var(--ll-text-soft); font-weight: 550; }
[data-testid="stSidebarNavLink"]:hover { background: var(--ll-panel); }
[data-testid="stSidebarNavLink"][aria-current="page"] { background: var(--ll-primary-tint); }
[data-testid="stSidebarNavLink"][aria-current="page"] span { color: var(--ll-primary-ink);
  font-weight: 700; }
.st-key-user_card { background: var(--ll-panel); border: 1px solid var(--ll-border);
  border-radius: var(--ll-radius); padding: 0.9rem 0.95rem; gap: 0.4rem; box-sizing: border-box; }
.st-key-user_card [data-testid="stMarkdownContainer"], .st-key-user_card .stMarkdown,
.st-key-user_card [data-testid="stElementContainer"] { margin: 0 !important; }
.st-key-user_card [data-testid="stCaptionContainer"] { margin-bottom: 0.35rem !important; }
.st-key-user_card p { margin: 0 !important; overflow-wrap: anywhere; font-size: 0.92rem; }
.st-key-user_card a { color: var(--ll-text) !important; text-decoration: none;
  pointer-events: none; }
.st-key-user_card .ll-avatar { display: inline-flex; align-items: center; justify-content: center;
  width: 2.1rem; height: 2.1rem; border-radius: 999px; background: var(--ll-gradient);
  color: var(--ll-on-brand); font-weight: 800; margin-bottom: 0.2rem; }

/* ---- Cards and containers ---- */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {
  border-radius: var(--ll-radius); }
[data-testid="stVerticalBlockBorderWrapper"][class] { border-color: var(--ll-border); }
div[data-testid="stVerticalBlockBorderWrapper"] > div[style*="border"] {
  border-color: var(--ll-border) !important; }
[data-testid="stForm"] { background: var(--ll-bg); border: 1px solid var(--ll-border);
  border-radius: var(--ll-radius-lg); padding: 1.4rem 1.4rem 1.1rem;
  box-shadow: var(--ll-shadow-sm); }
[data-testid="stExpander"] details { border: 1px solid var(--ll-border);
  border-radius: var(--ll-radius);
  background: var(--ll-bg); box-shadow: var(--ll-shadow-sm); }
[data-testid="stExpander"] summary { font-weight: 650; color: var(--ll-text); }
[data-testid="stExpander"] summary:hover { color: var(--ll-primary-ink); }
[data-testid="stExpander"] summary:hover svg { fill: var(--ll-primary-ink); }
[class*="st-key-surface"] { background: var(--ll-bg); border: 1px solid var(--ll-border);
  border-radius: var(--ll-radius-lg); padding: 1.15rem 1.25rem; box-shadow: var(--ll-shadow-sm);
  box-sizing: border-box; }

/* ---- Buttons and links ---- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button,
[data-testid="stPageLink"] a {
  border-radius: var(--ll-radius-sm); font-weight: 650; min-height: 2.6rem;
  transition: transform 0.15s var(--ll-ease), box-shadow 0.15s var(--ll-ease),
    background 0.15s var(--ll-ease), border-color 0.15s var(--ll-ease); }
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primaryFormSubmit"],
  .stFormSubmitButton > button[kind="primary"] {
  background: var(--ll-primary-ink); border: 1px solid var(--ll-primary-ink);
  color: var(--ll-on-brand); padding: 0.55rem 1.3rem; box-shadow: var(--ll-shadow-sm); }
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primaryFormSubmit"]:hover {
  background: var(--ll-primary-hover); border-color: var(--ll-primary-hover);
  color: var(--ll-on-brand); box-shadow: var(--ll-shadow-brand); transform: translateY(-1px); }
.stButton > button[kind="secondary"], .stDownloadButton > button[kind="secondary"],
.stFormSubmitButton > button[kind="secondaryFormSubmit"] {
  border: 1px solid var(--ll-border-strong); color: var(--ll-primary-ink);
  background: var(--ll-bg); }
.stButton > button[kind="secondary"]:hover, .stDownloadButton > button[kind="secondary"]:hover,
.stFormSubmitButton > button[kind="secondaryFormSubmit"]:hover {
  background: var(--ll-primary-tint); border-color: var(--ll-primary);
  color: var(--ll-primary-ink);
  transform: translateY(-1px); }
.stButton > button:active, .stDownloadButton > button:active,
.stFormSubmitButton > button:active, [data-testid="stPageLink"] a:active {
  transform: translateY(0) scale(0.99); box-shadow: none; }
.stButton > button:focus-visible, .stDownloadButton > button:focus-visible,
.stFormSubmitButton > button:focus-visible, [data-testid="stPageLink"] a:focus-visible {
  box-shadow: var(--ll-focus) !important; }
[data-testid="stPageLink"] a { display: inline-flex; align-items: center; padding: 0.4rem 0.8rem; }
[data-testid="stPageLink"] a:hover { background: var(--ll-primary-tint); }
[data-testid="stPageLink"] a span, [data-testid="stPageLink"] a p { color: var(--ll-primary-ink);
  font-weight: 650; }

/* ---- Inputs ---- */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div,
[data-baseweb="textarea"] { background: var(--ll-bg) !important;
  border-radius: var(--ll-radius-sm) !important; }
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {
  border: 1px solid var(--ll-border-strong) !important; transition: border-color 0.15s,
  box-shadow 0.15s; }
[data-baseweb="input"]:hover, [data-baseweb="select"] > div:hover {
  border-color: var(--ll-primary) !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within {
  border-color: var(--ll-primary) !important; box-shadow: var(--ll-focus); }
[data-baseweb="input"] input, [data-baseweb="base-input"] input {
  background: transparent !important;
  color: var(--ll-text); font-size: 1rem; }
[data-testid="stNumberInput"] button { background: var(--ll-panel); border-color: transparent; }
[data-testid="stNumberInput"] button:hover { background: var(--ll-primary-tint);
  color: var(--ll-primary-ink); }
[data-testid="stWidgetLabel"] p { font-weight: 600; color: var(--ll-text); font-size: 0.92rem; }

/* ---- Segmented control: the Sign In role selector (a horizontal radio) ---- */
.st-key-signin_card [data-testid="stRadio"] [role="radiogroup"] { display: flex; width: 100%;
  gap: 4px; padding: 4px; background: var(--ll-panel); border: 1px solid var(--ll-border);
  border-radius: 12px; box-sizing: border-box; flex-wrap: nowrap; }
.st-key-signin_card [data-testid="stRadio"] label { flex: 1 1 0; margin: 0 !important;
  justify-content: center; border-radius: 9px; padding: 0.5rem 0.6rem; cursor: pointer;
  box-sizing: border-box; border: 1px solid transparent; min-width: 0;
  transition: background 0.15s var(--ll-ease), box-shadow 0.15s var(--ll-ease); }
.st-key-signin_card [data-testid="stRadio"] label > div:first-child { display: none; }
.st-key-signin_card [data-testid="stRadio"] label p { font-weight: 650; color: var(--ll-text-soft);
  font-size: 0.95rem; white-space: nowrap; }
.st-key-signin_card [data-testid="stRadio"] label:hover { background: var(--ll-bg); }
.st-key-signin_card [data-testid="stRadio"] label:has(input:checked) { background: var(--ll-bg);
  box-shadow: var(--ll-shadow-sm); border-color: var(--ll-border); }
.st-key-signin_card [data-testid="stRadio"] label:has(input:checked) p {
  color: var(--ll-primary-ink); }
.st-key-signin_card [data-testid="stRadio"] label:has(input:focus-visible) {
  box-shadow: var(--ll-focus); }

/* ---- Tabs ---- */
.stTabs [data-baseweb="tab-list"] { gap: 0.25rem; border-bottom: 1px solid var(--ll-border); }
.stTabs [data-baseweb="tab"] { border-radius: 10px 10px 0 0; padding: 0.55rem 1rem;
  font-weight: 650; color: var(--ll-muted); transition: color 0.15s, background 0.15s; }
.stTabs [data-baseweb="tab"]:hover { color: var(--ll-primary-ink);
  background: var(--ll-primary-tint); }
.stTabs [aria-selected="true"] { color: var(--ll-primary-ink); }
.stTabs [aria-selected="true"] p { color: var(--ll-primary-ink); }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--ll-primary); height: 3px;
  border-radius: 3px; }
.stTabs [data-baseweb="tab-border"] { display: none; }

/* ---- Alerts and callouts: tint, coloured edge, navy text ---- */
[data-testid="stAlertContainer"] { border-radius: var(--ll-radius); color: var(--ll-text);
  border: 1px solid var(--ll-border); }
[data-testid="stAlertContainer"] p, [data-testid="stAlertContainer"] li { color: var(--ll-text); }
[data-testid="stAlertContentSuccess"] svg,
  [data-testid="stAlertContentSuccess"] [data-testid="stIconMaterial"] {
  color: var(--ll-approved-ink); }
[data-testid="stAlertContentError"] [data-testid="stIconMaterial"] {
  color: var(--ll-rejected-ink); }
[data-testid="stAlertContentWarning"] [data-testid="stIconMaterial"] {
  color: var(--ll-warning-ink); }
[data-testid="stAlertContentInfo"] [data-testid="stIconMaterial"] { color: var(--ll-primary-ink); }

/* ---- Metric cards ---- */
[data-testid="stMetric"] { background: var(--ll-bg); border: 1px solid var(--ll-border);
  border-radius: var(--ll-radius); padding: 0.95rem 1.1rem; box-shadow: var(--ll-shadow-sm);
  transition: box-shadow 0.2s var(--ll-ease), transform 0.2s var(--ll-ease); }
[data-testid="stMetric"]:hover { box-shadow: var(--ll-shadow-md); }
[data-testid="stMetricLabel"] p { color: var(--ll-muted); font-weight: 650; font-size: 0.82rem;
  text-transform: uppercase; letter-spacing: 0.04em; }
[data-testid="stMetricValue"] { color: var(--ll-text); font-weight: 800; letter-spacing: -0.02em; }

/* ---- Tables ---- */
[data-testid="stDataFrame"], [data-testid="stTable"] { border: 1px solid var(--ll-border);
  border-radius: var(--ll-radius); overflow: hidden; box-shadow: var(--ll-shadow-sm);
  background: var(--ll-bg); }

/* ---- Charts: white cards on the canvas ---- */
[data-testid="stPlotlyChart"] { background: var(--ll-bg); border: 1px solid var(--ll-border);
  border-radius: var(--ll-radius); padding: 0.6rem 0.7rem 0.3rem; box-shadow: var(--ll-shadow-sm);
  box-sizing: border-box; }

/* ---- File uploader ---- */
[data-testid="stFileUploaderDropzone"] { background: var(--ll-primary-tint);
  border: 2px dashed var(--ll-primary); border-radius: var(--ll-radius); padding: 1.3rem;
  transition: background 0.15s, border-color 0.15s; }
[data-testid="stFileUploaderDropzone"]:hover { background: var(--ll-panel);
  border-color: var(--ll-primary-ink); }
[data-testid="stFileUploaderDropzoneInstructions"] span { color: var(--ll-text-soft); }
[data-testid="stFileUploaderDropzone"] button { border-radius: var(--ll-radius-sm);
  border: 1px solid var(--ll-primary); color: var(--ll-primary-ink); background: var(--ll-bg);
  font-weight: 650; }

/* ---- Progress ---- */
[data-testid="stProgress"] > div > div > div { background-color: var(--ll-border) !important;
  border-radius: 999px; }
[data-testid="stProgress"] > div > div > div > div { background: var(--ll-gradient) !important;
  border-radius: 999px; }

/* ---- Pills ---- */
.ll-pill { display: inline-flex; align-items: center; gap: 0.35rem; border-radius: 999px;
  padding: 0.3rem 0.85rem; font-size: 0.9rem; font-weight: 700; border: 1px solid; }

/* ---- Home: hero ---- */
.st-key-hero { background: var(--ll-gradient); border-radius: 22px; padding: 2.4rem 2.6rem 2.2rem;
  box-shadow: var(--ll-shadow-brand); position: relative; overflow: hidden;
  box-sizing: border-box; }
.st-key-hero::after { content: ""; position: absolute; right: -120px; top: -140px; width: 420px;
  height: 420px; border-radius: 50%; background: radial-gradient(circle, rgba(82, 113, 255, 0.55),
  rgba(82, 113, 255, 0) 70%); pointer-events: none; }
.st-key-hero > div { position: relative; z-index: 1; }
.ll-hero-brand { display: flex; align-items: center; gap: 0.75rem; }
.ll-logo-hero { border-radius: 12px; box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.35); }
.ll-hero-name { color: var(--ll-on-brand); font-size: 2.5rem; font-weight: 800;
  letter-spacing: -0.03em; line-height: 1.1; }
.ll-hero-eyebrow { color: var(--ll-on-brand) !important; font-weight: 700;
  font-size: 1.1rem !important;
  margin: 1.1rem 0 0.2rem 0; }
.ll-hero-line { color: var(--ll-on-brand-soft) !important; font-size: 1.12rem !important;
  max-width: 44rem; margin: 0 0 0.4rem 0; line-height: 1.6; }
.st-key-hero [data-testid="stPageLink"] a { background: var(--ll-bg); color: var(--ll-primary-ink);
  padding: 0.6rem 1.25rem; border-radius: 12px; box-shadow: var(--ll-shadow-md);
  margin-top: 0.4rem; }
.st-key-hero [data-testid="stPageLink"] a:hover { transform: translateY(-2px);
  background: var(--ll-bg);
  box-shadow: var(--ll-shadow-lg); }

/* ---- Home: feature cards ---- */
[data-testid="stHorizontalBlock"]:has([class*="st-key-feature_"]) { align-items: stretch; }
[data-testid="stColumn"]:has(> div > [data-testid="stVerticalBlock"]
  > [class*="st-key-feature_"]) > div,
[data-testid="stColumn"]:has([class*="st-key-feature_"]) > div
  > [data-testid="stVerticalBlock"] {
  height: 100%; }
[class*="st-key-feature_"] { background: var(--ll-bg); border: 1px solid var(--ll-border);
  border-radius: var(--ll-radius-lg); padding: 1.3rem 1.3rem 1.1rem; height: 100%;
  min-height: 15rem;
  box-shadow: var(--ll-shadow-sm); box-sizing: border-box; justify-content: space-between;
  transition: transform 0.2s var(--ll-ease), box-shadow 0.2s var(--ll-ease), border-color 0.2s; }
[class*="st-key-feature_"]:hover { transform: translateY(-3px); box-shadow: var(--ll-shadow-lg);
  border-color: var(--ll-primary); }
[class*="st-key-feature_"] h4 { margin: 0.25rem 0 0 0; padding: 0; }
[class*="st-key-feature_"] p { color: var(--ll-text-soft); font-size: 0.95rem; }
[class*="st-key-fticon_"] { width: 2.9rem !important; height: 2.9rem; flex: 0 0 auto;
  border-radius: 12px; display: flex;
  align-items: center; justify-content: center; background: var(--ll-primary-tint); }
[class*="st-key-fticon_"] [data-testid="stMarkdownContainer"] p { margin: 0; line-height: 1; }
[class*="st-key-fticon_"] [data-testid="stElementContainer"] { width: auto !important; }
[class*="st-key-fticon_"] [role="img"] { color: var(--ll-primary-ink); font-size: 1.55rem; }
[class*="st-key-fticon_"] [data-testid="stIconMaterial"] { color: var(--ll-primary-ink);
  font-size: 1.6rem; }
[class*="st-key-feature_"] [data-testid="stPageLink"] { margin-top: auto; width: 100%; }
[class*="st-key-feature_"] [data-testid="stPageLink"] > div { width: 100%; max-width: 100%; }
[class*="st-key-feature_"] [data-testid="stPageLink-NavLink"] { max-width: 100%; }
[class*="st-key-feature_"] [data-testid="stPageLink"] a { width: 100%; max-width: 100%;
  justify-content: center;
  background: var(--ll-primary-ink); box-sizing: border-box; }
[class*="st-key-feature_"] [data-testid="stPageLink"] a span,
[class*="st-key-feature_"] [data-testid="stPageLink"] a p { color: var(--ll-on-brand) !important; }
[class*="st-key-feature_"] [data-testid="stPageLink"] a:hover {
  background: var(--ll-primary-hover);
  box-shadow: var(--ll-shadow-brand); }

/* ---- Home: steps, trust strip ---- */
.ll-steps { list-style: none; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1rem; padding: 0; margin: 0.4rem 0 0.6rem 0; counter-reset: none; position: relative; }
.ll-step { position: relative; background: var(--ll-bg); border: 1px solid var(--ll-border);
  border-radius: var(--ll-radius); padding: 1.1rem 1rem 1rem; box-shadow: var(--ll-shadow-sm);
  margin: 0 !important; }
.ll-step:not(:last-child)::after { content: ""; position: absolute; top: 2.05rem; right: -1rem;
  width: 1rem; height: 2px; background: var(--ll-border-strong); }
.ll-step-num { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem;
  height: 2.1rem; border-radius: 999px; background: var(--ll-gradient); color: var(--ll-on-brand);
  font-weight: 800; font-size: 0.95rem; box-shadow: var(--ll-shadow-brand); }
.ll-step-title { font-weight: 700 !important; color: var(--ll-text) !important;
  margin: 0.7rem 0 0.25rem 0 !important;
  font-size: 1rem !important; }
.ll-step-text { color: var(--ll-text-soft) !important; font-size: 0.9rem !important;
  margin: 0 !important;
  line-height: 1.55 !important; }
.ll-trust { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1rem;
  background: var(--ll-bg); border: 1px solid var(--ll-border); border-radius: var(--ll-radius-lg);
  padding: 1.1rem 1.3rem; box-shadow: var(--ll-shadow-sm); }
.ll-trust-item { display: flex; gap: 0.7rem; align-items: flex-start; }
.ll-trust-tick { flex: 0 0 auto; width: 1.55rem; height: 1.55rem; border-radius: 999px;
  background: var(--ll-approved-tint); border: 1px solid var(--ll-approved); position: relative;
  margin-top: 0.1rem; }
.ll-trust-tick::after { content: ""; position: absolute; left: 0.5rem; top: 0.27rem;
  width: 0.32rem;
  height: 0.62rem; border: solid var(--ll-approved-ink); border-width: 0 2.5px 2.5px 0;
  transform: rotate(45deg); }
.ll-trust-title { font-weight: 700 !important; margin: 0 !important;
  font-size: 0.95rem !important; }
.ll-trust-text { color: var(--ll-muted) !important; margin: 0 !important;
  font-size: 0.85rem !important;
  line-height: 1.45 !important; }

/* ---- Footer ---- */
.st-key-page_footer { border-top: 1px solid var(--ll-border); margin-top: 2rem;
  padding-top: 1rem; }
.st-key-page_footer p { font-size: 0.82rem !important; }

/* ---- Sign in ---- */
.ll-brand-panel { background: var(--ll-gradient); border-radius: 22px; padding: 2.4rem 2.2rem;
  box-shadow: var(--ll-shadow-brand); min-height: 25rem; box-sizing: border-box;
  position: relative;
  overflow: hidden; }
.ll-brand-panel::after { content: ""; position: absolute; left: -100px; bottom: -160px;
  width: 380px;
  height: 380px; border-radius: 50%; background: radial-gradient(circle, rgba(82, 113, 255, 0.5),
  rgba(82, 113, 255, 0) 70%); }
.ll-brand-panel .ll-hero-line { margin-top: 1.2rem; }
.ll-brand-points { list-style: none; padding: 0; margin: 1.4rem 0 0 0; position: relative;
  z-index: 1; }
.ll-brand-points li { color: var(--ll-on-brand) !important; font-weight: 600;
  padding: 0.45rem 0 0.45rem 1.6rem;
  position: relative; font-size: 0.98rem; }
.ll-brand-points li::before { content: ""; position: absolute; left: 0.15rem; top: 0.72rem;
  width: 0.55rem;
  height: 0.55rem; border-radius: 999px; background: var(--ll-on-brand-soft); }
.st-key-signin_card { background: var(--ll-bg); border: 1px solid var(--ll-border);
  border-radius: 22px; padding: 1.8rem 1.8rem 1.4rem; box-shadow: var(--ll-shadow-lg);
  box-sizing: border-box; }
.st-key-signin_card [data-testid="stForm"] { border: none; box-shadow: none;
  padding: 0.4rem 0 0 0; }
.st-key-signin_card h3 { margin-top: 0; }

/* ---- Eligibility result ---- */
.ll-meter { margin: 0.35rem 0 0.2rem 0; }
.ll-meter-track { position: relative; height: 0.85rem; border-radius: 999px;
  background: var(--ll-border);
  overflow: hidden; }
.ll-meter-band { position: absolute; top: 0; bottom: 0; background: var(--ll-warning-tint);
  border-left: 1px solid var(--ll-warning); border-right: 1px solid var(--ll-warning); }
.ll-meter-fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px;
  transition: width 0.6s var(--ll-ease); }
.ll-meter-approved { background: var(--ll-approved); }
.ll-meter-rejected { background: var(--ll-rejected); }
.ll-meter-cut { position: absolute; top: -2px; bottom: -2px; width: 2px;
  background: var(--ll-text); }
.ll-meter-scale { display: flex; justify-content: space-between; color: var(--ll-muted);
  font-size: 0.78rem; margin-top: 0.35rem; font-weight: 600; }
[class*="st-key-reason_"] [data-testid="stIconMaterial"],
  [class*="st-key-card_rejected"] [data-testid="stIconMaterial"] {
  color: var(--ll-rejected-ink); }
[class*="st-key-card_approved"] [data-testid="stIconMaterial"] { color: var(--ll-approved-ink); }
[class*="st-key-card_primary"] [data-testid="stIconMaterial"] { color: var(--ll-primary-ink); }
.st-key-result_figures [data-testid="stMetric"] { padding: 0.8rem 1rem; }
.st-key-result_figures [data-testid="stMetricValue"] { font-size: 1.6rem; }
.st-key-form_section_credit, .st-key-form_section_loan, .st-key-form_section_assets {
  background: var(--ll-bg); border: 1px solid var(--ll-border); border-radius: var(--ll-radius-lg);
  padding: 1.15rem 1.25rem 0.6rem; box-shadow: var(--ll-shadow-sm); box-sizing: border-box; }
[class*="st-key-form_section_"] h4 { display: flex; align-items: center; gap: 0.45rem; }
[class*="st-key-form_section_"] [data-testid="stIconMaterial"] { color: var(--ll-primary-ink); }

/* ---- Policy-check list ---- */
.ll-check { display: flex; gap: 0.7rem; align-items: baseline; padding: 0.5rem 0;
  border-bottom: 1px solid var(--ll-border); }
.ll-check:last-child { border-bottom: none; }
.ll-check-status { font-weight: 800; min-width: 5.6rem; font-size: 0.85rem; border-radius: 999px;
  padding: 0.12rem 0.6rem; text-align: center; border: 1px solid; }
.ll-check-pass .ll-check-status { color: var(--ll-approved-ink);
  background: var(--ll-approved-tint);
  border-color: var(--ll-approved); }
.ll-check-fail .ll-check-status { color: var(--ll-rejected-ink);
  background: var(--ll-rejected-tint);
  border-color: var(--ll-rejected); }
.ll-check-advisory .ll-check-status { color: var(--ll-warning-ink);
  background: var(--ll-warning-tint);
  border-color: var(--ll-warning); }
.ll-check-label { font-weight: 650; color: var(--ll-text); }
.ll-check-detail { color: var(--ll-muted); }

/* ---- Responsive ---- */
@media (max-width: 1100px) {
  .ll-steps { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ll-step::after { display: none; }
  .ll-trust { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] { padding: 3rem 1rem 2rem; }
  h1 { font-size: 1.7rem !important; }
  .st-key-hero { padding: 1.6rem 1.3rem; border-radius: 18px; }
  .ll-hero-name { font-size: 1.9rem; }
  .ll-steps, .ll-trust { grid-template-columns: minmax(0, 1fr); }
  .ll-brand-panel { min-height: 0; padding: 1.6rem 1.4rem; }
  .st-key-signin_card { padding: 1.3rem 1.1rem 1rem; }
  [class*="st-key-feature_"] { min-height: 0; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; }
}
"""


def _tone_css() -> str:
    """Keyed cards, KPI cards, tinted panels and result banners for each tone."""
    parts: list[str] = []
    for tone, (colour, tint, ink) in _TONES.items():
        parts.append(
            f".ll-pill-{tone} {{ background: {tint}; color: {ink}; border-color: {colour}; }}\n"
            # Keyed metric cards: st.container(key="kpi_<tone>_...") -> coloured top edge.
            f'[class*="st-key-kpi_{tone}"] [data-testid="stMetric"] {{ border-top: 4px solid '
            f"{colour}; }}\n"
            f'[class*="st-key-kpi_{tone}"] [data-testid="stMetricValue"] {{ color: {ink}; }}\n'
            # Keyed content cards: st.container(key="card_<tone>_...") -> coloured left edge.
            f'[class*="st-key-card_{tone}"] {{ background: {BACKGROUND}; border: 1px solid '
            f"{BORDER}; border-left: 4px solid {colour}; border-radius: 14px; "
            "padding: 0.95rem 1.15rem; box-sizing: border-box; box-shadow: var(--ll-shadow-sm); "
            "transition: box-shadow 0.2s var(--ll-ease); }\n"
            f'[class*="st-key-card_{tone}"]:hover {{ box-shadow: var(--ll-shadow-md); }}\n'
            # Keyed panels: st.container(key="panel_<tone>_...") -> tinted panel.
            f'[class*="st-key-panel_{tone}"] {{ background: {tint}; border: 1px solid '
            f"{colour}; border-radius: 14px; padding: 0.8rem 1.05rem; box-sizing: border-box; }}\n"
        )
    for kind, tone in (("Success", "approved"), ("Error", "rejected"), ("Warning", "warning"),
                       ("Info", "primary")):  # fmt: skip
        colour, tint, _ = _TONES[tone]
        parts.append(
            f'[data-testid="stAlertContainer"]:has([data-testid="stAlertContent{kind}"]) {{ '
            f"background: {tint}; border-left: 4px solid {colour}; }}\n"
        )
    parts.append(
        '[class*="st-key-panel_"] [data-testid="stAlertContainer"] { background: transparent '
        "!important; border: none !important; padding: 0.2rem 0; }\n"
    )
    # Result banners: st.container(key="banner_approved" / "banner_rejected").
    for tone in ("approved", "rejected"):
        colour, tint, ink = _TONES[tone]
        banner = f'[class*="st-key-banner_{tone}"]'
        parts.append(
            f"{banner} {{ background: linear-gradient(180deg, {tint} 0%, {BACKGROUND} 100%); "
            f"border: 1px solid {colour}; border-top: 6px solid {colour}; border-radius: 20px; "
            "padding: 1.4rem 1.6rem; box-sizing: border-box; box-shadow: var(--ll-shadow-md); }\n"
            f'{banner} [data-testid="stAlertContainer"] {{ background: transparent !important; '
            "border: none !important; padding: 0; }\n"
            f'{banner} [data-testid="stAlertContainer"] h3 {{ color: {ink}; '
            "font-size: 2.4rem !important; font-weight: 800 !important; padding: 0 0 0.1rem 0; "
            "letter-spacing: -0.03em; }\n"
            f'{banner} [data-testid="stAlertContainer"] p {{ font-size: 1.08rem; '
            "font-weight: 600; }\n"
            f'{banner} [data-testid="stAlertContainer"] [data-testid="stIconMaterial"] {{ '
            f"color: {ink}; font-size: 2.3rem; }}\n"
            f'{banner} [data-testid="stMetric"] {{ background: {BACKGROUND}; '
            f"border-color: {colour}; }}\n"
            f'{banner} [data-testid="stMetricValue"] {{ font-size: 1.85rem; color: {ink}; }}\n'
            f'{banner} [data-testid="stMetricValue"] > div {{ white-space: normal; '
            "overflow: visible; text-overflow: clip; }\n"
        )
    return "".join(parts)


def app_css() -> str:
    """The one CSS block injected on every page: font, tokens, components, tones."""
    tokens = "\n".join(f"  {name}: {value};" for name, value in TOKENS.items())
    return f"@import url('{FONT_URL}');\n:root {{\n{tokens}\n}}\n{_BASE_CSS}\n{_tone_css()}"


def css_block() -> str:
    """``app_css()`` wrapped in a ``<style>`` tag, ready for ``st.markdown``."""
    return f"<style>{app_css()}</style>"


CHECK_WORDS = {
    "Pass": ("Passed", "pass"),
    "Fail": ("Failed", "fail"),
    "Advisory": ("Advisory", "advisory"),
}


def policy_checks_html(rows: pd.DataFrame) -> str:
    """Policy-check list: the word "Passed" (green), "Failed" (red) or "Advisory" (amber).

    ``rows`` is ``DecisionView.rule_rows`` (Check, Result, Details). The status is always a
    word, so colour is never the only signal.
    """
    items = []
    for _, row in rows.iterrows():
        word, kind = CHECK_WORDS.get(str(row["Result"]), (str(row["Result"]), "advisory"))
        items.append(
            f'<div class="ll-check ll-check-{kind}">'
            f'<span class="ll-check-status">{html.escape(word)}</span>'
            f'<span><span class="ll-check-label">{html.escape(str(row["Check"]))}.</span> '
            f'<span class="ll-check-detail">{html.escape(str(row["Details"]))}</span></span>'
            "</div>"
        )
    return '<div class="ll-checks">' + "".join(items) + "</div>"
