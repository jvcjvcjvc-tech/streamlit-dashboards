"""
Site-Level Analysis dashboard — Streamlit recreation of the network ops view
(availability, COTTR category mix, Field Ops assignment tables).

  streamlit run app_site_level_analysis.py
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Site-Level Analysis",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

COL_BG = "#0b0e14"
COL_BORDER = "rgba(255,255,255,0.08)"
GREEN = "#00d9a5"
ORANGE = "#f77f00"
PINK = "#e94560"
PINK_DEEP = "#c73e54"
GRAY = "#6b7280"
RED = "#e63946"
TEXT_MUTED = "#9ca3af"

st.markdown(
    f"""
<style>
    .stApp {{ background: linear-gradient(165deg, #0a0c10 0%, {COL_BG} 45%, #12151c 100%); }}
    .sla-toprow {{
        display: flex;
        justify-content: flex-end;
        margin: -8px 0 4px 0;
    }}
    .deploy-link {{ font-size: 12px; color: {TEXT_MUTED}; }}
    .stTabs [data-baseweb="tab-list"] {{
        gap: 6px;
        flex-wrap: wrap;
        background: rgba(255,255,255,0.03);
        padding: 8px;
        border-radius: 999px;
    }}
    .stTabs [data-baseweb="tab"] {{
        border-radius: 999px;
        color: {TEXT_MUTED};
        padding: 8px 14px;
        font-size: 13px;
        font-weight: 500;
    }}
    .stTabs [aria-selected="true"] {{
        background: linear-gradient(90deg, {PINK}, #9f1239) !important;
        color: #fff !important;
    }}
    .section-heading {{
        color: #e5e7eb;
        font-size: 15px;
        font-weight: 600;
        margin: 20px 0 12px 0;
        padding-left: 10px;
        border-left: 3px solid {PINK};
    }}
    .fos-heading {{
        color: #e5e7eb;
        font-size: 15px;
        font-weight: 600;
        margin: 8px 0 12px 0;
    }}
    table.fos-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
        color: #e5e7eb;
    }}
    table.fos-table th {{
        text-align: left;
        padding: 10px 8px;
        color: {TEXT_MUTED};
        font-weight: 600;
        border-bottom: 1px solid {COL_BORDER};
    }}
    table.fos-table td {{
        padding: 10px 8px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
        vertical-align: middle;
    }}
    .down {{ color: {PINK}; font-weight: 600; }}
    .avail {{ color: {GREEN}; font-weight: 600; }}
    .delta-bad {{ color: {PINK}; font-weight: 600; }}
    .bar-track {{
        height: 10px;
        background: rgba(255,255,255,0.1);
        border-radius: 5px;
        overflow: hidden;
        min-width: 80px;
    }}
    .bar-fill {{
        height: 100%;
        border-radius: 5px;
        background: {RED};
    }}
</style>
""",
    unsafe_allow_html=True,
)

NAV_ITEMS = [
    "Executive Summary",
    "Site Analysis",
    "Region Availability",
    "Area Availability",
    "Availability Detail",
    "COTTR Detail",
    "Customer Minutes Detail",
    "Data Diagnostics",
]


def _hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _sparkline(color: str, n: int = 24, seed: int = 0) -> go.Figure:
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
            fillcolor=_hex_rgba(color, 0.22),
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


def _sparkline_green() -> go.Figure:
    return _sparkline(GREEN, seed=1)


def _sparkline_orange() -> go.Figure:
    return _sparkline(ORANGE, seed=2)


def _sparkline_pink() -> go.Figure:
    return _sparkline(PINK, seed=3)


def _stacked_h_bar(title: str, segments: list[tuple[str, float, str]], height: int = 120) -> go.Figure:
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


def _kpi_block(
    title: str,
    main_value: str,
    sub_lines: list[str],
    accent: str,
    spark_fn,
    chart_key: str,
) -> None:
    st.markdown(f'<p style="color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;letter-spacing:0.08em;margin:0 0 6px 0;">{title}</p>', unsafe_allow_html=True)
    st.markdown(
        f'<p style="color:{accent};font-size:26px;font-weight:700;margin:0;line-height:1.1;">{main_value}</p>',
        unsafe_allow_html=True,
    )
    for line in sub_lines:
        st.markdown(f'<p style="color:{TEXT_MUTED};font-size:12px;margin:4px 0 0 0;">{line}</p>', unsafe_allow_html=True)
    st.plotly_chart(
        spark_fn(),
        use_container_width=True,
        config={"displayModeBar": False},
        key=chart_key,
    )


def _budget_bar_html(pct: float) -> str:
    w = min(max(pct, 0), 200) / 200 * 100
    return f'<div class="bar-track"><div class="bar-fill" style="width:{w:.1f}%"></div></div>'


def _field_ops_table_html(title: str, rows: list[dict]) -> str:
    th = "<tr><th>Group</th><th>Down</th><th>Avail%</th><th>Budget</th><th>+/-</th><th>Sites</th></tr>"
    if "manager" in title.lower():
        th = "<tr><th>Manager</th><th>Down</th><th>Avail%</th><th>Budget</th><th>+/-</th><th>Sites</th></tr>"
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f'<td>{r["name"]}</td>'
            f'<td class="down">{r["down"]}</td>'
            f'<td class="avail">{r["avail"]}</td>'
            f'<td>{_budget_bar_html(r["budget_pct"])} <span style="color:{TEXT_MUTED};font-size:11px">{r["budget_pct"]:.0f}%</span></td>'
            f'<td class="delta-bad">{r["delta"]}</td>'
            f'<td>{r["sites"]}</td>'
            "</tr>"
        )
    return f"""
    <p class="fos-heading">{title}</p>
    <table class="fos-table">{th}{"".join(body)}</table>
    """


def render_site_analysis() -> None:
    st.markdown("### Site-Level Analysis")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        _kpi_block(
            "Daily Availability %",
            "99.55%",
            ["1/8 · 12%", "Days &lt; 99.95%"],
            GREEN,
            _sparkline_green,
            chart_key="sla_spark_daily_avail",
        )
    with c2:
        _kpi_block(
            "Downtime (sec)",
            "96.3M",
            ["Budget: 32.1M", '<span style="color:#e63946">+64.2M</span>'],
            GREEN,
            _sparkline_green,
            chart_key="sla_spark_downtime",
        )
    with c3:
        _kpi_block(
            "Outage Events",
            "464",
            ["338 sites"],
            ORANGE,
            _sparkline_orange,
            chart_key="sla_spark_outage_events",
        )
    with c4:
        _kpi_block(
            "Outage Minutes",
            "56.7K",
            ["338 sites"],
            ORANGE,
            _sparkline_orange,
            chart_key="sla_spark_outage_min",
        )
    with c5:
        _kpi_block(
            "Customer Minutes",
            "1.4M",
            ["96 sites"],
            PINK,
            _sparkline_pink,
            chart_key="sla_spark_cust_min",
        )
    with c6:
        _kpi_block(
            "Impacted Subscribers",
            "37.8K",
            ["96 sites"],
            PINK,
            _sparkline_pink,
            chart_key="sla_spark_impacted_sub",
        )

    st.markdown('<p class="section-heading">Category breakdowns</p>', unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            _stacked_h_bar(
                "Availability — Summary categories",
                [("Transport", 61, GRAY), ("RAN", 26, PINK), ("Power", 12, PINK_DEEP)],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="sla_bar_avail_summary",
        )
        st.plotly_chart(
            _stacked_h_bar(
                "Availability — Focus categories",
                [
                    ("Transport-AAV", 54, GRAY),
                    ("Site Mod", 22, PINK),
                    ("Maintenance", 8, PINK_DEEP),
                    ("Decommission", 7, "#7f1d1d"),
                    ("Other", 9, "#4b5563"),
                ],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="sla_bar_avail_focus",
        )
    with g2:
        st.plotly_chart(
            _stacked_h_bar(
                "COTTR — Summary categories",
                [("Transport", 76, GRAY), ("RAN", 16, PINK), ("Other", 8, "#4b5563")],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="sla_bar_cottr_summary",
        )
        st.plotly_chart(
            _stacked_h_bar(
                "COTTR — Focus categories",
                [
                    ("Transport-AAV", 64, GRAY),
                    ("Site Mod", 12, PINK),
                    ("Maintenance", 10, PINK_DEEP),
                    ("Decommission", 6, "#7f1d1d"),
                    ("Other", 8, "#4b5563"),
                ],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="sla_bar_cottr_focus",
        )

    st.markdown(
        '<p class="section-heading">Field Ops Availability — Birmingham</p>',
        unsafe_allow_html=True,
    )
    t1, t2 = st.columns(2)
    assignment_rows = [
        {"name": "North Central", "down": "39.0Ms", "avail": "99.234%", "budget_pct": 150, "delta": "+64.2M", "sites": "312"},
        {"name": "North", "down": "28.4Ms", "avail": "99.412%", "budget_pct": 114, "delta": "+22.1M", "sites": "298"},
        {"name": "South", "down": "18.2Ms", "avail": "99.521%", "budget_pct": 88, "delta": "−4.2M", "sites": "341"},
        {"name": "South Central", "down": "10.7Ms", "avail": "99.601%", "budget_pct": 62, "delta": "−12.8M", "sites": "336"},
    ]
    manager_rows = [
        {
            "name": "Timothy Blackwood",
            "down": "96.3Ms",
            "avail": "99.550%",
            "budget_pct": 150,
            "delta": "+64.2M",
            "sites": "1287",
        }
    ]
    with t1:
        st.markdown(_field_ops_table_html("Assignment groups", assignment_rows), unsafe_allow_html=True)
    with t2:
        st.markdown(_field_ops_table_html("Field Ops managers", manager_rows), unsafe_allow_html=True)

    st.caption("Sample figures aligned to the reference layout — wire to Snowflake or CSV for production values.")


def render_executive_summary() -> None:
    st.markdown("### Executive Summary")
    st.caption("Enterprise rollup · trailing 30 days (sample data — bind to your warehouse).")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        _kpi_block(
            "Network availability",
            "99.58%",
            ["Target 99.95%", "Days below target: 12"],
            GREEN,
            _sparkline_green,
            chart_key="es_spark_network_avail",
        )
    with c2:
        _kpi_block(
            "Downtime (sec)",
            "412.7M",
            ["Budget: 320.0M", '<span style="color:#e63946">+92.7M vs budget</span>'],
            GREEN,
            _sparkline_green,
            chart_key="es_spark_downtime",
        )
    with c3:
        _kpi_block(
            "Outage events",
            "2,847",
            ["2,104 unique sites"],
            ORANGE,
            _sparkline_orange,
            chart_key="es_spark_outage_events",
        )
    with c4:
        _kpi_block(
            "Outage minutes",
            "428K",
            ["Enterprise total"],
            ORANGE,
            _sparkline_orange,
            chart_key="es_spark_outage_min",
        )
    with c5:
        _kpi_block(
            "Customer minutes",
            "18.2M",
            ["Impacted customer-min"],
            PINK,
            _sparkline_pink,
            chart_key="es_spark_cust_min",
        )
    with c6:
        _kpi_block(
            "Impacted subscribers",
            "512K",
            ["Peak day estimate"],
            PINK,
            _sparkline_pink,
            chart_key="es_spark_impacted_sub",
        )

    st.markdown('<p class="section-heading">National category mix</p>', unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            _stacked_h_bar(
                "Availability — Summary categories",
                [("Transport", 61, GRAY), ("RAN", 26, PINK), ("Power", 12, PINK_DEEP)],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="es_bar_avail_summary",
        )
    with g2:
        st.plotly_chart(
            _stacked_h_bar(
                "COTTR — Summary categories",
                [("Transport", 76, GRAY), ("RAN", 16, PINK), ("Other", 8, "#4b5563")],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="es_bar_cottr_summary",
        )

    st.markdown('<p class="section-heading">Region spotlight</p>', unsafe_allow_html=True)
    region_rows = [
        {"region": "South", "avail": "99.612%", "down": "98.2M", "events": "612", "budget_pct": 118},
        {"region": "Northeast", "avail": "99.541%", "down": "86.4M", "events": "534", "budget_pct": 105},
        {"region": "West", "avail": "99.498%", "down": "79.1M", "events": "498", "budget_pct": 96},
        {"region": "Central", "avail": "99.455%", "down": "91.0M", "events": "521", "budget_pct": 112},
        {"region": "Mid-Atlantic", "avail": "99.523%", "down": "58.0M", "events": "382", "budget_pct": 89},
    ]
    rh = (
        "<tr><th>Region</th><th>Avail%</th><th>Downtime</th><th>Events</th><th>Budget</th></tr>"
    )
    rb = []
    for r in region_rows:
        rb.append(
            "<tr>"
            f'<td>{r["region"]}</td>'
            f'<td class="avail">{r["avail"]}</td>'
            f'<td class="down">{r["down"]}</td>'
            f'<td>{r["events"]}</td>'
            f'<td>{_budget_bar_html(r["budget_pct"])} <span style="color:{TEXT_MUTED};font-size:11px">{r["budget_pct"]}%</span></td>'
            "</tr>"
        )
    st.markdown(
        f'<table class="fos-table">{rh}{"".join(rb)}</table>',
        unsafe_allow_html=True,
    )

    st.caption("Executive view uses summary charts only; open **Site Analysis** for focus categories and Field Ops tables.")


def main() -> None:
    st.markdown('<div class="sla-toprow"><span class="deploy-link">Deploy</span></div>', unsafe_allow_html=True)
    tabs = st.tabs(NAV_ITEMS)
    for i, tab in enumerate(tabs):
        with tab:
            if NAV_ITEMS[i] == "Executive Summary":
                render_executive_summary()
            elif NAV_ITEMS[i] == "Site Analysis":
                render_site_analysis()
            else:
                st.info(
                    f"**{NAV_ITEMS[i]}** — placeholder. Reuse KPI / chart patterns from Site Analysis and bind data."
                )


if __name__ == "__main__":
    main()
