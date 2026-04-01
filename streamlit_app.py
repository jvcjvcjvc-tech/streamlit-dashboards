"""
MagentaBuilt site access + MB data integrity — Streamlit UI.

Additional page (sidebar): **Incident RF / Field Ops — stale notes** (`pages/1_Incident_RF_FieldOps_Stale.py`)
runs the incident extract CSV + charts.

Run from this folder:
  .\\.venv\\Scripts\\python.exe -m streamlit run streamlit_app.py

Or:
  streamlit run streamlit_app.py

Streamlit Community Cloud ([share.streamlit.io/deploy](https://share.streamlit.io/deploy)):
  Set main file to this module (repo + entrypoint only). Commit
  `build_magenta_site_access_dashboard.py` with the app; it is not configured on the deploy form.
  Browser / interactive Snowflake SSO does not work on Community Cloud — use CSV upload or
  non-interactive auth; optional `secrets.toml`: `[deploy] is_cloud = true` to force hosted UI.
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

HERE = Path(__file__).resolve().parent
DEFAULT_CSV = HERE / "magenta_site_access_results.csv"
SQL_FILE = HERE / "magenta_site_access_dashboard.sql"
AGENT = HERE / "simple_agent_with_sso_auth.py"
BUILD_HTML_DASHBOARD = HERE / "build_magenta_site_access_dashboard.py"
STATIC_HTML = HERE / "magenta_site_access_dashboard.html"

INTEGRITY_POWER = [
    "POWER_METER",
    "BREAKER_SIZE",
    "GEN_PLUG",
    "PORTABLE_GENERATOR_CAPABLE",
    "PORTABLE_GEN_PLUG",
    "PORTABLE_GEN_CORD_LENGTH",
]
INTEGRITY_ACCESS = [
    "FOPS_ASSIGNEE",
    "ACCESS_DETAILS",
    "SITE_DIRECTIONS",
    "SITE_24X7",
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
]


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name)
    if v is None:
        return False
    return v.strip().lower() in ("1", "true", "yes", "on")


def is_hosted_streamlit_deploy() -> bool:
    """
    Heuristic: Streamlit Community Cloud has no interactive browser for Snowflake SSO and
    often a read-only or ephemeral repo mount. Override locally with env
    STREAMLIT_DISABLE_SNOWFLAKE_SSO=1 to test hosted behavior.
    """
    if _env_truthy("STREAMLIT_DISABLE_SNOWFLAKE_SSO"):
        return True
    if Path("/mount/src").is_dir():
        return True
    if os.environ.get("STREAMLIT_COMMUNITY_CLOUD", "").strip().lower() in ("1", "true"):
        return True
    return False


def secrets_flag_is_cloud() -> bool | None:
    """If ``[deploy] is_cloud`` is in secrets, that value wins; else None (use heuristic)."""
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


def month_bucket_series(s: pd.Series) -> pd.Series:
    out = pd.Series(dtype=object, index=s.index)
    for i, v in s.items():
        if pd.isna(v) or str(v).strip() == "":
            continue
        raw = str(v).strip()[:26]
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                out[i] = datetime.strptime(raw, fmt).strftime("%Y-%m")
                break
            except ValueError:
                pass
        else:
            if len(raw) >= 7 and raw[4] == "-":
                out[i] = raw[:7]
    return out


def super_region(s: str | float) -> str | None:
    if pd.isna(s):
        return None
    r = str(s).strip().upper()
    if r == "WEST":
        return "WEST"
    if r in ("NORTHEAST", "CENTRAL", "SOUTH"):
        return "EAST"
    return None


def populated(val) -> bool:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return False
    return str(val).strip() != ""


def row_group_ok(row: pd.Series, fields: list[str]) -> bool:
    for f in fields:
        if f not in row.index or not populated(row.get(f)):
            return False
    return True


@dataclass
class Bucket:
    match: int = 0
    no_match: int = 0

    def add(self, ok: bool) -> None:
        if ok:
            self.match += 1
        else:
            self.no_match += 1

    @property
    def total(self) -> int:
        return self.match + self.no_match

    def pct(self) -> float:
        return 100.0 * self.match / self.total if self.total else 0.0


def compute_integrity_frames(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    cols = set(df.columns)
    power_f = [c for c in INTEGRITY_POWER if c in cols]
    access_f = [c for c in INTEGRITY_ACCESS if c in cols]
    all_f = power_f + access_f

    categories = [("All Fields", all_f), ("Power", power_f), ("Access", access_f)]
    stats: dict[str, dict[str, Bucket]] = {}
    for name, fields in categories:
        if fields:
            stats[name] = {"EAST": Bucket(), "WEST": Bucket()}

    region_series = col(df, "REGION", "Region")
    for idx in df.index:
        sr = super_region(region_series.get(idx, ""))
        if sr is None:
            continue
        row = df.loc[idx]
        for cat_name, fields in categories:
            if not fields or cat_name not in stats:
                continue
            stats[cat_name][sr].add(row_group_ok(row, fields))

    rows_out = []
    for title in ["All Fields", "Power", "Access"]:
        if title not in stats:
            continue
        east, west = stats[title]["EAST"], stats[title]["WEST"]
        tot_m = east.match + west.match
        tot_nm = east.no_match + west.no_match
        tot_all = tot_m + tot_nm
        tot_pct = 100.0 * tot_m / tot_all if tot_all else 0.0
        for label, b, pct in [
            ("EAST", east, east.pct()),
            ("WEST", west, west.pct()),
            ("Total", None, tot_pct),
        ]:
            if b is None:
                rows_out.append(
                    {
                        "Category": title,
                        "Super region": label,
                        "Match": tot_m,
                        "No Match": tot_nm,
                        "Total": tot_all,
                        "% Correct": round(pct, 2),
                    }
                )
            else:
                rows_out.append(
                    {
                        "Category": title,
                        "Super region": label,
                        "Match": b.match,
                        "No Match": b.no_match,
                        "Total": b.total,
                        "% Correct": round(pct, 2),
                    }
                )

    return pd.DataFrame(rows_out), power_f, access_f


@st.cache_data(show_spinner=False)
def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def run_build_html_dashboard() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BUILD_HTML_DASHBOARD)],
        cwd=str(HERE),
        capture_output=True,
        text=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="MagentaBuilt — Site access",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    hosted = is_hosted_streamlit_deploy()
    cloud_secret = secrets_flag_is_cloud()
    if cloud_secret is not None:
        hosted = cloud_secret

    st.sidebar.header("Data source")
    if hosted:
        st.sidebar.info(
            "**Streamlit Community Cloud (or hosted mode):** browser Snowflake SSO and "
            "rebuilding static HTML on the server are disabled. Run export + "
            "`build_magenta_site_access_dashboard.py` on your machine, commit what you need, "
            "or use **Upload CSV** below."
        )
    default_path = (
        str(DEFAULT_CSV.resolve())
        if DEFAULT_CSV.is_file()
        else ("" if hosted else str(DEFAULT_CSV.resolve()))
    )
    path_input = st.sidebar.text_input("CSV path", value=default_path, help="Export from Snowflake or choose another file.")
    uploaded = st.sidebar.file_uploader("Or upload CSV", type=["csv"])

    if st.sidebar.button(
        "Refresh from Snowflake (SSO)",
        help="Runs simple_agent_with_sso_auth.py then build_magenta_site_access_dashboard.py; complete browser login when prompted.",
        disabled=hosted,
    ):
        cmd = [
            sys.executable,
            str(AGENT),
            str(SQL_FILE),
            str(DEFAULT_CSV),
        ]
        with st.spinner("Snowflake export… check browser for SSO."):
            r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True)
        if r.returncode != 0:
            st.sidebar.error(r.stderr or r.stdout or "Export failed.")
        else:
            with st.spinner("Building static HTML dashboard…"):
                b = run_build_html_dashboard()
            if b.returncode != 0:
                st.sidebar.warning(
                    (b.stderr or b.stdout or "HTML build failed.")
                    + f"\nCSV is updated at {DEFAULT_CSV}."
                )
            else:
                st.sidebar.success(f"Export + HTML OK · {STATIC_HTML.name}")
            st.cache_data.clear()
            st.rerun()

    if st.sidebar.button(
        "Rebuild static HTML only",
        help=f"Runs build_magenta_site_access_dashboard.py (reads {DEFAULT_CSV.name}).",
        disabled=hosted,
    ):
        if not DEFAULT_CSV.is_file():
            st.sidebar.error(f"CSV not found: {DEFAULT_CSV}")
        else:
            with st.spinner("Building static HTML…"):
                b = run_build_html_dashboard()
            if b.returncode != 0:
                st.sidebar.error(b.stderr or b.stdout or "Build failed.")
            else:
                st.sidebar.success(f"Wrote {STATIC_HTML.name}")

    if uploaded is not None:
        df = pd.read_csv(uploaded, low_memory=False)
        data_label = uploaded.name
    else:
        p = Path(path_input.strip()) if path_input.strip() else Path("")
        if not path_input.strip() or not p.is_file():
            if hosted:
                st.error(
                    "No CSV loaded. Upload a CSV in the sidebar, or add a data file to the repo and set **CSV path**."
                )
            else:
                tried = path_input.strip() or default_path or str(DEFAULT_CSV)
                st.error(f"File not found: {tried}")
            st.stop()
        df = load_csv(str(p.resolve()))
        data_label = p.name

    st.title("MagentaBuilt — Site access & FOPS")
    st.caption(f"**{data_label}** · {len(df):,} rows")

    reg = col(df, "REGION", "Region").fillna("(blank)").astype(str).str.strip().replace("", "(blank)")
    mkt = col(df, "MARKET", "Market").fillna("(blank)").astype(str).str.strip().replace("", "(blank)")
    site_class = col(df, "SITE_CLASS", "Site_Class").fillna("(blank)").astype(str).str.strip().replace("", "(blank)")
    status = col(df, "MAGENTABUILT_STATUS", "MagentaBuilt_Status").fillna("(blank)").astype(str).str.strip()
    assignee = col(df, "FOPS_ASSIGNEE", "FOPS_Assignee").fillna("(unassigned)").astype(str).str.strip().replace("", "(unassigned)")
    oa = col(df, "OA_DATE", "OA_Date")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sites (rows)", f"{len(df):,}")
    c2.metric("Distinct regions", f"{reg.nunique():,}")
    c3.metric("Distinct markets", f"{mkt.nunique():,}")
    c4.metric("FOPS assignees", f"{assignee.nunique():,}")

    st.subheader("MB Data Integrity — Super Regional Data")
    st.caption("EAST = NORTHEAST + CENTRAL + SOUTH · WEST = WEST")
    integ_df, power_fields, access_fields = compute_integrity_frames(df)
    st.dataframe(integ_df, use_container_width=True, hide_index=True)
    with st.expander("Field groups (completeness)"):
        st.write("**Power**")
        st.code(", ".join(power_fields))
        st.write("**Access**")
        st.code(", ".join(access_fields))

    st.subheader("Charts")
    r_counts = reg.value_counts().head(12)
    fig_r = px.bar(x=r_counts.index, y=r_counts.values, labels={"x": "Region", "y": "Sites"}, title="Sites by region")
    fig_r.update_layout(height=320, margin=dict(t=40, b=40))

    months = month_bucket_series(oa)
    m_counts = months.dropna().value_counts().sort_index()
    fig_m = px.line(x=m_counts.index, y=m_counts.values, markers=True, title="On-air by month (OA_DATE)")
    fig_m.update_layout(height=320, margin=dict(t=40, b=40))

    mk_counts = mkt.value_counts().head(15)
    fig_mk = px.bar(x=mk_counts.values, y=mk_counts.index, orientation="h", title="Top markets")
    fig_mk.update_layout(height=320, margin=dict(t=40, b=40))

    sc_counts = site_class.value_counts().head(12)
    fig_sc = px.pie(names=sc_counts.index, values=sc_counts.values, title="Site class")

    st_counts = status.value_counts()
    fig_st = px.pie(names=st_counts.index, values=st_counts.values, title="MagentaBuilt status")

    as_counts = assignee.value_counts().head(12)
    fig_as = px.bar(x=as_counts.values, y=as_counts.index, orientation="h", title="Top FOPS assignees")
    fig_as.update_layout(height=320, margin=dict(t=40, b=40))

    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(fig_r, use_container_width=True)
    with g2:
        st.plotly_chart(fig_m, use_container_width=True)
    g3, g4 = st.columns(2)
    with g3:
        st.plotly_chart(fig_mk, use_container_width=True)
    with g4:
        st.plotly_chart(fig_sc, use_container_width=True)
    g5, g6 = st.columns(2)
    with g5:
        st.plotly_chart(fig_st, use_container_width=True)
    with g6:
        st.plotly_chart(fig_as, use_container_width=True)

    st.subheader("Data table")
    q = st.text_input("Filter (contains, any column)", "")
    show_cols = [
        c
        for c in [
            "REGION",
            "MARKET",
            "SITEID",
            "SITE_NAME",
            "SITE_CLASS",
            "MAGENTABUILT_STATUS",
            "OA_DATE",
            "FOPS_ASSIGNEE",
            "DEV_MANAGER",
            "POWER_COMPLETE",
            "ACCESS_COMPLETE",
        ]
        if c in df.columns
    ]
    view = df[show_cols] if show_cols else df
    if q.strip():
        mask = view.astype(str).apply(lambda r: r.str.lower().str.contains(q.strip().lower(), na=False)).any(axis=1)
        view = view.loc[mask]
    st.dataframe(view, use_container_width=True, height=480)
    st.caption(f"Showing {len(view):,} rows (filtered from {len(df):,}).")


if __name__ == "__main__":
    main()
