"""LoanLens visual theme: every colour, the shared app CSS and the Plotly template.

This is the only place colours are defined. The Streamlit pages (via ``app/ui_common.py``),
``charts.py`` and the notebooks import from here, so the whole product looks the same.
Styling only: nothing here affects a decision.
"""

from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

# ---- Palette -------------------------------------------------------------------------------
BACKGROUND = "#FFFFFF"
BACKGROUND_RGB = "rgb(255, 255, 255)"  # same colour; see style_figure
SOFT_PANEL = "#F4F7FE"
BORDER = "#E3E9F5"
PRIMARY = "#2E74E9"
INDIGO = "#5271FF"
TEXT = "#0F1B3D"
MUTED = "#5B6785"
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

PALETTE: dict[str, str] = {
    "background": BACKGROUND,
    "soft_panel": SOFT_PANEL,
    "border": BORDER,
    "primary": PRIMARY,
    "indigo": INDIGO,
    "text": TEXT,
    "muted": MUTED,
    "approved": APPROVED,
    "approved_tint": APPROVED_TINT,
    "rejected": REJECTED,
    "rejected_tint": REJECTED_TINT,
    "warning": WARNING,
    "warning_tint": WARNING_TINT,
}

FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, '
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


# ---- HTML snippets (escaped) ---------------------------------------------------------------
def pill_html(text: str, tone: str = "warning") -> str:
    """A small rounded label, e.g. the amber borderline pill."""
    return f'<span class="ll-pill ll-pill-{tone}">{html.escape(text)}</span>'


