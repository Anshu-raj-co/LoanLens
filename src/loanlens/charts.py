"""Reusable Plotly charts for approval analysis (EDA notebook and, later, the Analytics page).

All functions expect a cleaned frame where ``loan_status`` is 1 (approved) / 0 (rejected).
They describe the approval *decision* in the data, not default risk.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from loanlens.features import CIBIL_EDGES, CIBIL_LABELS, cibil_band

__all__ = [
    "CIBIL_EDGES",
    "CIBIL_LABELS",
    "approval_by_cibil_band",
    "approval_by_quantile_band",
    "approval_heatmap",
    "approval_rate_bar",
    "approval_rate_table",
    "cibil_band",
    "distribution_by_status",
]

TARGET = "loan_status"
APPROVED_COLOUR = "#2a9d8f"
REJECTED_COLOUR = "#e76f51"
STATUS_COLOURS = {"Approved": APPROVED_COLOUR, "Rejected": REJECTED_COLOUR}


def approval_rate_table(df: pd.DataFrame, by: str | pd.Series) -> pd.DataFrame:
    """Return applications, approvals and approval rate (0-1) per group.

    Args:
        df: cleaned frame with a 0/1 ``loan_status`` column.
        by: a column name in ``df`` or a Series aligned with ``df`` (e.g. bands).
    """
    keys = df[by] if isinstance(by, str) else by
    name = by if isinstance(by, str) else (by.name or "group")
    grouped = df[TARGET].groupby(keys, observed=True)
    table = pd.DataFrame(
        {
            "applications": grouped.size(),
            "approved": grouped.sum(),
            "approval_rate": grouped.mean(),
        }
    )
    table.index.name = name
    return table.reset_index()


def approval_rate_bar(
    df: pd.DataFrame,
    by: str | pd.Series,
    title: str,
    x_label: str | None = None,
) -> go.Figure:
    """Bar chart of approval rate per group, annotated with the number of applications."""
    table = approval_rate_table(df, by)
    group_col = table.columns[0]
    table[group_col] = table[group_col].astype(str)
    fig = px.bar(
        table,
        x=group_col,
        y="approval_rate",
        text=table["approval_rate"].map(lambda r: f"{r:.0%}"),
        hover_data={"applications": True, "approved": True},
        title=title,
        color_discrete_sequence=[APPROVED_COLOUR],
    )
    fig.update_layout(
        xaxis_title=x_label or group_col,
        yaxis_title="Approval rate",
        yaxis_tickformat=".0%",
        yaxis_range=[0, 1.08],
        xaxis_type="category",
    )
    fig.update_traces(textposition="outside")
    return fig


def approval_by_cibil_band(df: pd.DataFrame) -> go.Figure:
    """Approval rate by CIBIL band (bands from ``CIBIL_EDGES``)."""
    bands = cibil_band(df["cibil_score"]).rename("cibil_band")
    return approval_rate_bar(df, bands, "Approval rate by CIBIL band", "CIBIL band")


def approval_by_quantile_band(
    df: pd.DataFrame,
    column: str,
    q: int = 5,
    title: str | None = None,
    values: pd.Series | None = None,
) -> go.Figure:
    """Approval rate across quantile bands of a numeric column (or a derived ``values`` series).

    Band labels show the value range of each band.
    """
    series = values if values is not None else df[column]
    bands = pd.qcut(series, q=q, duplicates="drop")
    named = bands.cat.rename_categories(
        [f"{iv.left:,.2f} to {iv.right:,.2f}" for iv in bands.cat.categories]
    ).rename(column)
    return approval_rate_bar(
        df, named, title or f"Approval rate by {column} (quantile bands)", column
    )


def distribution_by_status(
    df: pd.DataFrame,
    column: str,
    title: str | None = None,
    nbins: int = 40,
    values: pd.Series | None = None,
) -> go.Figure:
    """Overlaid histogram of a numeric column split by approval status."""
    plot_df = pd.DataFrame(
        {
            column: values if values is not None else df[column],
            "status": df[TARGET].map({1: "Approved", 0: "Rejected"}),
        }
    )
    fig = px.histogram(
        plot_df,
        x=column,
        color="status",
        nbins=nbins,
        barmode="overlay",
        opacity=0.6,
        color_discrete_map=STATUS_COLOURS,
        title=title or f"Distribution of {column} by status",
    )
    fig.update_layout(yaxis_title="Applications", legend_title="Status")
    return fig


def approval_heatmap(
    df: pd.DataFrame,
    rows: str | pd.Series,
    cols: str | pd.Series,
    title: str,
    row_order: Sequence | None = None,
) -> go.Figure:
    """Heatmap of approval rate for two grouping variables, with application counts on hover."""
    r = df[rows] if isinstance(rows, str) else rows
    c = df[cols] if isinstance(cols, str) else cols
    grouped = df[TARGET].groupby([r, c], observed=True)
    rate = grouped.mean().unstack()
    count = grouped.size().unstack().reindex_like(rate)
    if row_order is not None:
        rate = rate.reindex(row_order)
        count = count.reindex(row_order)
    fig = go.Figure(
        go.Heatmap(
            z=rate.values,
            x=[str(v) for v in rate.columns],
            y=[str(v) for v in rate.index],
            customdata=count.values,
            colorscale="RdYlGn",
            zmin=0,
            zmax=1,
            text=[[f"{v:.0%}" if pd.notna(v) else "" for v in row] for row in rate.values],
            texttemplate="%{text}",
            hovertemplate="%{y} / %{x}<br>Approval rate: %{z:.1%}<br>"
            "Applications: %{customdata}<extra></extra>",
            colorbar={"title": "Approval rate", "tickformat": ".0%"},
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title=c.name,
        yaxis_title=r.name,
        xaxis_type="category",
        yaxis_type="category",
    )
    return fig
