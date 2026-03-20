"""
Browse the FULL Snowflake CSV (~1.4M rows) with server-side pagination.

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


def _normalize_path(raw: str) -> str:
    s = (raw or "").strip().strip('"').strip("'")
    return s


@st.cache_data(show_spinner="Loading CSV (one-time cache)…")
def load_csv(path_str: str) -> pd.DataFrame:
    return pd.read_csv(path_str, low_memory=False)


def main() -> None:
    st.set_page_config(page_title="VQTM — full extract", layout="wide")
    st.title("VQTM RAN availability — full extract dashboard")
    st.caption(
        "All rows are loaded once (cached). Use **Previous / Next** or **Go to page** below the charts. "
        "If the default path fails, paste the full path in the sidebar (use the text area so nothing is cut off)."
    )

    if "csv_path_text" not in st.session_state:
        st.session_state.csv_path_text = str(DEFAULT_CSV)
    if "table_page" not in st.session_state:
        st.session_state.table_page = 1

    st.sidebar.markdown("**CSV location**")
    st.sidebar.caption(
        "Use the box below for the **entire** path (OneDrive paths are long). "
        "`text_input` in the sidebar often truncates — this **text area** does not."
    )

    st.sidebar.text_area(
        "Full path to `vqtm_ran_avail_from_20260320.csv`",
        height=100,
        key="csv_path_text",
    )
    path_str = st.session_state.csv_path_text

    if st.sidebar.button("Browse for CSV… (Windows)"):
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            picked = filedialog.askopenfilename(
                title="Select vqtm_ran_avail_from_20260320.csv",
                filetypes=[("CSV", "*.csv"), ("All", "*.*")],
            )
            root.destroy()
            if picked:
                st.session_state.csv_path_text = picked
                st.session_state.table_page = 1
                st.rerun()
        except Exception as e:
            st.sidebar.warning(f"File dialog failed: {e}")

    st.sidebar.caption(
        f"Default export path exists: **{'Yes' if DEFAULT_CSV.is_file() else 'No'}** "
        f"(`{DEFAULT_CSV.name}`)"
    )

    p = Path(_normalize_path(path_str))
    if not p.is_file():
        st.error(f"**File not found:** `{p}`")
        st.info(
            "**Tips:** Copy the path from File Explorer (Shift+right‑click file → Copy as path) and paste into the sidebar text area. "
            f"Expected file name: `vqtm_ran_avail_from_20260320.csv`. Default folder: `{DEFAULT_CSV.parent}`."
        )
        st.stop()

    df = load_csv(str(p.resolve()))

    rows_pp = st.sidebar.slider(
        "Rows per page",
        min_value=500,
        max_value=50_000,
        value=10_000,
        step=500,
        help="How many rows to show in the table at once.",
    )

    n = len(df)
    n_pages = max(1, (n + rows_pp - 1) // rows_pp)
    st.session_state.table_page = int(min(max(1, st.session_state.table_page), n_pages))

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
        st.metric("Table pages", f"{n_pages:,}")

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

    def _prev_page() -> None:
        st.session_state.table_page = max(1, int(st.session_state.table_page) - 1)

    def _next_page() -> None:
        st.session_state.table_page = min(n_pages, int(st.session_state.table_page) + 1)

    nav1, nav2, nav3, nav4 = st.columns([1, 1, 2, 2])
    with nav1:
        st.button(
            "◀ Previous page",
            disabled=st.session_state.table_page <= 1,
            on_click=_prev_page,
            key="btn_prev_page",
        )
    with nav2:
        st.button(
            "Next page ▶",
            disabled=st.session_state.table_page >= n_pages,
            on_click=_next_page,
            key="btn_next_page",
        )
    with nav3:
        st.number_input(
            "Go to page",
            min_value=1,
            max_value=n_pages,
            step=1,
            key="table_page",
            help=f"1 … {n_pages:,}",
        )
    with nav4:
        st.metric("Position", f"{int(st.session_state.table_page):,} / {n_pages:,}")

    pg = int(st.session_state.table_page)
    start = (pg - 1) * rows_pp
    end = min(start + rows_pp, n)
    st.caption(
        f"Showing dataframe rows **{start + 1:,}–{end:,}** of **{n:,}** · **{rows_pp:,}** rows per page"
    )

    st.dataframe(df.iloc[start:end], use_container_width=True, height=600)


if __name__ == "__main__":
    main()
