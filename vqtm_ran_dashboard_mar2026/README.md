# VQTM RAN availability dashboard (Mar 20, 2026+)

Snowflake extract: `VQTM_RAN_AVAILABILITY_SITE_HOURLY` with `PERIOD_START_TIME >= '2026-03-20'`.

## What’s in Git

- **`vqtm_ran_avail_from_20260320.sql`** — source query  
- **`summary.json`** — aggregates over the **full** extract (row counts, downtime sums, region/vendor/market distributions)  
- **`sample.csv`** — random **8,000-row** reservoir sample for charts/table in the HTML dashboard  
- **`index.html`** — standalone dashboard (Chart.js CDN)  
- **`prepare_dashboard_data.py`** — stream the large CSV → `summary.json` + `sample.csv`  
- **`build_dashboard.py`** — regenerate `index.html` from those files  
- **`app_full_extract.py`** — **Streamlit** app to load **all ~1.4M rows** locally (see below)  

The full export (~1.4M rows, ~800MB) is **not** committed. Generate it locally with your Snowflake SSO agent, then run `prepare_dashboard_data.py` pointing at that CSV.

### Can `index.html` include all 1,388,791 rows?

**No — not in a practical way.** A static page would be hundreds of MB, exceed GitHub limits, and browsers would run out of memory or freeze. The HTML dashboard intentionally uses **full-data aggregates** in `summary.json` plus an **8k sample** for dense charts.

To work with **every row**, use the Streamlit app (loads the CSV once, cached from disk; paginated table over the full dataframe):

```bash
cd vqtm_ran_dashboard_mar2026   # important: picks up .streamlit/config.toml for large uploads
pip install streamlit pandas plotly   # if needed
streamlit run app_full_extract.py
```

**Windows:** paste the full path or use **Browse** (desktop only). The export path includes **both** folders: `query_execution_agent_sso_auth 5\query_execution_agent_sso_auth\` — if you omit the ` 5` segment, the file will not be found.

**Linux / WSL / Streamlit Cloud:** **Browse** is hidden (no `tkinter` GUI). Use **Upload** in the sidebar, or a path like `/mnt/c/Users/.../query_execution_agent_sso_auth 5/query_execution_agent_sso_auth/...`. Set **`VQTM_CSV_PATH`** to force a default file path.

You need **several GB free RAM** for pandas to hold this extract comfortably. Large uploads use `.streamlit/config.toml` (`maxUploadSize = 1200` MB).

Pagination: **Previous page** / **Next page** and **Go to page** (same row above the table). Change **Rows per page** in the sidebar to adjust page count.

## Regenerate locally

```bash
python prepare_dashboard_data.py "path/to/vqtm_ran_avail_from_20260320.csv"
python build_dashboard.py
```

Open **`index.html`** in a browser (double‑click **`OPEN_STATIC_DASHBOARD.bat`** in this folder, or drag `index.html` into the browser).

### “ERR_EMPTY_RESPONSE” / “vqtm_ran_dashboard_mar2026 didn’t send any data”

That happens if you type something like **`http://vqtm_ran_dashboard_mar2026/`** in the address bar. **That name is only a folder**, not a server — nothing is listening, so the browser gets an empty response.

| What you want | What to do |
|---------------|------------|
| Static **`index.html`** dashboard | Use **`file://`** (batch file above) or open the file from File Explorer. |
| Full 1.4M-row **Streamlit** app | In a terminal: `streamlit run app_full_extract.py` → open **`http://localhost:8501`** (not the folder name). |
| GitHub | The [folder](https://github.com/jvcjvcjvc-tech/streamlit-dashboards/tree/main/vqtm_ran_dashboard_mar2026) is for code/files; raw HTML in the browser often won’t run Chart.js well — download `index.html` and open locally. |

Interactive charts need the file opened locally or served over HTTP (`python -m http.server` in this folder, then visit `http://127.0.0.1:8000/index.html`).

## GitHub

After push, view the folder:  
`https://github.com/jvcjvcjvc-tech/streamlit-dashboards/tree/main/vqtm_ran_dashboard_mar2026`

Raw `index.html` (download / open locally):  
`https://raw.githubusercontent.com/jvcjvcjvc-tech/streamlit-dashboards/main/vqtm_ran_dashboard_mar2026/index.html`

GitHub’s inline preview may not run Chart.js; download the file or clone and open locally for full interactivity.
