"""
RF / Field Ops / Switch incidents — stale work notes (30+ days or no note).

Data: incident_rf_fieldops_stale_notes.csv (can be very large — uses a slim column
set by default so charts/metrics load without reading multi‑GB text fields).

Run:  streamlit run streamlit_app.py  → open this page in the sidebar.
Or:   streamlit run pages/1_Incident_RF_FieldOps_Stale.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    import plotly  # noqa: F401
except ImportError:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "plotly>=5.18.0"],
    )

import pandas as pd
import plotly.express as px
import streamlit as st

# Repo root (parent of pages/)
HERE = Path(__file__).resolve().parent.parent
DEFAULT_CSV = HERE / "incident_rf_fieldops_stale_notes.csv"
SQL_FILE = HERE / "incident_rf_fieldops_switch_notes.sql"
AGENT = HERE / "simple_agent_with_sso_auth.py"
# Writable in Streamlit in Snowflake when the app stage directory is read-only
SNOWFLAKE_SIS_EXPORT = Path("/tmp/incident_rf_fieldops_stale_notes.csv")

# Columns needed for charts, filters, and the main table (no heavy text).
SLIM_COLS = [
    "REPORT_TYPE",
    "TT_ID",
    "REGION_NAME",
    "MKT_CODE",
    "MARKETNAME",
    "M_AREA",
    "ELEMENT_ID",
    "ELEMENT_CLASS",
    "S_SITE_LATITUDE",
    "S_SITE_LONGITUDE",
    "CREATED_DATE",
    "RESOLVED_DATE",
    "DAYS_OPEN",
    "HOURS_OPEN",
    "STATUS_DESC",
    "GROUP_NAME",
    "ASSIGNED_TO",
    "MANAGER",
    "PRIORITY_ID",
    "AGETKT",
    "LDT_OPEN",
    "LDT_OPEN_2",
    "GROUP_CATEGORY",
    "SOURCE",
    "LAST_NOTE_DT",
    "ACTUAL_ETA",
    "ESTIMATED_ETA",
    "ESTIMATED_ETR",
    "MTTR_HR",
    "ALL_ETA_ETR",
    "ETA_ETR",
    "ESTIMATED_ETR_VALID",
    "ESTIMATED_ETR_EXPIRED",
    "ESTIMATED_ETR_NEAR_EXPIRE",
    "ESTIMATED_ETR_BLANK",
    "RESOLVED_BY",
    "TICKET_SLA",
    "AUTO_CLOSE",
    "CATEGORY",
    "SUBCATEGORY",
    "OPENED_BY",
    "URL",
    "REFRESHED_AT",
]

LARGE_FILE_BYTES = 80 * 1024 * 1024  # 80 MB — use slim columns

# Magenta-forward bar/pie colors; chart text uses blue (see finalize_chart)
TM_MAGENTA = "#E20074"
CHART_MAGENTAS = ("#E20074", "#EC407A", "#AD1457", "#F06292", "#C2185B", "#880E4F", "#F48FB1")

# UI / chart typography — bold blue
UI_BLUE = "#0d47a1"
UI_BLUE_LIGHT = "#1565c0"
CHART_FONT_BLUE = "#0d47a1"
CHART_FONT_SIZE = 13
CHART_TITLE_SIZE = 15


def inject_dashboard_typography() -> None:
    """Bold blue text across this page (main + sidebar)."""
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
          .main .stMarkdown strong {{
            color: {UI_BLUE} !important;
            font-weight: 700 !important;
          }}
          .main [data-testid="stCaptionContainer"] {{
            color: {UI_BLUE_LIGHT} !important;
            font-weight: 600 !important;
          }}
          [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
            color: {UI_BLUE} !important;
            font-weight: 700 !important;
          }}
          [data-testid="stSidebar"] .stMarkdown p,
          [data-testid="stSidebar"] label,
          [data-testid="stSidebar"] span {{
            color: {UI_BLUE_LIGHT} !important;
            font-weight: 600 !important;
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


def finalize_chart(fig, height: int = 360) -> object:
    """Plotly layout: magenta data colors, bold blue titles/axes/ticks."""
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


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name)
    if v is None:
        return False
    return v.strip().lower() in ("1", "true", "yes", "on")


def snowpark_session_available() -> bool:
    """True inside Streamlit in Snowflake (embedded session — no browser SSO)."""
    try:
        from snowflake.snowpark.context import get_active_session

        get_active_session()
        return True
    except Exception:
        return False


def is_hosted_streamlit_deploy() -> bool:
    if _env_truthy("STREAMLIT_DISABLE_SNOWFLAKE_SSO"):
        return True
    if Path("/mount/src").is_dir():
        return True
    if os.environ.get("STREAMLIT_COMMUNITY_CLOUD", "").strip().lower() in ("1", "true"):
        return True
    return False


def secrets_flag_is_cloud() -> bool | None:
    try:
        dep = st.secrets.get("deploy")
        if isinstance(dep, dict) and "is_cloud" in dep:
            return bool(dep["is_cloud"])
    except Exception:
        return None
    return None


def col(df: pd.DataFrame, *names: str) -> pd.Series:
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series([None] * len(df), index=df.index)


def _read_csv_smart(path: Path, *, slim: bool) -> tuple[pd.DataFrame, str]:
    """Load CSV; optionally restrict columns for large files."""
    usecols: list[str] | None = None
    note = ""
    if slim:
        # Intersect with actual header without full parse: try slim list only.
        usecols = list(SLIM_COLS)
        note = "Loaded **slim columns** only (faster for large files). Long text (LAST_NOTE, descriptions, PATH) is omitted."
    try:
        df = pd.read_csv(path, low_memory=False, usecols=usecols)
    except ValueError:
        # Some exports may drop optional columns; load all and narrow.
        df = pd.read_csv(path, low_memory=False)
        if slim:
            keep = [c for c in SLIM_COLS if c in df.columns]
            df = df[keep]
    return df, note


@st.cache_data(show_spinner="Loading CSV…")
def load_csv_cached(path_str: str, slim: bool) -> tuple[pd.DataFrame, str]:
    return _read_csv_smart(Path(path_str), slim=slim)


def days_since_last_note_series(last_note_dt: pd.Series) -> pd.Series:
    """Days from LAST_NOTE_DT to today (naive); null if no date."""
    parsed = pd.to_datetime(last_note_dt, errors="coerce")
    if parsed.isna().all():
        return pd.Series([pd.NA] * len(last_note_dt), index=last_note_dt.index, dtype="float")
    now = pd.Timestamp.now(tz=None)
    # If tz-aware timestamps appear, normalize
    delta = (now.normalize() - parsed.dt.normalize()).dt.days
    return pd.to_numeric(delta, errors="coerce")


def main() -> None:
    st.set_page_config(
        page_title="Incident RF / Field Ops — stale notes",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_dashboard_typography()

    in_sis = snowpark_session_available()
    hosted = is_hosted_streamlit_deploy()
    cloud_secret = secrets_flag_is_cloud()
    if cloud_secret is not None:
        hosted = cloud_secret
    # Community Cloud / read-only hosts: subprocess + browser SSO cannot run
    hosted_sso_blocked = hosted and not in_sis

    st.sidebar.header("Data source")
    if in_sis:
        st.sidebar.info(
            "**Streamlit in Snowflake:** refresh runs the SQL with **your current session** "
            "(no external browser). Output is written under **CSV path** (default `/tmp/...`)."
        )
    elif hosted_sso_blocked:
        st.sidebar.info(
            "**Hosted mode:** Snowflake SSO from the server is disabled. "
            "Export the CSV on your machine or **Upload CSV**."
        )
    default_path = (
        str(DEFAULT_CSV.resolve())
        if DEFAULT_CSV.is_file()
        else (
            str(SNOWFLAKE_SIS_EXPORT)
            if in_sis
            else ("" if hosted_sso_blocked else str(DEFAULT_CSV.resolve()))
        )
    )
    if "incident_csv_path_input" not in st.session_state:
        st.session_state["incident_csv_path_input"] = default_path
    st.sidebar.text_input(
        "CSV path",
        key="incident_csv_path_input",
        help=f"Local default: {DEFAULT_CSV.name}. In Snowflake SiS: often {SNOWFLAKE_SIS_EXPORT}.",
    )
    path_input = st.session_state["incident_csv_path_input"]
    uploaded = st.sidebar.file_uploader("Or upload CSV", type=["csv"])

    refresh_sso_disabled = hosted_sso_blocked or not SQL_FILE.is_file() or not AGENT.is_file()
    refresh_sis_disabled = not SQL_FILE.is_file()
    sis_help = (
        f"Runs `{SQL_FILE.name}` via Snowpark session and saves CSV (see CSV path). "
        "Requires rights on objects in the SQL."
    )
    sso_help = f"Runs: python {AGENT.name} {SQL_FILE.name} {DEFAULT_CSV.name}"

    if st.sidebar.button(
        "Refresh from Snowflake (session)" if in_sis else "Refresh from Snowflake (SSO)",
        help=sis_help if in_sis else sso_help,
        disabled=refresh_sis_disabled if in_sis else refresh_sso_disabled,
    ):
        if in_sis:
            try:
                from snowflake.snowpark.context import get_active_session
            except ImportError as e:
                st.sidebar.error(f"Snowpark not available: {e}")
            else:
                out_path = Path(path_input.strip()) if path_input.strip() else SNOWFLAKE_SIS_EXPORT
                sql_text = SQL_FILE.read_text(encoding="utf-8")
                try:
                    with st.spinner("Running SQL with Snowflake session…"):
                        session = get_active_session()
                        df = session.sql(sql_text).to_pandas()
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    df.to_csv(out_path, index=False)
                    st.session_state["incident_csv_path_input"] = str(out_path.resolve())
                    st.sidebar.success(f"Wrote {len(df):,} rows → `{out_path}`")
                    st.cache_data.clear()
                    st.rerun()
                except OSError as e:
                    st.sidebar.error(f"Could not write CSV to {out_path}: {e}")
                except Exception as e:
                    st.sidebar.error(f"Snowflake query failed: {e}")
        else:
            cmd = [sys.executable, str(AGENT), str(SQL_FILE), str(DEFAULT_CSV)]
            with st.spinner("Snowflake export… complete browser SSO if prompted."):
                r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True)
            if r.returncode != 0:
                st.sidebar.error(r.stderr or r.stdout or "Export failed.")
            else:
                st.sidebar.success(f"Wrote {DEFAULT_CSV.name} ({DEFAULT_CSV.stat().st_size:,} bytes)")
                st.cache_data.clear()
                st.rerun()

    st.sidebar.caption(
        f"CLI (local): `python {AGENT.name} {SQL_FILE.name} {DEFAULT_CSV.name}`"
    )

    if uploaded is not None:
        tmp_path = HERE / "_upload_incident_rf_temp.csv"
        tmp_path.write_bytes(uploaded.getvalue())
        slim_upload = tmp_path.stat().st_size >= LARGE_FILE_BYTES
        df, slim_note = _read_csv_smart(tmp_path, slim=slim_upload)
        data_label = uploaded.name
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
    else:
        p = Path(path_input.strip()) if path_input.strip() else Path("")
        if not path_input.strip() or not p.is_file():
            st.title("RF / Field Ops / Switch — stale work notes")
            st.warning(
                "No CSV loaded. Use **Refresh from Snowflake (SSO)** or set **CSV path** / upload."
            )
            st.code(f"{sys.executable} {AGENT} {SQL_FILE} {DEFAULT_CSV}", language="bash")
            st.stop()
        sz = p.stat().st_size
        auto_slim = sz >= LARGE_FILE_BYTES
        st.sidebar.metric("File size", f"{sz / (1024**2):,.1f} MB")
        force_slim = st.sidebar.checkbox(
            "Slim columns only (faster)",
            value=auto_slim,
            help="Skips LAST_NOTE, TT_DESCRIPTION, PATH, and other heavy text. Turn on for large exports.",
        )
        df, slim_note = load_csv_cached(str(p.resolve()), slim=force_slim)
        data_label = p.name

    if slim_note:
        st.info(slim_note)

    st.title("RF / Field Ops / Switch — stale work notes")
    st.caption(
        f"{data_label} · **{len(df):,}** rows · categories RF / FIELD OPS / SWITCH · "
        "no qualifying note or last note **> 30 days**"
    )

    refreshed = col(df, "REFRESHED_AT")
    if refreshed.notna().any():
        st.caption(f"REFRESHED_AT (sample): `{refreshed.dropna().iloc[0]}`")

    report = col(df, "REPORT_TYPE", "report_type").fillna("(blank)").astype(str)
    grp_cat = col(df, "GROUP_CATEGORY", "group_category").fillna("(blank)").astype(str)
    region = col(df, "REGION_NAME", "region_name").fillna("(blank)").astype(str)
    pri = col(df, "PRIORITY_ID", "PRIORITY", "priority_id").fillna("(blank)").astype(str)
    days = col(df, "DAYS_OPEN", "days_open")
    days_num = pd.to_numeric(days, errors="coerce")
    assign = col(df, "GROUP_NAME", "group_name").fillna("(blank)").astype(str)
    last_nd = col(df, "LAST_NOTE_DT", "last_note_dt")
    stale_days = days_since_last_note_series(last_nd)

    st.sidebar.subheader("Filters")
    rt_opts = sorted(report.unique())
    sel_rt = st.sidebar.multiselect("Report type", options=rt_opts, default=rt_opts)
    gc_opts = sorted(grp_cat.unique())
    sel_gc = st.sidebar.multiselect("Group category", options=gc_opts, default=gc_opts)
    reg_opts = sorted(region.unique())
    sel_reg = st.sidebar.multiselect("Region", options=reg_opts, default=reg_opts)

    mask = (
        report.isin(sel_rt)
        & grp_cat.isin(sel_gc)
        & region.isin(sel_reg)
    )
    dff = df.loc[mask].copy()
    report_f = report.loc[mask]
    grp_cat_f = grp_cat.loc[mask]
    region_f = region.loc[mask]
    pri_f = pri.loc[mask]
    days_num_f = days_num.loc[mask]
    assign_f = assign.loc[mask]
    stale_days_f = stale_days.loc[mask]

    open_mask = report_f == "OPEN"
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Filtered rows", f"{len(dff):,}", help="After sidebar filters")
    m2.metric("Open", f"{int(open_mask.sum()):,}")
    m3.metric("Resolved / closed", f"{int((report_f == 'RESOLVED_CLOSED').sum()):,}")
    m4.metric("Median days open", f"{days_num_f.median():.0f}" if days_num_f.notna().any() else "—")
    last_nd_f = col(dff, "LAST_NOTE_DT", "last_note_dt")
    no_note = last_nd_f.isna() | (last_nd_f.astype(str).str.strip() == "")
    m5.metric("No last note dt", f"{int(no_note.sum()):,}")

    tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Aging & stale notes", "Assignment & priority", "Data table"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            vc = report_f.value_counts()
            fig_p1 = px.pie(
                names=vc.index,
                values=vc.values,
                title="Report type",
                color_discrete_sequence=list(CHART_MAGENTAS),
            )
            finalize_chart(fig_p1)
            st.plotly_chart(fig_p1, use_container_width=True)
        with c2:
            vc = grp_cat_f.value_counts().head(14)
            fig_p2 = px.bar(
                x=vc.index,
                y=vc.values,
                title="Group category (top 14)",
                color_discrete_sequence=[TM_MAGENTA],
            )
            finalize_chart(fig_p2)
            fig_p2.update_traces(marker_line_width=0)
            st.plotly_chart(fig_p2, use_container_width=True)
        c3, c4 = st.columns(2)
        with c3:
            vc = region_f.value_counts().head(16)
            fig_p3 = px.bar(
                x=vc.values,
                y=vc.index,
                orientation="h",
                title="Region (top 16)",
                color_discrete_sequence=[TM_MAGENTA],
            )
            finalize_chart(fig_p3)
            fig_p3.update_traces(marker_line_width=0)
            st.plotly_chart(fig_p3, use_container_width=True)
        with c4:
            src = col(dff, "SOURCE", "source").fillna("(blank)").astype(str)
            vc = src.value_counts().head(12)
            fig_p4 = px.bar(
                x=vc.index,
                y=vc.values,
                title="Channel / source (top 12)",
                color_discrete_sequence=[TM_MAGENTA],
            )
            finalize_chart(fig_p4)
            fig_p4.update_traces(marker_line_width=0)
            st.plotly_chart(fig_p4, use_container_width=True)

        lat_c = "S_SITE_LATITUDE" if "S_SITE_LATITUDE" in dff.columns else None
        lon_c = "S_SITE_LONGITUDE" if "S_SITE_LONGITUDE" in dff.columns else None
        if lat_c and lon_c:
            plot_df = dff.copy()
            plot_df["_lat"] = pd.to_numeric(plot_df[lat_c], errors="coerce")
            plot_df["_lon"] = pd.to_numeric(plot_df[lon_c], errors="coerce")
            plot_df = plot_df[plot_df["_lat"].notna() & plot_df["_lon"].notna()]
            if len(plot_df) > 0:
                color_col = "REPORT_TYPE" if "REPORT_TYPE" in plot_df.columns else None
                hover_col = "TT_ID" if "TT_ID" in plot_df.columns else None
                fig_map = px.scatter_map(
                    plot_df,
                    lat="_lat",
                    lon="_lon",
                    color=color_col,
                    hover_name=hover_col,
                    zoom=3,
                    title="Incidents by site coordinates (where present)",
                    color_discrete_sequence=list(CHART_MAGENTAS),
                )
                finalize_chart(fig_map, height=440)
                fig_map.update_layout(margin=dict(t=40))
                st.plotly_chart(fig_map, use_container_width=True)

    with tab2:
        dff_open = dff.loc[open_mask]
        if len(dff_open) > 0 and "DAYS_OPEN" in dff_open.columns:
            fig_h = px.histogram(
                dff_open,
                x="DAYS_OPEN",
                nbins=40,
                title="Days open (open tickets only)",
                color_discrete_sequence=[TM_MAGENTA],
            )
            fig_h.update_layout(yaxis_title="Count", showlegend=False)
            finalize_chart(fig_h)
            fig_h.update_traces(marker_color=TM_MAGENTA)
            st.plotly_chart(fig_h, use_container_width=True)
        c1, c2 = st.columns(2)
        with c1:
            bucket = col(dff, "LDT_OPEN_2", "ldt_open_2").fillna("(blank)").astype(str)
            vc = bucket.value_counts().head(15)
            fig_b1 = px.bar(
                x=vc.values,
                y=vc.index,
                orientation="h",
                title="Open-ticket aging bucket (LDT_OPEN_2)",
                color_discrete_sequence=[TM_MAGENTA],
            )
            finalize_chart(fig_b1)
            fig_b1.update_traces(marker_line_width=0)
            st.plotly_chart(fig_b1, use_container_width=True)
        with c2:
            mkt_name = col(dff, "MARKETNAME", "marketname").fillna("(No market)").astype(str)
            stale_df = pd.DataFrame({"MARKET_NAME": mkt_name, "DAYS_SINCE_LAST_NOTE": stale_days_f})
            stale_df = stale_df.dropna(subset=["DAYS_SINCE_LAST_NOTE"])
            if len(stale_df) > 0:
                n_markets = st.slider("Markets to show (by median days)", 5, 40, 20, key="mkt_stale_n")
                g = (
                    stale_df.groupby("MARKET_NAME", as_index=False)["DAYS_SINCE_LAST_NOTE"]
                    .median()
                    .sort_values("DAYS_SINCE_LAST_NOTE", ascending=False)
                    .head(int(n_markets))
                )
                fig_s = px.bar(
                    g,
                    x="MARKET_NAME",
                    y="DAYS_SINCE_LAST_NOTE",
                    title="Median days since last note by market",
                    color_discrete_sequence=[TM_MAGENTA],
                )
                fig_s.update_xaxes(title="Market name", tickangle=-40)
                fig_s.update_yaxes(title="Median days since last note")
                finalize_chart(fig_s)
                fig_s.update_traces(marker_line_width=0)
                st.plotly_chart(fig_s, use_container_width=True)
                st.caption("Rows without a parsed LAST_NOTE_DT are excluded.")
            else:
                st.info("No parsed LAST_NOTE_DT values — cannot chart by market.")

    with tab3:
        c1, c2 = st.columns(2)
        with c1:
            vc = pri_f.value_counts().head(12)
            fig_t3a = px.bar(
                x=vc.index,
                y=vc.values,
                title="Priority (top 12)",
                color_discrete_sequence=[TM_MAGENTA],
            )
            finalize_chart(fig_t3a)
            fig_t3a.update_traces(marker_line_width=0)
            st.plotly_chart(fig_t3a, use_container_width=True)
        with c2:
            auto = pd.to_numeric(col(dff, "AUTO_CLOSE", "auto_close"), errors="coerce").fillna(0)
            fig_t3b = px.pie(
                names=["Manual/other", "Auto-close pattern"],
                values=[int((auto == 0).sum()), int((auto != 0).sum())],
                title="RESOLVED_BY SVC_PRD_ flag (AUTO_CLOSE)",
                color_discrete_sequence=[TM_MAGENTA, CHART_MAGENTAS[2]],
            )
            finalize_chart(fig_t3b)
            st.plotly_chart(fig_t3b, use_container_width=True)
        vc_a = assign_f.value_counts().head(20)
        fig_t3c = px.bar(
            x=vc_a.values,
            y=vc_a.index,
            orientation="h",
            title="Top assignment groups",
            color_discrete_sequence=[TM_MAGENTA],
        )
        finalize_chart(fig_t3c)
        fig_t3c.update_traces(marker_line_width=0)
        st.plotly_chart(fig_t3c, use_container_width=True)

    with tab4:
        q = st.text_input("Filter (contains, any shown column)", "")
        preferred = [
            "TT_ID",
            "REPORT_TYPE",
            "GROUP_CATEGORY",
            "REGION_NAME",
            "MKT_CODE",
            "MARKETNAME",
            "GROUP_NAME",
            "STATUS_DESC",
            "PRIORITY_ID",
            "DAYS_OPEN",
            "LAST_NOTE_DT",
            "LAST_NOTE",
            "LDT_OPEN_2",
            "CREATED_DATE",
            "RESOLVED_DATE",
            "SOURCE",
            "URL",
        ]
        show_cols = [c for c in preferred if c in dff.columns]
        view = dff[show_cols] if show_cols else dff
        if q.strip():
            mask_q = (
                view.astype(str)
                .apply(lambda r: r.str.lower().str.contains(q.strip().lower(), na=False))
                .any(axis=1)
            )
            view = view.loc[mask_q]

        max_rows = st.number_input("Max rows to render in browser", min_value=500, max_value=50000, value=5000, step=500)
        if len(view) > max_rows:
            st.warning(f"Showing first **{max_rows:,}** of **{len(view):,}** filtered rows (performance). Download has full filtered set.")
            show_view = view.iloc[: int(max_rows)]
        else:
            show_view = view

        st.dataframe(show_view, use_container_width=True, height=520)
        st.download_button(
            "Download filtered table as CSV",
            data=view.to_csv(index=False).encode("utf-8"),
            file_name="incident_rf_fieldops_stale_filtered.csv",
            mime="text/csv",
        )
        st.caption(
            f"Rendered {len(show_view):,} rows · filtered set {len(view):,} · source {len(dff):,} (after sidebar)."
        )


if __name__ == "__main__":
    main()
