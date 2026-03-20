# VQTM RAN availability dashboard (Mar 20, 2026+)

Snowflake extract: `VQTM_RAN_AVAILABILITY_SITE_HOURLY` with `PERIOD_START_TIME >= '2026-03-20'`.

## What’s in Git

- **`vqtm_ran_avail_from_20260320.sql`** — source query  
- **`summary.json`** — aggregates over the **full** extract (row counts, downtime sums, region/vendor/market distributions)  
- **`sample.csv`** — random **8,000-row** reservoir sample for charts/table in the HTML dashboard  
- **`index.html`** — standalone dashboard (Chart.js CDN)  
- **`prepare_dashboard_data.py`** — stream the large CSV → `summary.json` + `sample.csv`  
- **`build_dashboard.py`** — regenerate `index.html` from those files  

The full export (~1.4M rows, ~800MB) is **not** committed. Generate it locally with your Snowflake SSO agent, then run `prepare_dashboard_data.py` pointing at that CSV.

## Regenerate locally

```bash
python prepare_dashboard_data.py "path/to/vqtm_ran_avail_from_20260320.csv"
python build_dashboard.py
```

Open **`index.html`** in a browser (or use GitHub blob URL below; interactive charts need the file opened locally or served over HTTPS).

## GitHub

After push, view the folder:  
`https://github.com/jvcjvcjvc-tech/streamlit-dashboards/tree/main/vqtm_ran_dashboard_mar2026`

Raw `index.html` (download / open locally):  
`https://raw.githubusercontent.com/jvcjvcjvc-tech/streamlit-dashboards/main/vqtm_ran_dashboard_mar2026/index.html`

GitHub’s inline preview may not run Chart.js; download the file or clone and open locally for full interactivity.