def header_html(name: str) -> str:
    """The branded header strip shown at the top of every page: the product name only."""
    return f'<div class="ll-header"><span class="ll-brand">{html.escape(name)}</span></div>'


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
    """White background, light grid, navy text, system fonts, brand colour sequence."""
    axis = {
        "gridcolor": BORDER,
        "linecolor": BORDER,
        "zerolinecolor": BORDER,
        "tickfont": {"color": MUTED},
        "title": {"font": {"color": TEXT}},
        "automargin": True,
    }
    return go.layout.Template(
        layout={
            "font": {"family": FONT_STACK, "color": TEXT, "size": 13},
            "title": {"font": {"family": FONT_STACK, "color": TEXT, "size": 17}, "x": 0.0},
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
            "bargap": 0.3,
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
STREAMLIT_THEME = {
    "base": "light",
    "primaryColor": PRIMARY,
    "backgroundColor": BACKGROUND,
    "secondaryBackgroundColor": SOFT_PANEL,
    "textColor": TEXT,
}


def _tone_rules(prefix: str, tone: str) -> str:
    colour = _TONES[tone][0]
    return (
        f'[class*="st-key-{prefix}"] {{ background: {BACKGROUND}; border: 1px solid {BORDER}; '
        f"border-left: 5px solid {colour}; border-radius: 12px; padding: 0.85rem 1.1rem; "
        f"box-sizing: border-box; box-shadow: 0 1px 3px rgba(15, 27, 61, 0.06); }}\n"
    )


def app_css() -> str:
    """The one CSS block injected on every page (light fintech look)."""
    alert = '[data-testid="stAlertContainer"]:has([data-testid="stAlertContent{kind}"])'
    parts = [
        f"""
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {{
  font-family: {FONT_STACK};
}}
.stApp {{ background: {BACKGROUND}; color: {TEXT}; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 3.6rem; padding-bottom: 3rem;
  max-width: 1180px; }}
[data-testid="stHeader"] {{ background: rgba(255, 255, 255, 0.9); }}
[data-testid="stDecoration"] {{ display: none; }}
h1, h2, h3, h4 {{ color: {TEXT}; letter-spacing: -0.01em; }}
h1 {{ font-size: 2rem !important; font-weight: 700 !important; }}
h2 {{ font-size: 1.45rem !important; font-weight: 650 !important; margin-top: 0.6rem; }}
h3 {{ font-size: 1.2rem !important; font-weight: 650 !important; }}
p, li {{ font-size: 1rem; line-height: 1.6; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: {MUTED} !important; }}
a {{ color: {PRIMARY_INK}; }}

/* Header strip */
.ll-header {{ display: flex; align-items: center; min-height: 4.4rem; box-sizing: border-box;
  background: {PRIMARY_INK}; border-bottom: 4px solid {INDIGO};
  color: #FFFFFF; border-radius: 14px; padding: 0.7rem 1.3rem; margin-bottom: 1.1rem;
  box-shadow: 0 4px 14px rgba(46, 116, 233, 0.18); }}
.ll-brand {{ font-size: 2.4rem; font-weight: 800; line-height: 1.15; color: #FFFFFF;
  letter-spacing: -0.015em; }}

/* Sidebar */
[data-testid="stSidebar"] {{ background: {SOFT_PANEL}; border-right: 1px solid {BORDER}; }}
[data-testid="stSidebarNavLink"] {{ border-radius: 8px; }}

/* Cards: bordered containers */
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 14px; border-color: {BORDER}; }}
[data-testid="stExpander"] details {{ border: 1px solid {BORDER}; border-radius: 12px;
  background: {BACKGROUND}; }}
[data-testid="stExpander"] summary {{ font-weight: 600; color: {TEXT}; }}
[data-testid="stExpander"] summary:hover {{ color: {PRIMARY_INK}; }}

/* Buttons */
.stButton > button, .stDownloadButton > button, [data-testid="stPageLink"] a {{
  border-radius: 10px; font-weight: 600; transition: all 0.15s ease; }}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
  background: {PRIMARY_INK}; border: 1px solid {PRIMARY_INK}; color: #FFFFFF;
  padding: 0.55rem 1.2rem; }}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {{
  background: {PRIMARY_INK_HOVER}; border-color: {PRIMARY_INK_HOVER}; color: #FFFFFF;
  box-shadow: 0 4px 12px rgba(46, 116, 233, 0.28); }}
.stButton > button[kind="secondary"], .stDownloadButton > button[kind="secondary"] {{
  border: 1px solid {PRIMARY}; color: {PRIMARY_INK}; background: {BACKGROUND}; }}
.stButton > button[kind="secondary"]:hover, .stDownloadButton > button[kind="secondary"]:hover
  {{ background: {SOFT_PANEL}; border-color: {PRIMARY_INK}; color: {PRIMARY_INK}; }}
[data-testid="stPageLink"] a:hover {{ background: {SOFT_PANEL}; }}

/* Form inputs */
[data-testid="stNumberInput"] input, [data-testid="stTextInput"] input,
[data-baseweb="select"] > div {{ border-radius: 10px !important; }}
[data-testid="stNumberInput"] label p, [data-testid="stTextInput"] label p,
[data-testid="stSelectbox"] label p, [data-testid="stMultiSelect"] label p {{
  font-weight: 600; color: {TEXT}; }}
[data-baseweb="input"], [data-baseweb="select"] > div {{ border-color: {BORDER} !important; }}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{ gap: 0.35rem; border-bottom: 1px solid {BORDER}; }}
.stTabs [data-baseweb="tab"] {{ border-radius: 10px 10px 0 0; padding: 0.5rem 1rem;
  font-weight: 600; color: {MUTED}; }}
.stTabs [aria-selected="true"] {{ color: {PRIMARY_INK}; background: {SOFT_PANEL}; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: {PRIMARY}; }}

/* Alerts: palette tints with a coloured left border; body text stays navy */
[data-testid="stAlertContainer"] {{ border-radius: 12px; color: {TEXT}; }}
{alert.format(kind="Success")} {{ background: {APPROVED_TINT};
  border-left: 5px solid {APPROVED}; }}
{alert.format(kind="Error")} {{ background: {REJECTED_TINT};
  border-left: 5px solid {REJECTED}; }}
{alert.format(kind="Warning")} {{ background: {WARNING_TINT};
  border-left: 5px solid {WARNING}; }}
{alert.format(kind="Info")} {{ background: {SOFT_PANEL}; border-left: 5px solid {PRIMARY}; }}
[data-testid="stAlertContainer"] p, [data-testid="stAlertContainer"] li {{
  color: {TEXT}; }}

/* Metric cards */
[data-testid="stMetric"] {{ background: {BACKGROUND}; border: 1px solid {BORDER};
  border-radius: 14px; padding: 0.8rem 1rem; box-shadow: 0 1px 3px rgba(15, 27, 61, 0.06); }}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; font-weight: 600; }}
[data-testid="stMetricValue"] {{ color: {TEXT}; font-weight: 700; }}

/* Data tables */
[data-testid="stDataFrame"] {{ border: 1px solid {BORDER}; border-radius: 12px;
  overflow: hidden; }}

/* Pills */
.ll-pill {{ display: inline-block; border-radius: 999px; padding: 0.22rem 0.8rem;
  font-size: 0.92rem; font-weight: 650; border: 1px solid; }}
"""
    ]
    for tone, (colour, tint, ink) in _TONES.items():
        parts.append(
            f".ll-pill-{tone} {{ background: {tint}; color: {ink}; border-color: {colour}; }}\n"
        )
        # Keyed metric cards: st.container(key="kpi_<tone>_...") -> coloured top edge + value.
        parts.append(
            f'[class*="st-key-kpi_{tone}"] [data-testid="stMetric"] {{ border-top: 4px solid '
            f"{colour}; background: {tint if tone != 'primary' else BACKGROUND}; }}\n"
            f'[class*="st-key-kpi_{tone}"] [data-testid="stMetricValue"] {{ color: {ink}; }}\n'
        )
        # Keyed content cards: st.container(key="card_<tone>_...") -> coloured left border.
        parts.append(_tone_rules(f"card_{tone}", tone))
        # Keyed panels: st.container(key="panel_<tone>_...") -> tinted panel.
        parts.append(
            f'[class*="st-key-panel_{tone}"] {{ background: {tint}; border: 1px solid '
            f"{colour}; border-radius: 12px; padding: 0.75rem 1rem; box-sizing: border-box; }}\n"
        )
    # Alerts inside a tinted panel blend into it.
    parts.append(
        '[class*="st-key-panel_"] [data-testid="stAlertContainer"] { background: transparent '
        "!important; border: none !important; padding: 0.2rem 0; }\n"
    )
    # Result banners: st.container(key="banner_approved" / "banner_rejected").
    for tone in ("approved", "rejected"):
        colour, tint, ink = _TONES[tone]
        parts.append(
            f'[class*="st-key-banner_{tone}"] {{ background: {tint}; border: 2px solid '
            f"{colour}; border-radius: 16px; padding: 1.1rem 1.4rem; box-sizing: border-box; "
            f"box-shadow: 0 4px 16px rgba(15, 27, 61, 0.07); }}\n"
            f'[class*="st-key-banner_{tone}"] [data-testid="stAlertContainer"] {{ '
            f"background: transparent !important; border: none !important; padding: 0; }}\n"
            f'[class*="st-key-banner_{tone}"] [data-testid="stAlertContainer"] h3 {{ '
            f"color: {ink}; font-size: 2rem !important; font-weight: 750 !important; "
            f"padding: 0 0 0.15rem 0; }}\n"
            f'[class*="st-key-banner_{tone}"] [data-testid="stAlertContainer"] svg '
            f"{{ display: none; }}\n"
            f'[class*="st-key-banner_{tone}"] [data-testid="stMetric"] {{ background: '
            f"rgba(255, 255, 255, 0.75); border-color: {colour}; }}\n"
            f'[class*="st-key-banner_{tone}"] [data-testid="stMetricValue"] {{ '
            f"font-size: 1.7rem; }}\n"
            f'[class*="st-key-banner_{tone}"] [data-testid="stMetricValue"] > div {{ '
            f"white-space: normal; overflow: visible; text-overflow: clip; }}\n"
        )
    # Policy-check list items.
    parts.append(
        f".ll-check {{ display: flex; gap: 0.55rem; align-items: baseline; padding: 0.35rem 0;"
        f" border-bottom: 1px solid {BORDER}; }}\n"
        f".ll-check:last-child {{ border-bottom: none; }}\n"
        f".ll-check-status {{ font-weight: 800; min-width: 5.2rem; }}\n"
        f".ll-check-pass .ll-check-status {{ color: {APPROVED_INK}; }}\n"
        f".ll-check-fail .ll-check-status {{ color: {REJECTED_INK}; }}\n"
        f".ll-check-advisory .ll-check-status {{ color: {WARNING_INK}; }}\n"
        f".ll-check-label {{ font-weight: 600; color: {TEXT}; }}\n"
        f".ll-check-detail {{ color: {MUTED}; }}\n"
    )
    return "\n".join(parts)


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
