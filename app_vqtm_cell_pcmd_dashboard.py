"""
VQTM cell daily + PCMD subscriber rule — Streamlit dashboard.

Rule: if AMF or MME PCMD COTTR QHOUR has UNIQUE_SUBSCRIBER_COUNT >= 1 for the cell
on the selected day, adjusted cell downtime = 0; else use VQTM raw downtime.

Default day: 2026-03-21. Data source: Snowflake (secrets) or demo sample / CSV upload.

  streamlit run app_vqtm_cell_pcmd_dashboard.py

SQL template: vqtm_cell_pcmd_adjusted.sql — edit column names to match DESCRIBE VIEW.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

try:
    import snowflake.connector

    _SNOWFLAKE = True
except ImportError:
    _SNOWFLAKE = False

DEFAULT_DAY = date(2026, 3, 21)
SQL_FILE = Path(__file__).resolve().parent / "vqtm_cell_pcmd_adjusted.sql"


def _load_sql_template() -> str:
    if SQL_FILE.is_file():
        return SQL_FILE.read_text(encoding="utf-8")
    return ""


def _sql_for_day(sql: str, day: date) -> str:
    ds = day.isoformat()
    out = sql.replace("DATE('2026-03-21')", f"DATE('{ds}')")
    out = out.replace("2026-03-21", ds)
    return out.strip().rstrip(";")


def _snowflake_conn():
    s = st.secrets["snowflake"]
    return snowflake.connector.connect(
        account=s["account"],
        user=s["user"],
        password=s["password"],
        warehouse=s["warehouse"],
        database=s.get("database", "BDM_QTM_PRESENTATION_SH"),
        schema=s.get("schema", "QI_SHARED"),
        role=s.get("role"),
    )


def _demo_df(n: int = 220, seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cells = [f"CELL_{i:05d}" for i in range(n)]
    has_sub = rng.random(n) < 0.35
    raw = rng.uniform(0, 3600, n).astype("float64")
    raw = (raw * (1 + rng.random(n))).clip(0, 86400)
    adj = raw.copy()
    adj[has_sub] = 0.0
    total_t = rng.uniform(80000, 86400, n)
    sites = [f"SITE_{int(x):04d}" for x in rng.integers(0, 400, n)]
    regions = rng.choice(["South", "Northeast", "West", "Central", "Mid-Atlantic"], n)
    markets = rng.choice(["Houston", "Atlanta", "Seattle", "Chicago", "Miami"], n)
    avail = 100.0 * (total_t - adj) / total_t
    return pd.DataFrame(
        {
            "CELL_KEY": cells,
            "SITE_ID": sites,
            "REGION_ID": regions,
            "MARKET_ID": markets,
            "RAW_DOWNTIME_SEC": raw,
            "TOTAL_TIME_SEC": total_t,
            "HAS_PCMD_SUBSCRIBER": has_sub,
            "ADJUSTED_DOWNTIME_SEC": adj,
            "ADJUSTED_AVAIL_PCT_APPROX": avail,
        }
    )


def main() -> None:
    st.set_page_config(page_title="VQTM cell + PCMD adjusted downtime", layout="wide")
    st.title("VQTM cell daily + PCMD subscriber rule")
    st.caption(
        "If AMF or MME PCMD shows ≥1 unique subscriber for the cell on the day, "
        "adjusted downtime = 0. Otherwise use VQTM raw downtime. "
        f"Default target day: **{DEFAULT_DAY.isoformat()}**."
    )

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        target = st.date_input("Report date", value=DEFAULT_DAY)
    with col_b:
        mode = st.radio(
            "Data source",
            ["Demo (synthetic)", "Snowflake", "Upload CSV"],
            horizontal=True,
        )
    with col_c:
        st.markdown("&nbsp;")

    df: pd.DataFrame | None = None
    err: str | None = None

    if mode == "Demo (synthetic)":
        df = _demo_df()
        st.info("Using **synthetic** data for layout testing. Connect **Snowflake** for real 2026-03-21 results.")
    elif mode == "Upload CSV":
        up = st.file_uploader("CSV from Snowflake (query result)", type=["csv"])
        if up:
            df = pd.read_csv(up, low_memory=False)
            df.columns = [str(c).upper().replace(" ", "_") for c in df.columns]
    else:
        if not _SNOWFLAKE:
            err = "snowflake-connector-python not installed."
        elif "snowflake" not in st.secrets:
            err = "Add `[snowflake]` to `.streamlit/secrets.toml`."
        else:
            sql_t = _load_sql_template()
            if not sql_t:
                err = f"Missing SQL template: {SQL_FILE}"
            else:
                q = _sql_for_day(sql_t, target)
                with st.spinner("Running Snowflake query…"):
                    try:
                        conn = _snowflake_conn()
                        df = pd.read_sql(q, conn)
                        conn.close()
                        df.columns = [str(c).upper().replace(" ", "_") for c in df.columns]
                    except Exception as e:
                        err = str(e)

    if err:
        st.error(err)
        st.markdown(
            "Edit **`vqtm_cell_pcmd_adjusted.sql`** so column names match "
            "`DESCRIBE VIEW` on:\n"
            "- `BDM_QTM_PRESENTATION_SH.QI_SHARED.VQTM_RAN_AVAILABILITY_CELL_DAILY`\n"
            "- `...PCMD_ML_LAB.VPCMD_AMF_COTTR_QHOUR_AGG`\n"
            "- `...PCMD_ML_LAB.VPCMD_MME_COTTR_QHOUR_AGG`"
        )
        with st.expander("SQL sent (after date substitution)"):
            st.code(_sql_for_day(_load_sql_template(), target) if _load_sql_template() else "")
        return

    if df is None or df.empty:
        st.warning("No rows. Check the date and view filters.")
        return

    df.columns = [str(c).upper().replace(" ", "_") for c in df.columns]

    need = [
        "RAW_DOWNTIME_SEC",
        "ADJUSTED_DOWNTIME_SEC",
        "HAS_PCMD_SUBSCRIBER",
    ]
    missing = [c for c in need if c not in df.columns]
    if missing:
        st.error(f"Result missing columns: {missing}. Got: {list(df.columns)}")
        st.dataframe(df.head(20))
        return

    n = len(df)
    sub_col = df["HAS_PCMD_SUBSCRIBER"]
    if sub_col.dtype == object:
        n_sub = int(sub_col.astype(str).str.upper().isin(["TRUE", "T", "1", "Y", "YES"]).sum())
    else:
        n_sub = int(sub_col.fillna(False).astype(bool).sum())
    raw_sum = float(df["RAW_DOWNTIME_SEC"].sum())
    adj_sum = float(df["ADJUSTED_DOWNTIME_SEC"].sum())
    delta = raw_sum - adj_sum

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Cells (rows)", f"{n:,}")
    m2.metric("Cells w/ PCMD subs (flag)", f"{n_sub:,}")
    m3.metric("Σ raw downtime (sec)", f"{raw_sum:,.0f}")
    m4.metric("Σ adjusted downtime (sec)", f"{adj_sum:,.0f}")
    m5.metric("Downtime removed by rule (sec)", f"{delta:,.0f}")

    t1, t2 = st.columns(2)
    with t1:
        if "REGION_ID" in df.columns:
            by_r = (
                df.groupby("REGION_ID", dropna=False)
                .agg(
                    cells=("CELL_KEY", "count"),
                    raw_dt=("RAW_DOWNTIME_SEC", "sum"),
                    adj_dt=("ADJUSTED_DOWNTIME_SEC", "sum"),
                    with_sub=("HAS_PCMD_SUBSCRIBER", "sum"),
                )
                .reset_index()
            )
            fig = px.bar(
                by_r,
                x="REGION_ID",
                y=["raw_dt", "adj_dt"],
                barmode="group",
                title="Downtime sec by region (raw vs adjusted)",
            )
            fig.update_layout(template="plotly_dark", height=400)
            st.plotly_chart(fig, use_container_width=True, key="pcmd_bar_region")
        else:
            st.info("No REGION_ID — skip regional chart.")

    with t2:
        pie = df["HAS_PCMD_SUBSCRIBER"].map({True: "PCMD subs ≥1", False: "No PCMD subs"})
        if df["HAS_PCMD_SUBSCRIBER"].dtype == object:
            pie = df["HAS_PCMD_SUBSCRIBER"].astype(str)
        ct = pie.value_counts().reset_index()
        ct.columns = ["bucket", "count"]
        fig2 = px.pie(ct, names="bucket", values="count", title="Cells by PCMD subscriber presence")
        fig2.update_layout(template="plotly_dark", height=400)
        st.plotly_chart(fig2, use_container_width=True, key="pcmd_pie_sub")

    top_n = st.slider("Top N cells by raw downtime", 10, 80, 25)
    worst = df.nlargest(top_n, "RAW_DOWNTIME_SEC")
    fig3 = go.Figure()
    fig3.add_trace(
        go.Bar(name="Raw", x=worst["CELL_KEY"], y=worst["RAW_DOWNTIME_SEC"], marker_color="#e94560")
    )
    fig3.add_trace(
        go.Bar(
            name="Adjusted",
            x=worst["CELL_KEY"],
            y=worst["ADJUSTED_DOWNTIME_SEC"],
            marker_color="#00d9a5",
        )
    )
    fig3.update_layout(
        barmode="group",
        template="plotly_dark",
        title=f"Top {top_n} cells by raw downtime (same cell, adjusted per rule)",
        xaxis_tickangle=-45,
        height=480,
    )
    st.plotly_chart(fig3, use_container_width=True, key="pcmd_bar_top_cells")

    st.subheader("Detail table")
    st.dataframe(df, use_container_width=True, height=420)

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        csv_bytes,
        file_name=f"vqtm_cell_pcmd_adjusted_{target.isoformat()}.csv",
        mime="text/csv",
    )

    with st.expander("SQL template (repo file)"):
        st.code(_load_sql_template() or "(missing vqtm_cell_pcmd_adjusted.sql)")


if __name__ == "__main__":
    main()
