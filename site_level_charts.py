"""
Plotly figure builders shared by app_site_level_analysis.py and create_site_level_analysis_deck.py.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

GREEN = "#00d9a5"
ORANGE = "#f77f00"
PINK = "#e94560"
PINK_DEEP = "#c73e54"
GRAY = "#6b7280"
RED = "#e63946"
TEXT_MUTED = "#9ca3af"


def hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def fig_sparkline(color: str, n: int = 24, seed: int = 0) -> go.Figure:
    rng = np.random.default_rng(seed)
    base = np.linspace(0, 1, n)
    ys = 0.5 + 0.35 * np.sin(base * 4) + rng.normal(0, 0.06, n)
    ys = np.clip(ys, 0.1, 1.0)
    fig = go.Figure(
        go.Scatter(
            x=list(range(n)),
            y=ys,
            mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy",
            fillcolor=hex_rgba(color, 0.22),
        )
    )
    fig.add_hline(y=0.55, line=dict(color="rgba(255,255,255,0.25)", width=1, dash="dot"))
    fig.update_layout(
        height=52,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, fixedrange=True),
    )
    return fig


def fig_sparkline_green() -> go.Figure:
    return fig_sparkline(GREEN, seed=1)


def fig_sparkline_orange() -> go.Figure:
    return fig_sparkline(ORANGE, seed=2)


def fig_sparkline_pink() -> go.Figure:
    return fig_sparkline(PINK, seed=3)


def fig_stacked_h_bar(
    title: str,
    segments: list[tuple[str, float, str]],
    height: int = 120,
) -> go.Figure:
    y = [""]
    fig = go.Figure()
    for name, pct, color in segments:
        fig.add_trace(
            go.Bar(
                name=name,
                x=[pct],
                y=y,
                orientation="h",
                marker_color=color,
                text=[f"{pct:.0f}%"],
                textposition="inside",
                insidetextfont=dict(color="white", size=11),
                hovertemplate="%{fullData.name}: %{x:.1f}%<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="stack",
        height=height,
        margin=dict(l=12, r=12, t=36, b=8),
        title=dict(text=title, font=dict(size=13, color="#e5e7eb"), x=0, xanchor="left"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(range=[0, 100], ticksuffix="%", gridcolor="rgba(255,255,255,0.06)", zeroline=False),
        yaxis=dict(visible=False, fixedrange=True),
        font=dict(color=TEXT_MUTED, size=11),
    )
    return fig


def fig_region_avail_bars(
    title: str,
    items: list[tuple[str, float]],
    height: int = 280,
) -> go.Figure:
    names = [x[0] for x in items]
    vals = [x[1] for x in items]
    colors = [GREEN if v >= 99.5 else ORANGE if v >= 99.0 else PINK for v in vals]
    fig = go.Figure(
        go.Bar(
            x=vals,
            y=names,
            orientation="h",
            marker_color=colors,
            text=[f"{v:.3f}%" for v in vals],
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#e5e7eb"), x=0, xanchor="left"),
        height=height,
        margin=dict(l=12, r=48, t=36, b=8),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(
            range=[98.8, 100],
            ticksuffix="%",
            gridcolor="rgba(255,255,255,0.06)",
            zeroline=False,
        ),
        yaxis=dict(autorange="reversed", fixedrange=True, tickfont=dict(size=11)),
        font=dict(color=TEXT_MUTED, size=11),
    )
    return fig
