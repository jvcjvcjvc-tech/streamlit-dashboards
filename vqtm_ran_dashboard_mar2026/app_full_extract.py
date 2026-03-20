"""
Browse the FULL Snowflake CSV (~1.4M rows) with server-side pagination.

Static index.html cannot embed this (file size + browser memory). Run locally:

  streamlit run app_full_extract.py

Requires enough RAM to hold the dataframe (~2–4 GB typical for this extract).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

DEFAULT_CSV = Path(
    r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR"
    r"\query_execution_agent_sso_auth 5\query_execution_agent_sso_auth"
    r"\vqtm_ran_avail_from_20260320.csv"
)


@st.cache_data(show_spinner="Loading CSV (one-time cache)…")
def load_csv(path_str: str) -> pd.DataFrame:
    return pd.read_csv(path_str, low_memory=False)


def main() -> None:
    st.set_page_config(page_title="VQTM — full extract", layout="wide")
    st.title("VQTM RAN availability — full extract dashboard")
    st.caption(
        "All **1,388,791+** rows are loaded into memory once (cached). "
        "Use pagination to scroll the table; charts use the full dataset."
    )

    path_str = st.sidebar.text_input(
        "Path to `vqtm_ran_avail_from_20260320.csv`",
        value=str(DEFAULT_CSV),
    )
    p = Path(path_str)
    if not p.is_file():
        st.error(f"File not found: {p}")
        st.stop()

    df = load_csv(str(p.resolve()))

    st.success(f"**{len(df):,}** rows × **{len(df.columns)}** columns")

    # --- KPIs (full data) ---
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Unique SITE_ID", f"{df['SITE_ID'].nunique():,}" if "SITE_ID" in df.columns else "—")
    with c2:
        if "TOTAL_DOWNTIME_LTE" in df.columns:
            lte = pd.to_numeric(df["TOTAL_DOWNTIME_LTE"], errors="coerce").fillna(0)
            st.metric("Rows LTE downtime > 0", f"{(lte > 0).sum():,}")
        else:
            st.metric("Rows LTE downtime > 0", "—")
    with c3:
        if "TOTAL_DOWNTIME_5G" in df.columns:
            g5 = pd.to_numeric(df["TOTAL_DOWNTIME_5G"], errors="coerce").fillna(0)
            st.metric("Rows 5G downtime > 0", f"{(g5 > 0).sum():,}")
        else:
            st.metric("Rows 5G downtime > 0", "—")
    with c4:
        if "PERIOD_START_TIME" in df.columns:
            st.metric("Period (min → max)", "see below")
        else:
            st.metric("Period", "—")

    if "PERIOD_START_TIME" in df.columns:
        st.caption(
            f"PERIOD_START_TIME: **{df['PERIOD_START_TIME'].min()}** → **{df['PERIOD_START_TIME'].max()}**"
        )

    st.divider()
    st.subheader("Charts (full data, aggregated)")

    cc1, cc2 = st.columns(2)
    with cc1:
        if "REGION_ID" in df.columns:
            vc = df["REGION_ID"].value_counts().head(25)
            fig = px.bar(x=vc.values, y=vc.index, orientation="h", title="Rows by REGION_ID")
            fig.update_layout(height=400, yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)
    with cc2:
        if "VENDOR" in df.columns:
            vc = df["VENDOR"].value_counts()
            fig = px.pie(values=vc.values, names=vc.index, title="Rows by VENDOR")
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("All rows — paginated table")

    rows_pp = st.sidebar.slider("Rows per page", min_value=500, max_value=50_000, value=10_000, step=500)
    n = len(df)
    n_pages = max(1, (n + rows_pp - 1) // rows_pp)
    page = st.sidebar.number_input("Page", min_value=1, max_value=n_pages, value=1, step=1)
    start = (page - 1) * rows_pp
    end = min(start + rows_pp, n)
    st.caption(f"Showing rows **{start + 1:,}–{end:,}** of **{n:,}** ({n_pages:,} pages)")

    st.dataframe(df.iloc[start:end], use_container_width=True, height=600)


if __name__ == "__main__":
    main()
