"""
Site-Level Analysis dashboard — Streamlit recreation of the network ops view
(availability, COTTR category mix, Field Ops assignment tables).

  streamlit run app_site_level_analysis.py
"""
from __future__ import annotations

import streamlit as st

from site_level_charts import (
    GRAY,
    GREEN,
    ORANGE,
    PINK,
    PINK_DEEP,
    RED,
    TEXT_MUTED,
    fig_region_avail_bars,
    fig_sparkline,
    fig_sparkline_green,
    fig_sparkline_orange,
    fig_sparkline_pink,
    fig_stacked_h_bar,
)

st.set_page_config(
    page_title="Site-Level Analysis",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

COL_BG = "#0b0e14"
COL_BORDER = "rgba(255,255,255,0.08)"

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
    .warn {{ color: {ORANGE}; font-weight: 600; }}
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


def _region_horizontal_avail_bars(
    title: str,
    items: list[tuple[str, float]],
    chart_key: str,
    height: int = 280,
) -> None:
    fig = fig_region_avail_bars(title, items, height=height)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=chart_key)


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
            fig_sparkline_green,
            chart_key="sla_spark_daily_avail",
        )
    with c2:
        _kpi_block(
            "Downtime (sec)",
            "96.3M",
            ["Budget: 32.1M", '<span style="color:#e63946">+64.2M</span>'],
            GREEN,
            fig_sparkline_green,
            chart_key="sla_spark_downtime",
        )
    with c3:
        _kpi_block(
            "Outage Events",
            "464",
            ["338 sites"],
            ORANGE,
            fig_sparkline_orange,
            chart_key="sla_spark_outage_events",
        )
    with c4:
        _kpi_block(
            "Outage Minutes",
            "56.7K",
            ["338 sites"],
            ORANGE,
            fig_sparkline_orange,
            chart_key="sla_spark_outage_min",
        )
    with c5:
        _kpi_block(
            "Customer Minutes",
            "1.4M",
            ["96 sites"],
            PINK,
            fig_sparkline_pink,
            chart_key="sla_spark_cust_min",
        )
    with c6:
        _kpi_block(
            "Impacted Subscribers",
            "37.8K",
            ["96 sites"],
            PINK,
            fig_sparkline_pink,
            chart_key="sla_spark_impacted_sub",
        )

    st.markdown('<p class="section-heading">Category breakdowns</p>', unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            fig_stacked_h_bar(
                "Availability — Summary categories",
                [("Transport", 61, GRAY), ("RAN", 26, PINK), ("Power", 12, PINK_DEEP)],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="sla_bar_avail_summary",
        )
        st.plotly_chart(
            fig_stacked_h_bar(
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
            fig_stacked_h_bar(
                "COTTR — Summary categories",
                [("Transport", 76, GRAY), ("RAN", 16, PINK), ("Other", 8, "#4b5563")],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="sla_bar_cottr_summary",
        )
        st.plotly_chart(
            fig_stacked_h_bar(
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
            fig_sparkline_green,
            chart_key="es_spark_network_avail",
        )
    with c2:
        _kpi_block(
            "Downtime (sec)",
            "412.7M",
            ["Budget: 320.0M", '<span style="color:#e63946">+92.7M vs budget</span>'],
            GREEN,
            fig_sparkline_green,
            chart_key="es_spark_downtime",
        )
    with c3:
        _kpi_block(
            "Outage events",
            "2,847",
            ["2,104 unique sites"],
            ORANGE,
            fig_sparkline_orange,
            chart_key="es_spark_outage_events",
        )
    with c4:
        _kpi_block(
            "Outage minutes",
            "428K",
            ["Enterprise total"],
            ORANGE,
            fig_sparkline_orange,
            chart_key="es_spark_outage_min",
        )
    with c5:
        _kpi_block(
            "Customer minutes",
            "18.2M",
            ["Impacted customer-min"],
            PINK,
            fig_sparkline_pink,
            chart_key="es_spark_cust_min",
        )
    with c6:
        _kpi_block(
            "Impacted subscribers",
            "512K",
            ["Peak day estimate"],
            PINK,
            fig_sparkline_pink,
            chart_key="es_spark_impacted_sub",
        )

    st.markdown('<p class="section-heading">National category mix</p>', unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            fig_stacked_h_bar(
                "Availability — Summary categories",
                [("Transport", 61, GRAY), ("RAN", 26, PINK), ("Power", 12, PINK_DEEP)],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="es_bar_avail_summary",
        )
    with g2:
        st.plotly_chart(
            fig_stacked_h_bar(
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


def render_region_availability() -> None:
    st.markdown("### Region availability")
    st.caption("Regional KPIs vs national targets · sample data.")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        _kpi_block("Worst region avail", "99.412%", ["Northeast · MTD"], GREEN, fig_sparkline_green, chart_key="ra_spark_worst")
    with c2:
        _kpi_block("Regional downtime", "412.7M", ["Σ all regions"], GREEN, fig_sparkline_green, chart_key="ra_spark_down")
    with c3:
        _kpi_block("Regions over budget", "3", ["/ 5 tracked"], ORANGE, fig_sparkline_orange, chart_key="ra_spark_over")
    with c4:
        _kpi_block("Cross-region events", "2,847", ["Deduped"], ORANGE, fig_sparkline_orange, chart_key="ra_spark_events")
    with c5:
        _kpi_block("Customer minutes", "18.2M", ["All regions"], PINK, fig_sparkline_pink, chart_key="ra_spark_cust")
    with c6:
        _kpi_block("Impacted subs", "512K", ["30-day"], PINK, fig_sparkline_pink, chart_key="ra_spark_subs")

    st.markdown('<p class="section-heading">Availability % by region</p>', unsafe_allow_html=True)
    _region_horizontal_avail_bars(
        "Trailing 30 days (weighted)",
        [
            ("South", 99.612),
            ("Mid-Atlantic", 99.523),
            ("Northeast", 99.541),
            ("West", 99.498),
            ("Central", 99.455),
        ],
        chart_key="ra_bar_region_avail",
    )

    st.markdown('<p class="section-heading">Regional category mix — Availability</p>', unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            fig_stacked_h_bar("South — summary", [("Transport", 58, GRAY), ("RAN", 28, PINK), ("Power", 14, PINK_DEEP)]),
            use_container_width=True,
            config={"displayModeBar": False},
            key="ra_bar_south_sum",
        )
    with g2:
        st.plotly_chart(
            fig_stacked_h_bar("Northeast — summary", [("Transport", 64, GRAY), ("RAN", 24, PINK), ("Power", 12, PINK_DEEP)]),
            use_container_width=True,
            config={"displayModeBar": False},
            key="ra_bar_ne_sum",
        )

    st.markdown('<p class="section-heading">Region rollup</p>', unsafe_allow_html=True)
    region_rows = [
        {"region": "South", "avail": "99.612%", "down": "98.2M", "events": "612", "budget_pct": 118},
        {"region": "Northeast", "avail": "99.541%", "down": "86.4M", "events": "534", "budget_pct": 105},
        {"region": "West", "avail": "99.498%", "down": "79.1M", "events": "498", "budget_pct": 96},
        {"region": "Central", "avail": "99.455%", "down": "91.0M", "events": "521", "budget_pct": 112},
        {"region": "Mid-Atlantic", "avail": "99.523%", "down": "58.0M", "events": "382", "budget_pct": 89},
    ]
    rh = "<tr><th>Region</th><th>Avail%</th><th>Downtime</th><th>Events</th><th>Budget</th></tr>"
    rb = []
    for r in region_rows:
        rb.append(
            "<tr>"
            f'<td>{r["region"]}</td><td class="avail">{r["avail"]}</td>'
            f'<td class="down">{r["down"]}</td><td>{r["events"]}</td>'
            f'<td>{_budget_bar_html(r["budget_pct"])} <span style="color:{TEXT_MUTED};font-size:11px">{r["budget_pct"]}%</span></td>'
            "</tr>"
        )
    st.markdown(f'<table class="fos-table">{rh}{"".join(rb)}</table>', unsafe_allow_html=True)
    st.caption("Drill to **Area Availability** for markets within a region.")


def render_area_availability() -> None:
    st.markdown("### Area availability")
    st.caption("Market / ring-level view · sample data.")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        _kpi_block("Markets in view", "42", ["Filtered set"], GREEN, fig_sparkline_green, chart_key="aa_spark_mkts")
    with c2:
        _kpi_block("Area avail (avg)", "99.501%", ["Weighted by cells"], GREEN, fig_sparkline_green, chart_key="aa_spark_avail")
    with c3:
        _kpi_block("Sites &lt; 99.9%", "186", ["Action queue"], ORANGE, fig_sparkline_orange, chart_key="aa_spark_sites")
    with c4:
        _kpi_block("Area downtime", "79.1M", ["West sample"], ORANGE, fig_sparkline_orange, chart_key="aa_spark_down")
    with c5:
        _kpi_block("Cust minutes", "3.4M", ["This area"], PINK, fig_sparkline_pink, chart_key="aa_spark_cust")
    with c6:
        _kpi_block("Impacted subs", "94K", ["This area"], PINK, fig_sparkline_pink, chart_key="aa_spark_subs")

    st.markdown('<p class="section-heading">Availability % by market (West)</p>', unsafe_allow_html=True)
    _region_horizontal_avail_bars(
        "Top markets by population weight",
        [
            ("Houston", 99.582),
            ("Dallas", 99.541),
            ("Phoenix", 99.498),
            ("Denver", 99.455),
            ("Seattle", 99.521),
            ("Portland", 99.389),
        ],
        chart_key="aa_bar_market_avail",
        height=320,
    )

    st.markdown('<p class="section-heading">Category mix — focus (area)</p>', unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            fig_stacked_h_bar(
                "Availability — focus",
                [
                    ("Transport-AAV", 52, GRAY),
                    ("Site Mod", 24, PINK),
                    ("Maintenance", 9, PINK_DEEP),
                    ("Decommission", 6, "#7f1d1d"),
                    ("Other", 9, "#4b5563"),
                ],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="aa_bar_avail_focus",
        )
    with g2:
        st.plotly_chart(
            fig_stacked_h_bar(
                "COTTR — focus",
                [
                    ("Transport-AAV", 62, GRAY),
                    ("Site Mod", 14, PINK),
                    ("Maintenance", 12, PINK_DEEP),
                    ("Decommission", 5, "#7f1d1d"),
                    ("Other", 7, "#4b5563"),
                ],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="aa_bar_cottr_focus",
        )

    st.markdown('<p class="section-heading">Markets — downtime &amp; budget</p>', unsafe_allow_html=True)
    mrows = [
        {"name": "Houston", "down": "22.1M", "avail": "99.582%", "budget_pct": 108, "delta": "+8.2M", "sites": "412"},
        {"name": "Dallas", "down": "18.4M", "avail": "99.541%", "budget_pct": 96, "delta": "−2.1M", "sites": "398"},
        {"name": "Phoenix", "down": "15.2M", "avail": "99.498%", "budget_pct": 91, "delta": "−5.8M", "sites": "355"},
        {"name": "Denver", "down": "12.8M", "avail": "99.455%", "budget_pct": 124, "delta": "+14.2M", "sites": "287"},
    ]
    st.markdown(_field_ops_table_html("Markets (sample)", mrows), unsafe_allow_html=True)


def render_availability_detail() -> None:
    st.markdown("### Availability detail")
    st.caption("Summary + focus drivers · hourly / cell drill-down placeholder rows.")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        _kpi_block("Avail % (detail)", "99.55%", ["Cell weighted"], GREEN, fig_sparkline_green, chart_key="ad_spark_avail")
    with c2:
        _kpi_block("Downtime (sec)", "96.3M", ["Same scope as Site"], GREEN, fig_sparkline_green, chart_key="ad_spark_down")
    with c3:
        _kpi_block("Planned work %", "18%", ["Of total downtime"], ORANGE, fig_sparkline_orange, chart_key="ad_spark_planned")
    with c4:
        _kpi_block("Unplanned %", "82%", ["Transport-heavy"], ORANGE, fig_sparkline_orange, chart_key="ad_spark_unplan")
    with c5:
        _kpi_block("Mean restore (h)", "4.2", ["Rolling 7d"], PINK, fig_sparkline_pink, chart_key="ad_spark_mtr")
    with c6:
        _kpi_block("Repeat sites", "54", ["2+ events / 30d"], PINK, fig_sparkline_pink, chart_key="ad_spark_repeat")

    st.markdown('<p class="section-heading">Driver breakdown</p>', unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            fig_stacked_h_bar(
                "Availability — summary",
                [("Transport", 61, GRAY), ("RAN", 26, PINK), ("Power", 12, PINK_DEEP)],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="ad_bar_avail_sum",
        )
        st.plotly_chart(
            fig_stacked_h_bar(
                "Availability — focus",
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
            key="ad_bar_avail_focus",
        )
    with g2:
        st.plotly_chart(
            fig_stacked_h_bar(
                "Top drag — vendor slice",
                [("Vendor A", 44, GRAY), ("Vendor B", 31, PINK), ("Vendor C", 18, PINK_DEEP), ("Other", 7, "#4b5563")],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="ad_bar_vendor",
        )
        st.plotly_chart(
            fig_stacked_h_bar(
                "Technology slice",
                [("LTE", 48, GRAY), ("5G NR", 35, PINK), ("Legacy", 17, PINK_DEEP)],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="ad_bar_tech",
        )

    st.markdown('<p class="section-heading">Largest downtime contributors</p>', unsafe_allow_html=True)
    top_rows = [
        {"name": "4NBS301A · NE", "down": "12.4Ms", "avail": "98.921%", "budget_pct": 142, "delta": "+18.2M", "sites": "1"},
        {"name": "3JES302D · Upstate", "down": "9.8Ms", "avail": "99.102%", "budget_pct": 128, "delta": "+11.0M", "sites": "1"},
        {"name": "9ME7125A · Memphis", "down": "8.1Ms", "avail": "99.201%", "budget_pct": 119, "delta": "+6.4M", "sites": "1"},
    ]
    st.markdown(_field_ops_table_html("Sites (sample)", top_rows), unsafe_allow_html=True)


def render_cottr_detail() -> None:
    st.markdown("### COTTR detail")
    st.caption("Cause-outage time to restore · category and regional COTTR view.")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        _kpi_block("COTTR index", "1.08", ["vs target 1.00"], GREEN, fig_sparkline_green, chart_key="cd_spark_idx")
    with c2:
        _kpi_block("Transport COTTR %", "76%", ["Of COTTR minutes"], GREEN, fig_sparkline_green, chart_key="cd_spark_trans")
    with c3:
        _kpi_block("RAN COTTR %", "16%", ["Of COTTR minutes"], ORANGE, fig_sparkline_orange, chart_key="cd_spark_ran")
    with c4:
        _kpi_block("Median TTR (h)", "3.6", ["Enterprise"], ORANGE, fig_sparkline_orange, chart_key="cd_spark_ttr")
    with c5:
        _kpi_block("Chronic tickets", "88", ["&gt; 72h open"], PINK, fig_sparkline_pink, chart_key="cd_spark_chronic")
    with c6:
        _kpi_block("Escalations", "124", ["7-day"], PINK, fig_sparkline_pink, chart_key="cd_spark_esc")

    st.markdown('<p class="section-heading">COTTR category mix</p>', unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            fig_stacked_h_bar(
                "COTTR — summary",
                [("Transport", 76, GRAY), ("RAN", 16, PINK), ("Other", 8, "#4b5563")],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="cd_bar_sum",
        )
        st.plotly_chart(
            fig_stacked_h_bar(
                "COTTR — focus",
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
            key="cd_bar_focus",
        )
    with g2:
        st.plotly_chart(
            fig_stacked_h_bar(
                "COTTR — by resolution",
                [("Remote", 38, GRAY), ("Dispatch", 34, PINK), ("Vendor", 21, PINK_DEEP), ("Other", 7, "#4b5563")],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="cd_bar_resolution",
        )
        st.plotly_chart(
            fig_stacked_h_bar(
                "COTTR — priority",
                [("P1", 22, PINK_DEEP), ("P2", 41, PINK), ("P3", 28, GRAY), ("P4", 9, "#4b5563")],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="cd_bar_priority",
        )

    st.markdown('<p class="section-heading">COTTR by region</p>', unsafe_allow_html=True)
    cottr_reg = [
        {"name": "South", "down": "412Kh", "avail": "—", "budget_pct": 115, "delta": "+58Kh", "sites": "612"},
        {"name": "Northeast", "down": "388Kh", "avail": "—", "budget_pct": 102, "delta": "+12Kh", "sites": "534"},
        {"name": "West", "down": "301Kh", "avail": "—", "budget_pct": 94, "delta": "−18Kh", "sites": "498"},
    ]
    st.markdown(_field_ops_table_html("Regions — COTTR minutes (000s hours shown as Kh)", cottr_reg), unsafe_allow_html=True)


def render_customer_minutes_detail() -> None:
    st.markdown("### Customer minutes detail")
    st.caption("Customer-impacting minutes and subscriber estimates.")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        _kpi_block("Customer minutes", "18.2M", ["30-day enterprise"], PINK, fig_sparkline_pink, chart_key="cmd_spark_cm")
    with c2:
        _kpi_block("Per 1K subs", "412", ["Normalized"], PINK, fig_sparkline_pink, chart_key="cmd_spark_per1k")
    with c3:
        _kpi_block("Peak hour share", "28%", ["Of daily CM"], ORANGE, fig_sparkline_orange, chart_key="cmd_spark_peak")
    with c4:
        _kpi_block("VoLTE share", "61%", ["Of CM"], ORANGE, fig_sparkline_orange, chart_key="cmd_spark_volte")
    with c5:
        _kpi_block("Data share", "34%", ["Of CM"], GREEN, fig_sparkline_green, chart_key="cmd_spark_data")
    with c6:
        _kpi_block("Voice share", "5%", ["Of CM"], GREEN, fig_sparkline_green, chart_key="cmd_spark_voice")

    st.markdown('<p class="section-heading">Customer impact — root cause mix</p>', unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            fig_stacked_h_bar(
                "CM — summary drivers",
                [("Transport", 58, GRAY), ("RAN", 28, PINK), ("Power / other", 14, PINK_DEEP)],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="cmd_bar_sum",
        )
    with g2:
        st.plotly_chart(
            fig_stacked_h_bar(
                "CM — focus drivers",
                [
                    ("Transport-AAV", 51, GRAY),
                    ("Site Mod", 21, PINK),
                    ("Maintenance", 11, PINK_DEEP),
                    ("Decommission", 9, "#7f1d1d"),
                    ("Other", 8, "#4b5563"),
                ],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="cmd_bar_focus",
        )

    st.markdown('<p class="section-heading">Top customer-minute events</p>', unsafe_allow_html=True)
    cm_rows = [
        {"name": "INC125456764 · Transport", "down": "842K CM", "avail": "—", "budget_pct": 0, "delta": "P1", "sites": "12"},
        {"name": "INC125382397 · RAN HW", "down": "610K CM", "avail": "—", "budget_pct": 0, "delta": "P2", "sites": "8"},
        {"name": "CHG022057647 · Rehome", "down": "445K CM", "avail": "—", "budget_pct": 0, "delta": "CHG", "sites": "15"},
    ]
    st.markdown(_field_ops_table_html("Events (sample)", cm_rows), unsafe_allow_html=True)


def render_data_diagnostics() -> None:
    st.markdown("### Data diagnostics")
    st.caption("Pipeline health, freshness, and row counts — operational QA.")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        _kpi_block("Last fact load", "OK", ["2h 14m ago"], GREEN, fig_sparkline_green, chart_key="dd_spark_load")
    with c2:
        _kpi_block("Freshness SLA", "98.2%", ["Met / 7d"], GREEN, fig_sparkline_green, chart_key="dd_spark_fresh")
    with c3:
        _kpi_block("Hourly rows", "1.42M", ["Latest partition"], ORANGE, fig_sparkline_orange, chart_key="dd_spark_rows")
    with c4:
        _kpi_block("Null key rate", "0.02%", ["Below threshold"], ORANGE, fig_sparkline_orange, chart_key="dd_spark_null")
    with c5:
        _kpi_block("Dup SH keys", "0", ["Last run"], PINK, fig_sparkline_pink, chart_key="dd_spark_dup")
    with c6:
        _kpi_block("QA failures", "3", ["Open tickets"], PINK, fig_sparkline_pink, chart_key="dd_spark_qa")

    st.markdown('<p class="section-heading">Ingest volume trend</p>', unsafe_allow_html=True)
    st.plotly_chart(
        fig_sparkline(GREEN, seed=42, n=36),
        use_container_width=True,
        config={"displayModeBar": False},
        key="dd_spark_ingest",
    )

    st.markdown('<p class="section-heading">Source checks</p>', unsafe_allow_html=True)
    checks = [
        {"check": "VQTM hourly → Snowflake", "status": "Pass", "detail": "Lag 114m"},
        {"check": "COTTR bridge join", "status": "Pass", "detail": "0.01% orphan"},
        {"check": "Customer minute allocation", "status": "Warn", "detail": "3 markets stale"},
        {"check": "Reference geography", "status": "Pass", "detail": "v2026.03.18"},
    ]
    ch = "<tr><th>Check</th><th>Status</th><th>Detail</th></tr>"
    cb = []
    for c in checks:
        if c["status"] == "Pass":
            cls = "avail"
        elif c["status"] == "Fail":
            cls = "down"
        elif c["status"] == "Warn":
            cls = "warn"
        else:
            cls = ""
        st_style = f' class="{cls}"' if cls else ""
        cb.append(
            f"<tr><td>{c['check']}</td><td{st_style}>{c['status']}</td><td>{c['detail']}</td></tr>"
        )
    st.markdown(f'<table class="fos-table">{ch}{"".join(cb)}</table>', unsafe_allow_html=True)

    st.markdown('<p class="section-heading">Partition coverage</p>', unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            fig_stacked_h_bar(
                "Rows by region (%)",
                [("South", 28, GRAY), ("NE", 22, PINK), ("West", 20, PINK_DEEP), ("Central", 18, "#7f1d1d"), ("Other", 12, "#4b5563")],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="dd_bar_region_pct",
        )
    with g2:
        st.plotly_chart(
            fig_stacked_h_bar(
                "Late arrivals (&gt; 4h)",
                [("On time", 94, GREEN), ("Late", 6, PINK)],
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="dd_bar_late",
        )


TAB_RENDERERS = {
    "Executive Summary": render_executive_summary,
    "Site Analysis": render_site_analysis,
    "Region Availability": render_region_availability,
    "Area Availability": render_area_availability,
    "Availability Detail": render_availability_detail,
    "COTTR Detail": render_cottr_detail,
    "Customer Minutes Detail": render_customer_minutes_detail,
    "Data Diagnostics": render_data_diagnostics,
}


def main() -> None:
    st.markdown('<div class="sla-toprow"><span class="deploy-link">Deploy</span></div>', unsafe_allow_html=True)
    tabs = st.tabs(NAV_ITEMS)
    for i, tab in enumerate(tabs):
        with tab:
            name = NAV_ITEMS[i]
            TAB_RENDERERS[name]()


if __name__ == "__main__":
    main()
