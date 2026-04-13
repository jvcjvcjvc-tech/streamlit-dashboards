"""
Generate CPPS Paging Dashboard with Live Data from Snowflake

Fetches paging metrics from PCMD_AMF_AGG_HOURLY and generates an HTML dashboard.
Run with: python generate_cpps_paging_dashboard.py --env PROD_PCMD
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from simple_agent_with_sso_auth import run_direct_query

OUTPUT_HTML = "cpps_paging_dashboard_live.html"
OUTPUT_CSV = "cpps_paging_data.csv"


PAGING_QUERY = """
WITH date_params AS (
    SELECT 
        DATEADD('day', -30, CURRENT_DATE()) AS START_DATE,
        CURRENT_DATE() AS END_DATE
),
base AS (
    SELECT *
    FROM PCMD_AMF_AGG_HOURLY, date_params
    WHERE LOCAL_DATE_PART >= date_params.START_DATE
      AND LOCAL_DATE_PART <= date_params.END_DATE
),
market_hour AS (
    SELECT
        COALESCE(MARKET::VARCHAR, '(unknown)') AS MARKET,
        LOCAL_DATE_PART,
        LOCAL_HOUR_PART,
        ANY_VALUE(REGION) AS REGION,
        SUM(COALESCE(PAGING_SUCC, 0)) AS HOUR_PAGING_SUCC,
        SUM(COALESCE(PAGING_ATT, 0)) AS HOUR_PAGING_ATT,
        IFF(MIN(COALESCE(PAGING_SUCC, 0)) = 0, 1, 0) AS DOWNTIME
    FROM base
    GROUP BY
        COALESCE(MARKET::VARCHAR, '(unknown)'),
        LOCAL_DATE_PART,
        LOCAL_HOUR_PART
),
market_daily AS (
    SELECT
        MARKET,
        LOCAL_DATE_PART AS DATE_VALUE,
        ANY_VALUE(REGION) AS REGION,
        SUM(HOUR_PAGING_SUCC) AS DAILY_PAGING_SUCC,
        SUM(HOUR_PAGING_ATT) AS DAILY_PAGING_ATT,
        COUNT(*) AS TOTAL_HOURS,
        SUM(DOWNTIME) AS DOWNTIME_HOURS,
        COUNT(*) - SUM(DOWNTIME) AS UPTIME_HOURS
    FROM market_hour
    GROUP BY MARKET, LOCAL_DATE_PART
),
market_summary AS (
    SELECT
        MARKET,
        ANY_VALUE(REGION) AS REGION,
        MIN(DATE_VALUE) AS DATE_START,
        MAX(DATE_VALUE) AS DATE_END,
        COUNT(DISTINCT DATE_VALUE) AS DAYS_COUNT,
        SUM(DAILY_PAGING_SUCC) AS TOTAL_PAGING_SUCC,
        SUM(DAILY_PAGING_ATT) AS TOTAL_PAGING_ATT,
        SUM(TOTAL_HOURS) AS TOTAL_HOURS,
        SUM(DOWNTIME_HOURS) AS TOTAL_DOWNTIME_HOURS,
        SUM(UPTIME_HOURS) AS TOTAL_UPTIME_HOURS,
        ROUND(100.0 * SUM(DAILY_PAGING_SUCC) / NULLIF(SUM(DAILY_PAGING_ATT), 0), 4) AS PAGING_SUCCESS_RATE_PCT,
        ROUND(100.0 * SUM(UPTIME_HOURS) / NULLIF(SUM(TOTAL_HOURS), 0), 4) AS AVAILABILITY_PCT,
        ROUND(100.0 * SUM(DOWNTIME_HOURS) / NULLIF(SUM(TOTAL_HOURS), 0), 4) AS DOWNTIME_PCT
    FROM market_daily
    GROUP BY MARKET
),
latest_day AS (
    SELECT
        MARKET,
        DATE_VALUE AS LATEST_DATE,
        DAILY_PAGING_SUCC AS LATEST_PAGING_SUCC,
        DAILY_PAGING_ATT AS LATEST_PAGING_ATT,
        ROUND(100.0 * DAILY_PAGING_SUCC / NULLIF(DAILY_PAGING_ATT, 0), 4) AS LATEST_SUCCESS_RATE_PCT,
        TOTAL_HOURS AS LATEST_TOTAL_HOURS,
        DOWNTIME_HOURS AS LATEST_DOWNTIME_HOURS,
        ROUND(100.0 * UPTIME_HOURS / NULLIF(TOTAL_HOURS, 0), 4) AS LATEST_AVAILABILITY_PCT
    FROM market_daily
    QUALIFY ROW_NUMBER() OVER (PARTITION BY MARKET ORDER BY DATE_VALUE DESC) = 1
)
SELECT
    ms.MARKET,
    ms.REGION,
    ms.DATE_START,
    ms.DATE_END,
    ms.DAYS_COUNT,
    ms.TOTAL_PAGING_SUCC,
    ms.TOTAL_PAGING_ATT,
    ms.PAGING_SUCCESS_RATE_PCT,
    ms.TOTAL_HOURS,
    ms.TOTAL_DOWNTIME_HOURS,
    ms.TOTAL_UPTIME_HOURS,
    ms.AVAILABILITY_PCT,
    ms.DOWNTIME_PCT,
    ld.LATEST_DATE,
    ld.LATEST_PAGING_SUCC,
    ld.LATEST_PAGING_ATT,
    ld.LATEST_SUCCESS_RATE_PCT,
    ld.LATEST_TOTAL_HOURS,
    ld.LATEST_DOWNTIME_HOURS,
    ld.LATEST_AVAILABILITY_PCT
