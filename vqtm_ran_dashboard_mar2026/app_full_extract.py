"""
Browse the FULL Snowflake CSV (~1.4M rows) with server-side pagination.

  streamlit run app_full_extract.py

Requires enough RAM to hold the dataframe (~2–4 GB typical for this extract).
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

CSV_NAME = "vqtm_ran_avail_from_20260320.csv"

# Typical export location (note: folder name includes " 5" and a nested folder with the same base name)
_WIN_DEFAULT = Path(
    r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR"
    r"\query_execution_agent_sso_auth 5\query_execution_agent_sso_auth"
) / CSV_NAME

# Same path via WSL when C: is mounted at /mnt/c
_WSL_DEFAULT = Path(
    "/mnt/c/Users/JChalap1/OneDrive - T-Mobile USA/Documents/AI_CURSOR"
    "/query_execution_agent_sso_auth 5/query_execution_agent_sso_auth"
) / CSV_NAME


def _path_candidates() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("VQTM_CSV_PATH", "").strip()
    if env:
        out.append(Path(env))
    out.append(_WIN_DEFAULT)
    out.append(_WSL_DEFAULT)
    # Common mistake: missing " 5" segment and inner folder
    out.append(
        Path(
            r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR"
            r"\query_execution_agent_sso_auth"
        )
        / CSV_NAME
    )
    return out


def _first_existing_path() -> Path | None:
    for c in _path_candidates():
        if c.is_file():
            return c
    return None


def _normalize_path(raw: str) -> str:
    return (raw or "").strip().strip('"').strip("'")


@st.cache_data(show_spinner="Loading CSV from disk (one-time cache)…")
def load_csv_path(path_str: str) -> pd.DataFrame:
    return pd.read_csv(path_str, low_memory=False)


def load_csv_upload(uploaded) -> pd.DataFrame:
    """Not cached — avoids hashing hundreds of MB for @st.cache_data."""
    raw = uploaded.getvalue() if hasattr(uploaded, "getvalue") else uploaded
    return pd.read_csv(io.BytesIO(raw), low_memory=False)


def main() -> None:
    st.set_page_config(page_title="VQTM — full extract", layout="wide")
    st.title("VQTM RAN availability — full extract dashboard")
    st.caption(
        "All rows are loaded once (cached when loading from disk). Use **Previous / Next** or **Go to page** below the charts."
    )

    if "csv_path_text" not in st.session_state:
        hit = _first_existing_path()
        st.session_state.csv_path_text = str(hit) if hit else str(_WIN_DEFAULT)
    if "table_page" not in st.session_state:
        st.session_state.table_page = 1

    st.sidebar.markdown("**CSV location**")

    uploaded = st.sidebar.file_uploader(
        f"Upload `{CSV_NAME}` (Linux / WSL / cloud / no GUI)",
        type=["csv"],
        help="Use this if the app runs on Linux (tkinter Browse is unavailable) or the file is not on the server disk. "
        "Very large files need RAM and may require .streamlit/config.toml maxUploadSize (see repo).",
    )

    st.sidebar.text_area(
        f"Or: full path to `{CSV_NAME}`",
        height=96,
        key="csv_path_text",
    )
    path_str = _normalize_path(st.session_state.csv_path_text)

    if sys.platform == "win32":
        if st.sidebar.button("Browse for CSV… (Windows desktop only)"):
            try:
                import tkinter as tk
                from tkinter import filedialog

                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                picked = filedialog.askopenfilename(
                    title=f"Select {CSV_NAME}",
                    filetypes=[("CSV", "*.csv"), ("All", "*.*")],
                )
                root.destroy()
                if picked:
                    st.session_state.csv_path_text = picked
                    st.session_state.table_page = 1
                    st.rerun()
            except Exception as e:
                st.sidebar.warning(
                    f"File dialog failed ({e}). Use **upload** above or paste a path."
                )
    else:
        st.sidebar.caption(
            "**Browse** is hidden: this session is not Windows (`tkinter` file dialogs need a desktop). "
            "Use **Upload** or paste a path (e.g. under `/mnt/c/...` in WSL)."
        )

    hit = _first_existing_path()
    st.sidebar.caption(
        "Auto-detected file on disk: **"
        + ("Yes — `" + str(hit) + "`" if hit else "No")
        + "** · Env `VQTM_CSV_PATH` overrides the search list."
    )

    df: pd.DataFrame | None = None
    load_label = ""

    if uploaded is not None:
        with st.spinner("Reading uploaded CSV (not cached; may take a minute for large files)…"):
            df = load_csv_upload(uploaded)
        load_label = f"upload:{uploaded.name}"
    else:
        p = Path(path_str)
        if not p.is_file():
            st.error(f"**File not found:** `{p}`")
            st.info(
                "**Common mistake:** the export lives in **two** nested folders — include both "
                "`query_execution_agent_sso_auth 5` **and** `query_execution_agent_sso_auth`, e.g.\n\n"
                f"`…\\AI_CURSOR\\query_execution_agent_sso_auth 5\\query_execution_agent_sso_auth\\{CSV_NAME}`\n\n"
                "**WSL:** try\n\n"
                f"`/mnt/c/Users/JChalap1/OneDrive - T-Mobile USA/Documents/AI_CURSOR/"
                f"query_execution_agent_sso_auth 5/query_execution_agent_sso_auth/{CSV_NAME}`\n\n"
                "Or use **Upload** in the sidebar if the CSV is only on your PC."
            )
            st.stop()
        df = load_csv_path(str(p.resolve()))
        load_label = str(p.resolve())

    assert df is not None
    st.sidebar.caption(f"Loaded: `{load_label}`")

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
