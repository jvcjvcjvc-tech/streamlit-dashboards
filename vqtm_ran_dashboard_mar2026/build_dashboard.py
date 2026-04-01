"""Emit index.html from summary.json + sample rows (embedded)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>VQTM RAN availability — Mar 20+ 2026 (summary)</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root { --bg: #0c111d; --panel: #151b2e; --border: #2a3548; --text: #e8ecf4; --muted: #8b9bb4; --accent: #e20074; --accent-dim: #ff4da6; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; min-height: 100vh; }
    .wrap { max-width: 1280px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }
    header { border-bottom: 1px solid var(--border); padding-bottom: 1.25rem; margin-bottom: 1.5rem; }
    header h1 { margin: 0 0 0.35rem; font-size: 1.45rem; font-weight: 600; }
    header p { margin: 0; color: var(--muted); font-size: 0.88rem; }
    .banner { background: rgba(226, 0, 116, 0.12); border: 1px solid var(--border); border-radius: 10px; padding: 0.85rem 1rem; margin-bottom: 1.25rem; font-size: 0.85rem; }
    .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
    .kpi { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 1rem; }
    .kpi .label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
    .kpi .value { font-size: 1.45rem; font-weight: 700; margin-top: 0.2rem; }
    .kpi .sub { font-size: 0.78rem; color: var(--muted); margin-top: 0.15rem; }
    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 1rem; margin-bottom: 1.5rem; }
    .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 1rem 1.1rem 1.2rem; }
    .card h2 { margin: 0 0 0.85rem; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
    .span-4 { grid-column: span 4; }
    .span-6 { grid-column: span 6; }
    .span-12 { grid-column: span 12; }
    @media (max-width: 900px) { .span-4, .span-6 { grid-column: span 12; } }
    .chart-h { height: 280px; position: relative; }
    .table-tools { margin-bottom: 0.6rem; }
    .table-tools input { width: 100%; max-width: 420px; padding: 0.45rem 0.65rem; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: var(--text); }
    .table-wrap { overflow: auto; max-height: 380px; border: 1px solid var(--border); border-radius: 8px; }
    table { border-collapse: collapse; width: 100%; font-size: 0.75rem; }
    th, td { padding: 0.4rem 0.5rem; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
    th { position: sticky; top: 0; background: #1e2640; z-index: 1; font-weight: 600; color: var(--muted); }
    tr:hover td { background: rgba(226, 0, 116, 0.06); }
    .pill { display: inline-block; padding: 0.12rem 0.4rem; border-radius: 999px; font-size: 0.7rem; font-weight: 600; background: rgba(226, 0, 116, 0.15); color: var(--accent-dim); }
    code { font-size: 0.82em; color: #c4d0e8; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>VQTM RAN availability <span class="pill">PERIOD_START_TIME ≥ 2026-03-20</span></h1>
      <p>Full extract: <strong id="fullRows"></strong> rows · Unique sites: <strong id="uniqSites"></strong> ·
      Period range: <code id="pmin"></code> → <code id="pmax"></code></p>
    </header>
    <div class="banner" id="banner"></div>
    <div class="kpis" id="kpis"></div>
    <div class="grid">
      <div class="card span-4"><h2>Region (full data)</h2><div class="chart-h"><canvas id="cRegion"></canvas></div></div>
      <div class="card span-4"><h2>Vendor (full data)</h2><div class="chart-h"><canvas id="cVendor"></canvas></div></div>
      <div class="card span-4"><h2>Top markets (full data)</h2><div class="chart-h"><canvas id="cMarket"></canvas></div></div>
      <div class="card span-6"><h2>Sample: LTE vs 5G downtime (sec)</h2><div class="chart-h"><canvas id="cDown"></canvas></div></div>
      <div class="card span-6"><h2>Sample: availability % (where RAT has time)</h2><div class="chart-h"><canvas id="cAvail"></canvas></div></div>
      <div class="card span-12">
        <h2>Sample rows (filter)</h2>
        <div class="table-tools"><input type="search" id="filter" placeholder="Filter sample…" /></div>
        <div class="table-wrap"><table><thead><tr id="thead"></tr></thead><tbody id="tbody"></tbody></table></div>
      </div>
    </div>
  </div>
  <script>
    const SUMMARY = __SUMMARY__;
    const SAMPLE = __SAMPLE__;
    const COLS = ["SITE_ID","PERIOD_START_TIME","REGION_ID","MARKET_ID","VENDOR","CELL_COUNT",
      "TOTAL_DOWNTIME_LTE","TOTAL_DOWNTIME_5G","OUTAGE_TYPE","TOP_RECORDID"];

    document.getElementById("fullRows").textContent = SUMMARY.total_rows.toLocaleString();
    document.getElementById("uniqSites").textContent = SUMMARY.unique_sites.toLocaleString();
    document.getElementById("pmin").textContent = SUMMARY.period_start_min || "—";
    document.getElementById("pmax").textContent = SUMMARY.period_start_max || "—";
    document.getElementById("banner").textContent = SUMMARY.sample_note || "";

    function pct(a, b) { return b ? ((100 * a) / b).toFixed(1) + "%" : "—"; }
    document.getElementById("kpis").innerHTML =
      '<div class="kpi"><div class="label">Rows w/ LTE downtime &gt; 0</div><div class="value">' + SUMMARY.rows_lte_downtime_gt0.toLocaleString() + '</div>' +
        '<div class="sub">' + pct(SUMMARY.rows_lte_downtime_gt0, SUMMARY.total_rows) + ' of total</div></div>' +
      '<div class="kpi"><div class="label">Rows w/ 5G downtime &gt; 0</div><div class="value">' + SUMMARY.rows_5g_downtime_gt0.toLocaleString() + '</div>' +
        '<div class="sub">' + pct(SUMMARY.rows_5g_downtime_gt0, SUMMARY.total_rows) + ' of total</div></div>' +
      '<div class="kpi"><div class="label">Σ LTE downtime (sec)</div><div class="value">' + SUMMARY.sum_total_downtime_lte.toLocaleString() + '</div></div>' +
      '<div class="kpi"><div class="label">Σ 5G downtime (sec)</div><div class="value">' + SUMMARY.sum_total_downtime_5g.toLocaleString() + '</div></div>';

    Chart.defaults.color = "#8b9bb4";
    Chart.defaults.borderColor = "#2a3548";

    const reg = SUMMARY.by_region || {};
    new Chart(document.getElementById("cRegion"), {
      type: "bar",
      data: { labels: Object.keys(reg), datasets: [{ data: Object.values(reg), backgroundColor: "rgba(226, 0, 116, 0.7)" }] },
      options: {
        indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true }, y: { grid: { display: false } } },
      },
    });

    const ven = SUMMARY.by_vendor || {};
    new Chart(document.getElementById("cVendor"), {
      type: "doughnut",
      data: {
        labels: Object.keys(ven),
        datasets: [{ data: Object.values(ven), backgroundColor: ["#e20074","#6366f1","#22c55e","#f59e0b","#38bdf8","#a78bfa"] }],
      },
      options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } },
    });

    const mk = SUMMARY.top_markets || {};
    new Chart(document.getElementById("cMarket"), {
      type: "bar",
      data: { labels: Object.keys(mk), datasets: [{ data: Object.values(mk), backgroundColor: "rgba(56, 189, 248, 0.65)" }] },
      options: {
        indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true }, y: { grid: { display: false } } },
      },
    });

    new Chart(document.getElementById("cDown"), {
      type: "bar",
      data: {
        labels: SAMPLE.map(r => r.SITE_ID),
        datasets: [
          { label: "LTE", data: SAMPLE.map(r => parseFloat(r.TOTAL_DOWNTIME_LTE) || 0), backgroundColor: "rgba(99, 102, 241, 0.75)" },
          { label: "5G", data: SAMPLE.map(r => parseFloat(r.TOTAL_DOWNTIME_5G) || 0), backgroundColor: "rgba(34, 197, 94, 0.75)" },
        ],
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, ticks: { maxRotation: 90, minRotation: 45, font: { size: 7 } } },
          y: { stacked: true, beginAtZero: true },
        },
      },
    });

    const ltePct = SAMPLE.map(r => r._lte_pct);
    const g5Pct = SAMPLE.map(r => r._5g_pct);
    new Chart(document.getElementById("cAvail"), {
      type: "bar",
      data: {
        labels: SAMPLE.map(r => r.SITE_ID),
        datasets: [
          { label: "LTE %", data: ltePct.map(v => v == null || v === "" ? 0 : +v),
            backgroundColor: SAMPLE.map((_, i) => (ltePct[i] == null || ltePct[i] === "") ? "transparent" : "rgba(99, 102, 241, 0.75)") },
          { label: "5G %", data: g5Pct.map(v => v == null || v === "" ? 0 : +v),
            backgroundColor: SAMPLE.map((_, i) => (g5Pct[i] == null || g5Pct[i] === "") ? "transparent" : "rgba(34, 197, 94, 0.75)") },
        ],
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          y: { max: 100, beginAtZero: true },
          x: { ticks: { maxRotation: 90, minRotation: 45, font: { size: 7 } } },
        },
      },
    });

    const thead = document.getElementById("thead");
    thead.innerHTML = COLS.map(c => "<th>" + c + "</th>").join("");
    const tbody = document.getElementById("tbody");
    function esc(s) { return String(s ?? "").replace(/</g, "&lt;"); }
    function rowHtml(r) { return "<tr>" + COLS.map(c => "<td>" + esc(r[c]) + "</td>").join("") + "</tr>"; }
    function render(q) {
      const qq = (q || "").toLowerCase();
      const rows = !qq ? SAMPLE : SAMPLE.filter(r => COLS.some(c => String(r[c] ?? "").toLowerCase().includes(qq)));
      tbody.innerHTML = rows.slice(0, 2000).map(rowHtml).join("");
    }
    render("");
    document.getElementById("filter").addEventListener("input", e => render(e.target.value));
  </script>
</body>
</html>
"""


def main() -> None:
    summary = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
    with (HERE / "sample.csv").open(encoding="utf-8", newline="") as f:
        sample = list(csv.DictReader(f))

    sum_json = json.dumps(summary, ensure_ascii=False).replace("</script>", "<\\/script>")
    samp_json = json.dumps(sample, ensure_ascii=False).replace("</script>", "<\\/script>")

    html = TEMPLATE.replace("__SUMMARY__", sum_json).replace("__SAMPLE__", samp_json)
    (HERE / "index.html").write_text(html, encoding="utf-8")
    print(f"Wrote {HERE / 'index.html'}")


if __name__ == "__main__":
    main()