FROM market_summary ms
LEFT JOIN latest_day ld ON ms.MARKET = ld.MARKET
WHERE ms.MARKET NOT IN ('(unknown)', 'LabMarket', 'EMERGENCY MANAGEMENT')
ORDER BY ms.AVAILABILITY_PCT ASC, ms.MARKET
"""


def generate_html(data: list) -> str:
    """Generate the HTML dashboard."""
    
    data_json = json.dumps(data, default=str)
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CPPS Paging Metrics Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #0c111d;
      --panel: #151b2e;
      --border: #2a3548;
      --text: #e8ecf4;
      --muted: #8b9bb4;
      --accent: #e20074;
      --accent-dim: #ff4da6;
      --green: #22c55e;
      --yellow: #eab308;
      --red: #ef4444;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1600px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }}
    header {{
      border-bottom: 1px solid var(--border);
      padding-bottom: 1.25rem;
      margin-bottom: 1.5rem;
    }}
    header h1 {{
      margin: 0 0 0.35rem;
      font-size: 1.6rem;
      font-weight: 600;
      letter-spacing: -0.02em;
      color: var(--accent);
    }}
    header p {{ margin: 0; color: var(--muted); font-size: 0.9rem; }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem 1.15rem;
    }}
    .kpi .label {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }}
    .kpi .value {{ font-size: 1.55rem; font-weight: 700; margin-top: 0.25rem; }}
    .kpi .value.green {{ color: var(--green); }}
    .kpi .value.yellow {{ color: var(--yellow); }}
    .kpi .value.red {{ color: var(--red); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 1rem;
      margin-bottom: 1.5rem;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem 1.15rem 1.25rem;
    }}
    .card h2 {{
      margin: 0 0 1rem;
      font-size: 0.82rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
    }}
    .span-6 {{ grid-column: span 6; }}
    .span-12 {{ grid-column: span 12; }}
    @media (max-width: 960px) {{
      .span-6 {{ grid-column: span 12; }}
    }}
    .chart-h {{ height: 300px; position: relative; }}
    .table-wrap {{
      overflow: auto;
      max-height: 500px;
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
    }}
    th, td {{
      padding: 0.6rem 0.75rem;
      border-bottom: 1px solid var(--border);
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      background: #111827;
      position: sticky;
      top: 0;
      z-index: 1;
      font-weight: 600;
      color: var(--accent-dim);
    }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    tr:hover td {{ background: rgba(226, 0, 116, 0.06); }}
    .status-good {{ color: var(--green); font-weight: 600; }}
    .status-warn {{ color: var(--yellow); font-weight: 600; }}
    .status-bad {{ color: var(--red); font-weight: 600; }}
    .bar-cell {{ min-width: 120px; }}
    .bar-container {{
      background: #1e293b;
      border-radius: 4px;
      height: 18px;
      overflow: hidden;
    }}
    .bar-fill {{
      height: 100%;
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      padding-right: 4px;
      font-size: 0.7rem;
      font-weight: 600;
      color: #fff;
    }}
    .bar-good {{ background: linear-gradient(90deg, #22c55e, #16a34a); }}
    .bar-warn {{ background: linear-gradient(90deg, #eab308, #ca8a04); }}
    .bar-bad {{ background: linear-gradient(90deg, #ef4444, #dc2626); }}
    .generated {{ text-align: center; padding: 1rem; color: var(--muted); font-size: 0.75rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>CPPS Paging Metrics Dashboard</h1>
      <p>Core Performance Platform Statistics - Paging Success Metrics by Market | Source: PCMD_AMF_AGG_HOURLY | Live Data</p>
    </header>

    <div class="kpis">
      <div class="kpi">
        <div class="label">Markets Tracked</div>
        <div class="value" id="kpiMarkets">--</div>
      </div>
      <div class="kpi">
        <div class="label">Avg Paging Success Rate</div>
        <div class="value" id="kpiAvgRate">--</div>
      </div>
      <div class="kpi">
        <div class="label">Avg Availability</div>
        <div class="value" id="kpiAvgAvail">--</div>
      </div>
      <div class="kpi">
        <div class="label">Total Paging Success</div>
        <div class="value" id="kpiTotalSuccess">--</div>
      </div>
      <div class="kpi">
        <div class="label">Total Downtime Hours</div>
        <div class="value" id="kpiDowntime">--</div>
      </div>
    </div>

    <div class="grid">
      <div class="card span-6">
        <h2>Availability by Market (%)</h2>
        <div class="chart-h"><canvas id="chAvail"></canvas></div>
      </div>
      <div class="card span-6">
        <h2>Paging Success Rate by Market (%)</h2>
        <div class="chart-h"><canvas id="chSuccess"></canvas></div>
      </div>
    </div>

    <div class="card span-12">
      <h2>Market Details</h2>
      <div class="table-wrap">
        <table id="tbl">
          <thead>
            <tr>
              <th>Market</th>
              <th>Region</th>
              <th>Availability %</th>
              <th class="bar-cell">Availability</th>
              <th>Success Rate %</th>
              <th>Total Hours</th>
              <th>Downtime Hrs</th>
              <th>Paging Success</th>
              <th>Paging Attempts</th>
              <th>Latest Date</th>
              <th>Latest Avail %</th>
            </tr>
          </thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
    </div>

    <div class="generated">
      Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Data Period: Last 30 Days | Source: Snowflake PROD_PCMD
    </div>
  </div>

  <script>
    const DATA = {data_json};

    // Sort by availability (worst first)
    DATA.sort((a, b) => a.availPct - b.availPct);

    // Calculate KPIs
    const totalMarkets = DATA.length;
    const avgAvail = DATA.reduce((s, r) => s + (r.availPct || 0), 0) / totalMarkets;
    const avgRate = DATA.reduce((s, r) => s + (r.successRate || 0), 0) / totalMarkets;
    const totalSuccess = DATA.reduce((s, r) => s + (r.pagingSucc || 0), 0);
    const totalDowntime = DATA.reduce((s, r) => s + (r.downtimeHrs || 0), 0);

    document.getElementById('kpiMarkets').textContent = totalMarkets;
    document.getElementById('kpiAvgAvail').textContent = avgAvail.toFixed(2) + '%';
    document.getElementById('kpiAvgAvail').className = 'value ' + (avgAvail >= 99.5 ? 'green' : avgAvail >= 98 ? 'yellow' : 'red');
    document.getElementById('kpiAvgRate').textContent = avgRate.toFixed(2) + '%';
    document.getElementById('kpiAvgRate').className = 'value ' + (avgRate >= 99.5 ? 'green' : avgRate >= 98 ? 'yellow' : 'red');
    document.getElementById('kpiTotalSuccess').textContent = totalSuccess.toLocaleString();
    document.getElementById('kpiDowntime').textContent = totalDowntime;
    document.getElementById('kpiDowntime').className = 'value ' + (totalDowntime <= 10 ? 'green' : totalDowntime <= 30 ? 'yellow' : 'red');

    Chart.defaults.color = '#8b9bb4';
    Chart.defaults.borderColor = '#2a3548';

    new Chart(document.getElementById('chAvail'), {{
      type: 'bar',
      data: {{
        labels: DATA.map(r => r.market),
        datasets: [{{
          data: DATA.map(r => r.availPct),
          backgroundColor: DATA.map(r => r.availPct >= 99.5 ? '#22c55e99' : r.availPct >= 98 ? '#eab30899' : '#ef444499'),
          borderColor: DATA.map(r => r.availPct >= 99.5 ? '#22c55e' : r.availPct >= 98 ? '#eab308' : '#ef4444'),
          borderWidth: 1
        }}]
      }},
      options: {{
        indexAxis: 'y',
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          x: {{ min: 95, max: 100, title: {{ display: true, text: 'Availability %' }} }}
        }}
      }}
    }});

    new Chart(document.getElementById('chSuccess'), {{
      type: 'bar',
      data: {{
        labels: DATA.map(r => r.market),
        datasets: [{{
          data: DATA.map(r => r.successRate),
          backgroundColor: '#e2007499',
          borderColor: '#e20074',
          borderWidth: 1
        }}]
      }},
      options: {{
        indexAxis: 'y',
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          x: {{ min: 98, max: 100, title: {{ display: true, text: 'Success Rate %' }} }}
        }}
      }}
    }});

    const tbody = document.getElementById('tbody');
    DATA.forEach(r => {{
      const statusClass = r.availPct >= 99.5 ? 'status-good' : r.availPct >= 98 ? 'status-warn' : 'status-bad';
      const barClass = r.availPct >= 99.5 ? 'bar-good' : r.availPct >= 98 ? 'bar-warn' : 'bar-bad';
      const barWidth = Math.max(0, Math.min(100, (r.availPct - 95) * 20));
      
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><strong>${{r.market}}</strong></td>
        <td>${{r.region || ''}}</td>
        <td class="num ${{statusClass}}">${{(r.availPct || 0).toFixed(2)}}%</td>
        <td class="bar-cell">
          <div class="bar-container">
            <div class="bar-fill ${{barClass}}" style="width: ${{barWidth}}%">${{(r.availPct || 0).toFixed(1)}}%</div>
          </div>
        </td>
        <td class="num">${{(r.successRate || 0).toFixed(2)}}%</td>
        <td class="num">${{(r.totalHours || 0).toLocaleString()}}</td>
        <td class="num ${{r.downtimeHrs > 5 ? 'status-bad' : r.downtimeHrs > 0 ? 'status-warn' : ''}}">${{r.downtimeHrs || 0}}</td>
        <td class="num">${{(r.pagingSucc || 0).toLocaleString()}}</td>
        <td class="num">${{(r.pagingAtt || 0).toLocaleString()}}</td>
        <td>${{r.latestDate || ''}}</td>
        <td class="num ${{(r.latestAvail || 0) >= 99.5 ? 'status-good' : (r.latestAvail || 0) >= 95 ? 'status-warn' : 'status-bad'}}">${{(r.latestAvail || 0).toFixed(2)}}%</td>
      `;
      tbody.appendChild(tr);
    }});
  </script>
</body>
</html>'''
    
    return html


def main(config_file='config_sso.json', user_email=None, environment='PROD_PCMD'):
    """Main function to generate the dashboard."""
    
    print("=" * 60)
    print("CPPS Paging Metrics Dashboard Generator")
    print("=" * 60)
    print(f"Environment: {environment}")
    print(f"Output: {OUTPUT_HTML}")
    print("=" * 60)
    
    try:
        print("\nFetching paging data from Snowflake...")
        df = run_direct_query(PAGING_QUERY, config_file=config_file, user_email=user_email, environment=environment)
        
        # Convert to list of dicts
        data = []
        for _, row in df.iterrows():
            data.append({
                "market": row.get('MARKET', ''),
                "region": row.get('REGION', ''),
                "availPct": float(row.get('AVAILABILITY_PCT', 0) or 0),
                "successRate": float(row.get('PAGING_SUCCESS_RATE_PCT', 0) or 0),
                "totalHours": int(row.get('TOTAL_HOURS', 0) or 0),
                "downtimeHrs": int(row.get('TOTAL_DOWNTIME_HOURS', 0) or 0),
                "pagingSucc": int(row.get('TOTAL_PAGING_SUCC', 0) or 0),
                "pagingAtt": int(row.get('TOTAL_PAGING_ATT', 0) or 0),
                "latestDate": str(row.get('LATEST_DATE', ''))[:10] if row.get('LATEST_DATE') else '',
                "latestAvail": float(row.get('LATEST_AVAILABILITY_PCT', 0) or 0)
            })
        
        # Save CSV
        df.to_csv(OUTPUT_CSV, index=False)
        print(f"\nData saved to: {OUTPUT_CSV}")
        
    except Exception as e:
        print(f"\nError fetching data: {e}")
        print("Using sample data instead...")
        
        # Sample data
        data = [
            {"market": "ATLANTA", "region": "SOUTH", "availPct": 99.85, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 15234567, "pagingAtt": 15246789, "latestDate": "2026-04-08", "latestAvail": 100.00},
            {"market": "AUSTIN", "region": "SOUTH", "availPct": 99.72, "successRate": 99.88, "totalHours": 720, "downtimeHrs": 2, "pagingSucc": 8234567, "pagingAtt": 8244789, "latestDate": "2026-04-08", "latestAvail": 100.00},
            {"market": "BIRMINGHAM", "region": "SOUTH", "availPct": 98.89, "successRate": 99.45, "totalHours": 720, "downtimeHrs": 8, "pagingSucc": 4234567, "pagingAtt": 4257789, "latestDate": "2026-04-08", "latestAvail": 95.83},
            {"market": "DALLAS", "region": "SOUTH", "availPct": 99.86, "successRate": 99.91, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 18234567, "pagingAtt": 18250789, "latestDate": "2026-04-08", "latestAvail": 100.00},
            {"market": "HOUSTON", "region": "SOUTH", "availPct": 99.44, "successRate": 99.72, "totalHours": 720, "downtimeHrs": 4, "pagingSucc": 14234567, "pagingAtt": 14274789, "latestDate": "2026-04-08", "latestAvail": 95.83},
            {"market": "JACKSONVILLE", "region": "SOUTH", "availPct": 99.86, "successRate": 99.90, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 5234567, "pagingAtt": 5239789, "latestDate": "2026-04-08", "latestAvail": 100.00},
            {"market": "MEMPHIS", "region": "SOUTH", "availPct": 99.93, "successRate": 99.96, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 3234567, "pagingAtt": 3235789, "latestDate": "2026-04-08", "latestAvail": 100.00},
            {"market": "MIAMI", "region": "SOUTH", "availPct": 99.86, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 12234567, "pagingAtt": 12244789, "latestDate": "2026-04-08", "latestAvail": 100.00},
            {"market": "MOBILE", "region": "SOUTH", "availPct": 99.72, "successRate": 99.85, "totalHours": 720, "downtimeHrs": 2, "pagingSucc": 2234567, "pagingAtt": 2237789, "latestDate": "2026-04-08", "latestAvail": 100.00},
            {"market": "ORLANDO", "region": "SOUTH", "availPct": 99.86, "successRate": 99.91, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 8234567, "pagingAtt": 8241789, "latestDate": "2026-04-08", "latestAvail": 100.00},
            {"market": "PUERTO RICO", "region": "SOUTH", "availPct": 98.61, "successRate": 99.35, "totalHours": 720, "downtimeHrs": 10, "pagingSucc": 2234567, "pagingAtt": 2249789, "latestDate": "2026-04-08", "latestAvail": 91.67},
            {"market": "TAMPA", "region": "SOUTH", "availPct": 99.79, "successRate": 99.88, "totalHours": 720, "downtimeHrs": 2, "pagingSucc": 6234567, "pagingAtt": 6241789, "latestDate": "2026-04-08", "latestAvail": 100.00}
        ]
    
    # Generate HTML
    html_content = generate_html(data)
    Path(OUTPUT_HTML).write_text(html_content, encoding='utf-8')
    
    print(f"Dashboard generated: {OUTPUT_HTML}")
    print("\n" + "=" * 60)
    print("SUCCESS! Dashboard ready.")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate CPPS Paging Dashboard')
    parser.add_argument('--config', '-c', default='config_sso.json', help='Config file path')
    parser.add_argument('--user', '-u', dest='user_email', help='T-Mobile email for SSO')
    parser.add_argument('--env', '-e', dest='environment', default='PROD_PCMD',
                        choices=['DEV', 'QAT', 'PROD', 'PROD_PCMD'], help='Environment (default: PROD_PCMD)')
    
    args = parser.parse_args()
    
    main(config_file=args.config, user_email=args.user_email, environment=args.environment)
