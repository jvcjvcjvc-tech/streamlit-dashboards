"""
Incident Open Backlog Dashboard
Streamlit dashboard for visualizing open incidents for RF, Field Ops, and Switch categories.

Run locally:
  streamlit run app_incident_open_backlog.py

Deploy to Streamlit Cloud:
  Main file: app_incident_open_backlog.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

try:
    import plotly
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "plotly>=5.18.0"])

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parent
DEFAULT_CSV = HERE / "incident_open_backlog.csv"
SQL_FILE = HERE / "incident_open_backlog.sql"
AGENT = HERE / "simple_agent_with_sso_auth.py"

TM_MAGENTA = "#E20074"
CHART_MAGENTAS = ("#E20074", "#EC407A", "#AD1457", "#F06292", "#C2185B", "#880E4F", "#F48FB1")
UI_BLUE = "#0d47a1"
UI_BLUE_LIGHT = "#1565c0"
CHART_FONT_BLUE = "#0d47a1"
CHART_FONT_SIZE = 13
CHART_TITLE_SIZE = 15


def inject_dashboard_typography() -> None:
    st.markdown(
        f"""
        <style>
          .main h1, .main h2, .main h3 {{
            color: {UI_BLUE} !important;
            font-weight: 700 !important;
          }}
          .main .stMarkdown p, .main .stMarkdown li {{
            color: {UI_BLUE_LIGHT} !important;
            font-weight: 600 !important;
            font-size: 1.06rem !important;
          }}
          [data-testid="stMetricValue"] {{
            color: {UI_BLUE} !important;
            font-weight: 700 !important;
          }}
          [data-testid="stMetricLabel"] {{
            color: {UI_BLUE_LIGHT} !important;
            font-weight: 600 !important;
          }}
          .stTabs [data-baseweb="tab"] {{
            color: {UI_BLUE} !important;
            font-weight: 700 !important;
            font-size: 1rem !important;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def finalize_chart(fig, height: int = 360):
    fig.update_layout(
        template="plotly_white",
        height=height,
        plot_bgcolor="#F5FAFF",
        paper_bgcolor="#FFFFFF",
        font=dict(color=CHART_FONT_BLUE, size=CHART_FONT_SIZE, family="Arial"),
        title_font=dict(size=CHART_TITLE_SIZE, color=CHART_FONT_BLUE, family="Arial Black"),
        colorway=list(CHART_MAGENTAS),
        legend=dict(font=dict(color=CHART_FONT_BLUE, size=CHART_FONT_SIZE)),
    )
    fig.update_xaxes(
        title_font=dict(color=CHART_FONT_BLUE, size=CHART_FONT_SIZE, family="Arial Black"),
        tickfont=dict(color=CHART_FONT_BLUE, size=CHART_FONT_SIZE),
    )
    fig.update_yaxes(
        title_font=dict(color=CHART_FONT_BLUE, size=CHART_FONT_SIZE, family="Arial Black"),
        tickfont=dict(color=CHART_FONT_BLUE, size=CHART_FONT_SIZE),
    )
    return fig


def col(df: pd.DataFrame, *names: str) -> pd.Series:
    for n in names:
        if n in df.columns:
            return df[n]
        if n.upper() in df.columns:
            return df[n.upper()]
        if n.lower() in df.columns:
            return df[n.lower()]
    return pd.Series([None] * len(df), index=df.index)


def calculate_days_open(df: pd.DataFrame) -> pd.Series:
    opened = pd.to_datetime(col(df, "OPENED_AT", "OPENED_DATE", "CREATED_DATE"), errors="coerce")
    now = pd.Timestamp.now()
    return (now - opened).dt.days


@st.cache_data(show_spinner="Loading data...")
def load_csv(path_str: str) -> pd.DataFrame:
    df = pd.read_csv(path_str, low_memory=False)
    return df


def is_hosted_streamlit() -> bool:
    if Path("/mount/src").is_dir():
        return True
    if os.environ.get("STREAMLIT_COMMUNITY_CLOUD", "").strip().lower() in ("1", "true"):
        return True
    return False


def main() -> None:
    st.set_page_config(
        page_title="Incident Open Backlog",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_dashboard_typography()

    st.title("📊 Incident Open Backlog Dashboard")
    st.caption("RF / Field Ops / Switch open incidents from ServiceNow")

    hosted = is_hosted_streamlit()

    st.sidebar.header("Data Source")
    
    default_path = str(DEFAULT_CSV.resolve()) if DEFAULT_CSV.is_file() else ""
    if "csv_path" not in st.session_state:
        st.session_state["csv_path"] = default_path
    
    st.sidebar.text_input("CSV path", key="csv_path")
    uploaded = st.sidebar.file_uploader("Or upload CSV", type=["csv"])

    if st.sidebar.button("Clear Cache & Reload"):
        st.cache_data.clear()
        st.rerun()

    refresh_disabled = hosted or not SQL_FILE.is_file() or not AGENT.is_file()
    if st.sidebar.button("Refresh from Snowflake (SSO)", disabled=refresh_disabled,
                         help="Run SQL query via SSO authentication"):
        cmd = [sys.executable, str(AGENT), str(SQL_FILE), str(DEFAULT_CSV)]
        with st.spinner("Running Snowflake export... complete browser SSO if prompted."):
            r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True)
        if r.returncode != 0:
            st.sidebar.error(r.stderr or r.stdout or "Export failed.")
        else:
            st.sidebar.success(f"Exported {DEFAULT_CSV.name}")
            st.cache_data.clear()
            st.rerun()

    if uploaded is not None:
        df = pd.read_csv(uploaded, low_memory=False)
        data_label = uploaded.name
        st.sidebar.info(f"Uploaded: {uploaded.name}")
        st.sidebar.write("Columns found:", list(df.columns)[:10], "...")
    else:
        csv_path = st.session_state.get("csv_path", "")
        p = Path(csv_path.strip()) if csv_path.strip() else Path("")
        if not csv_path.strip() or not p.is_file():
            st.warning("No CSV loaded. Use **Refresh from Snowflake (SSO)** or upload a CSV file.")
            st.code(f"python export_incident_open_backlog.py", language="bash")
            st.stop()
        df = load_csv(str(p.resolve()))
        data_label = p.name
        st.sidebar.metric("File size", f"{p.stat().st_size / (1024**2):,.1f} MB")

    st.sidebar.metric("Total rows", f"{len(df):,}")
    st.sidebar.metric("Columns", f"{len(df.columns)}")
    
    # Debug: Show market column info
    if "MARKET_ID" in df.columns:
        non_null = df["MARKET_ID"].notna().sum()
        st.sidebar.success(f"Markets: {non_null:,} rows have data")
    else:
        st.sidebar.error("MARKET_ID column NOT found!")
        st.sidebar.write("Columns:", list(df.columns))
    
    df["_DAYS_OPEN"] = calculate_days_open(df)

    state = col(df, "STATE", "state").fillna("(blank)").astype(str)
    group_category = col(df, "GROUP_CATEGORY").fillna("(blank)").astype(str)
    inc_category = col(df, "CATEGORY").fillna("(blank)").astype(str)
    priority = col(df, "PRIORITY", "priority").fillna("(blank)").astype(str)
    assignment_group = col(df, "ASSIGNMENT_GROUP", "assignment_group").fillna("(blank)").astype(str)
    # Find market column - try multiple names
    market_col_name = None
    for mc in ["MARKET_ID", "market_id", "M_MARKET_ABBREVATION", "MARKET_NAME"]:
        if mc in df.columns:
            market_col_name = mc
            break
    
    if market_col_name:
        market = df[market_col_name].fillna("(No market)").astype(str)
        st.sidebar.success(f"Using market column: {market_col_name}")
    else:
        market = pd.Series(["(No market)"] * len(df), index=df.index)
        st.sidebar.error("No market column found!")
    region = col(df, "RGN_RGN_ABBRV", "M_AREA", "REGION_NAME").fillna("(No region)").astype(str)

    st.sidebar.subheader("Filters")
    
    state_opts = sorted(state.unique())
    sel_state = st.sidebar.multiselect("State", options=state_opts, default=state_opts if state_opts else [])
    
    grp_cat_opts = sorted([c for c in group_category.unique() if c and c != "(blank)"])
    if not grp_cat_opts:
        grp_cat_opts = sorted(group_category.unique())
    sel_grp_cat = st.sidebar.multiselect("Group (RF/Field Ops/Switch)", options=grp_cat_opts, default=grp_cat_opts if grp_cat_opts else [])
    
    pri_opts = sorted(priority.unique())
    sel_pri = st.sidebar.multiselect("Priority", options=pri_opts, default=pri_opts if pri_opts else [])

    # Build filter mask - handle empty selections
    if sel_state and sel_grp_cat and sel_pri:
        mask = state.isin(sel_state) & group_category.isin(sel_grp_cat) & priority.isin(sel_pri)
    else:
        mask = pd.Series([True] * len(df), index=df.index)
    dff = df.loc[mask].copy()

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Open", f"{len(dff):,}")
    m2.metric("Avg Days Open", f"{dff['_DAYS_OPEN'].mean():.1f}" if len(dff) > 0 else "—")
    m3.metric("Median Days Open", f"{dff['_DAYS_OPEN'].median():.0f}" if len(dff) > 0 else "—")
    
    high_pri = priority.loc[mask].isin(["1", "1 - Critical", "P1", "Critical"])
    m4.metric("High Priority", f"{high_pri.sum():,}")
    
    aged_30 = (dff["_DAYS_OPEN"] > 30).sum()
    m5.metric("Aged > 30 days", f"{aged_30:,}")

    tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Aging Analysis", "Assignment Groups", "Data Table"])

    with tab1:
        if len(dff) == 0:
            st.warning("No data matches the current filters. Adjust filters in the sidebar.")
        else:
            c1, c2 = st.columns(2)
            
            with c1:
                vc = state.loc[mask].value_counts()
                if len(vc) > 0:
                    fig_state = px.pie(
                        names=list(vc.index),
                        values=list(vc.values),
                        title="Incidents by State",
                        color_discrete_sequence=list(CHART_MAGENTAS),
                    )
                    finalize_chart(fig_state)
                    st.plotly_chart(fig_state, use_container_width=True)
            
            with c2:
                vc = group_category.loc[mask].value_counts()
                if len(vc) > 0:
                    fig_cat = px.bar(
                        x=list(vc.index),
                        y=list(vc.values),
                        title="Incidents by Group Category",
                        color_discrete_sequence=[TM_MAGENTA],
                    )
                    finalize_chart(fig_cat)
                    st.plotly_chart(fig_cat, use_container_width=True)

            c3, c4 = st.columns(2)
            
            with c3:
                vc = priority.loc[mask].value_counts().head(10)
                if len(vc) > 0:
                    fig_pri = px.bar(
                        x=list(vc.index),
                        y=list(vc.values),
                        title="Incidents by Priority",
                        color_discrete_sequence=[TM_MAGENTA],
                    )
                    finalize_chart(fig_pri)
                    st.plotly_chart(fig_pri, use_container_width=True)
            
            with c4:
                mkt = market.loc[mask]
                vc = mkt.value_counts().head(15)
                if len(vc) > 0:
                    fig_mkt = px.bar(
                        x=list(vc.values),
                        y=list(vc.index),
                        orientation="h",
                        title="Top 15 Markets by Incident Count",
                        color_discrete_sequence=[TM_MAGENTA],
                    )
                    finalize_chart(fig_mkt)
                    st.plotly_chart(fig_mkt, use_container_width=True)

    with tab2:
        if len(dff) == 0:
            st.warning("No data to display.")
        else:
            fig_hist = px.histogram(
                dff,
                x="_DAYS_OPEN",
                nbins=50,
                title="Distribution of Days Open",
                color_discrete_sequence=[TM_MAGENTA],
            )
            fig_hist.update_layout(xaxis_title="Days Open", yaxis_title="Count")
            finalize_chart(fig_hist, height=400)
            st.plotly_chart(fig_hist, use_container_width=True)

            c1, c2 = st.columns(2)
            
            with c1:
                bins = [0, 7, 14, 30, 60, 90, 180, float('inf')]
                labels = ['0-7 days', '8-14 days', '15-30 days', '31-60 days', '61-90 days', '91-180 days', '180+ days']
                dff["_AGE_BUCKET"] = pd.cut(dff["_DAYS_OPEN"], bins=bins, labels=labels, right=True)
                vc = dff["_AGE_BUCKET"].value_counts().reindex(labels).fillna(0)
                fig_bucket = px.bar(
                    x=list(vc.index.astype(str)),
                    y=list(vc.values),
                    title="Incidents by Aging Bucket",
                    color_discrete_sequence=[TM_MAGENTA],
                )
                fig_bucket.update_layout(xaxis_title="Age Bucket", yaxis_title="Count")
                finalize_chart(fig_bucket)
                st.plotly_chart(fig_bucket, use_container_width=True)
            
            with c2:
                mkt_f = market.loc[mask]
                age_df = pd.DataFrame({"Market": mkt_f.values, "Days_Open": dff["_DAYS_OPEN"].values})
                age_df = age_df.dropna()
                if len(age_df) > 0:
                    g = (
                        age_df.groupby("Market", as_index=False)["Days_Open"]
                        .median()
                        .sort_values("Days_Open", ascending=False)
                        .head(15)
                    )
                    fig_mkt_age = px.bar(
                        g,
                        x="Market",
                        y="Days_Open",
                        title="Median Days Open by Market (Top 15)",
                        color_discrete_sequence=[TM_MAGENTA],
                    )
                    fig_mkt_age.update_xaxes(tickangle=-45)
                    finalize_chart(fig_mkt_age)
                    st.plotly_chart(fig_mkt_age, use_container_width=True)

    with tab3:
        if len(dff) == 0:
            st.warning("No data to display.")
        else:
            c1, c2 = st.columns(2)
            
            with c1:
                ag = assignment_group.loc[mask]
                vc = ag.value_counts().head(20)
                if len(vc) > 0:
                    fig_ag = px.bar(
                        x=list(vc.values),
                        y=list(vc.index),
                        orientation="h",
                        title="Top 20 Assignment Groups",
                        color_discrete_sequence=[TM_MAGENTA],
                    )
                    finalize_chart(fig_ag, height=500)
                    st.plotly_chart(fig_ag, use_container_width=True)
        
            with c2:
                assigned_to = col(dff, "ASSIGNED_TO", "assigned_to").fillna("(Unassigned)").astype(str)
                vc = assigned_to.value_counts().head(20)
                if len(vc) > 0:
                    fig_user = px.bar(
                        x=list(vc.values),
                        y=list(vc.index),
                        orientation="h",
                        title="Top 20 Assigned Users",
                        color_discrete_sequence=[TM_MAGENTA],
                    )
                    finalize_chart(fig_user, height=500)
                    st.plotly_chart(fig_user, use_container_width=True)

            ag_age = pd.DataFrame({
                "Assignment_Group": assignment_group.loc[mask].values,
                "Days_Open": dff["_DAYS_OPEN"].values
            })
            if len(ag_age) > 0:
                ag_stats = (
                    ag_age.groupby("Assignment_Group", as_index=False)
                    .agg({"Days_Open": ["count", "mean", "median"]})
                )
                ag_stats.columns = ["Assignment_Group", "Count", "Avg_Days", "Median_Days"]
                ag_stats = ag_stats.sort_values("Count", ascending=False).head(20)
                
                st.subheader("Assignment Group Statistics (Top 20)")
                st.dataframe(ag_stats.round(1), use_container_width=True, hide_index=True)

    with tab4:
        st.subheader("Incident Data")
        
        q = st.text_input("Search (filter any column)", "")
        
        display_cols = [c for c in [
            "INCIDENT_NUMBER", "STATE", "PRIORITY", "CATEGORY", "SHORT_DESCRIPTION",
            "ASSIGNMENT_GROUP", "ASSIGNED_TO", "OPENED_DATE", "_DAYS_OPEN",
            "CONFIG_ITEM", "M_MARKET_ABBREVATION", "RGN_RGN_ABBRV", "GROUP_CATEGORY"
        ] if c in dff.columns or c == "_DAYS_OPEN"]
        
        view = dff[display_cols] if display_cols else dff
        
        if q.strip():
            mask_q = (
                view.astype(str)
                .apply(lambda r: r.str.lower().str.contains(q.strip().lower(), na=False))
                .any(axis=1)
            )
            view = view.loc[mask_q]

        max_rows = st.number_input("Max rows to display", min_value=100, max_value=50000, value=5000, step=500)
        
        if len(view) > max_rows:
            st.warning(f"Showing first {max_rows:,} of {len(view):,} rows")
            show_view = view.iloc[:int(max_rows)]
        else:
            show_view = view

        st.dataframe(show_view, use_container_width=True, height=500)
        
        st.download_button(
            "Download filtered data as CSV",
            data=view.to_csv(index=False).encode("utf-8"),
            file_name="incident_open_backlog_filtered.csv",
            mime="text/csv",
        )
        
        st.caption(f"Showing {len(show_view):,} of {len(view):,} filtered rows (source: {len(dff):,} after filters)")


if __name__ == "__main__":
    main()
