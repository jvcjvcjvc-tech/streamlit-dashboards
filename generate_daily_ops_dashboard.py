"""
Generate Daily Operations Summary Report Dashboard with Live Data

Fetches all metrics from Snowflake and generates the HTML dashboard.
Uses SSO authentication via simple_agent_with_sso_auth.py
"""

import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Import the SSO auth module
from simple_agent_with_sso_auth import run_direct_query, run_query_with_sso

# Output files
OUTPUT_HTML = "daily_operations_summary_report_live.html"
OUTPUT_CSV = "daily_ops_summary_data.csv"

# Markets in order
MARKETS_ORDER = [
    "ATLANTA", "AUSTIN", "BIRMINGHAM", "DALLAS", "HOUSTON",
    "JACKSONVILLE", "MEMPHIS", "MIAMI", "MOBILE", "ORLANDO",
    "PUERTO RICO", "TAMPA", "SOUTH"
]


def fetch_availability_data(config_file='config_sso.json', user_email=None, environment='PROD'):
    """Fetch availability metrics from Snowflake."""
    
    query = """
    WITH params AS (
      SELECT
        DATEADD(day, -1, CURRENT_DATE()) AS end_day,
        DATE_TRUNC('QUARTER', DATEADD(day, -1, CURRENT_DATE())) AS qtr_start
    ),
    days_in_qtr AS (
      SELECT DATEDIFF(day, qtr_start, end_day) + 1 AS days_in_qtr, qtr_start, end_day
      FROM params
    ),
    markets AS (
      SELECT column1 AS market_id
      FROM VALUES ('Atlanta'),('Austin'),('Birmingham'),('Dallas'),('Houston'),
                  ('Jacksonville'),('Memphis'),('Miami'),('Mobile'),('Orlando'),
                  ('Puerto Rico'),('Tampa')
    ),

    avail_one AS (
      SELECT UPPER(market_id) AS Market, WEIGHTED_AVG_SCORE AS Value
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_AVAILABILITYONE_MKT_DAY
      WHERE market_id IN (SELECT market_id FROM markets)
      QUALIFY ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY PERIOD_START_TIME DESC) = 1
      
      UNION ALL
      
      SELECT 'SOUTH', WEIGHTED_AVG_SCORE
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_AVAILABILITYONE_REG_DAY
      WHERE region_id = 'SOUTH'
      QUALIFY ROW_NUMBER() OVER (PARTITION BY region_id ORDER BY PERIOD_START_TIME DESC) = 1
    ),

    avail_daily AS (
      SELECT UPPER(market_id) AS Market, COMBO_AVAILABILITY AS Value
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_COMBO_MKT_DAY
      WHERE market_id IN (SELECT market_id FROM markets)
      QUALIFY ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY PERIOD_START_TIME DESC) = 1
      
      UNION ALL
      
      SELECT 'SOUTH', COMBO_AVAILABILITY
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_COMBO_REG_DAY
      WHERE region_id = 'SOUTH'
      QUALIFY ROW_NUMBER() OVER (PARTITION BY region_id ORDER BY PERIOD_START_TIME DESC) = 1
    ),

    avail_trend AS (
      SELECT UPPER(t.market_id) AS Market, COUNT(*) AS Value
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_COMBO_MKT_DAY t
      CROSS JOIN days_in_qtr d
      WHERE t.market_id IN (SELECT market_id FROM markets)
        AND t.period_start_time >= d.qtr_start
        AND t.period_start_time <= d.end_day
        AND t.COMBO_AVAILABILITY >= 99.895
      GROUP BY t.market_id
      
      UNION ALL
      
      SELECT 'SOUTH', COUNT(*)
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_COMBO_REG_DAY t
      CROSS JOIN days_in_qtr d
      WHERE t.region_id = 'SOUTH'
        AND t.period_start_time >= d.qtr_start
        AND t.period_start_time <= d.end_day
        AND t.COMBO_AVAILABILITY >= 99.895
    ),

    allin_daily AS (
      SELECT UPPER(market_id) AS Market, COMBO_AVAILABILITY AS Value
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_FINAL_MKT_DAY
      WHERE market_id IN (SELECT market_id FROM markets)
      QUALIFY ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY PERIOD_START_TIME DESC) = 1
      
      UNION ALL
      
      SELECT 'SOUTH', COMBO_AVAILABILITY
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_FINAL_REG_DAY
      WHERE region_id = 'SOUTH'
      QUALIFY ROW_NUMBER() OVER (PARTITION BY region_id ORDER BY PERIOD_START_TIME DESC) = 1
    ),

    allin_trend AS (
      SELECT UPPER(t.market_id) AS Market, COUNT(*) AS Value
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_FINAL_MKT_DAY t
      CROSS JOIN days_in_qtr d
      WHERE t.market_id IN (SELECT market_id FROM markets)
        AND t.period_start_time >= d.qtr_start
        AND t.period_start_time <= d.end_day
        AND t.COMBO_AVAILABILITY >= 99.895
      GROUP BY t.market_id
      
      UNION ALL
      
      SELECT 'SOUTH', COUNT(*)
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_FINAL_REG_DAY t
      CROSS JOIN days_in_qtr d
      WHERE t.region_id = 'SOUTH'
        AND t.period_start_time >= d.qtr_start
        AND t.period_start_time <= d.end_day
        AND t.COMBO_AVAILABILITY >= 99.895
    ),

    outage_daily AS (
      SELECT UPPER(market_id) AS Market, outage_index AS Value
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_OUTAGEINDEX_MKT_DAY
      WHERE market_id IN (SELECT market_id FROM markets)
      QUALIFY ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY PERIOD_START_TIME DESC) = 1
      
      UNION ALL
      
      SELECT 'SOUTH', outage_index
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_OUTAGEINDEX_REG_DAY
      WHERE region_id = 'SOUTH'
      QUALIFY ROW_NUMBER() OVER (PARTITION BY region_id ORDER BY PERIOD_START_TIME DESC) = 1
    ),

    outage_trend AS (
      SELECT UPPER(t.market_id) AS Market, COUNT_IF(t.outage_index >= 23.895) AS Value
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_OUTAGEINDEX_MKT_DAY t
      CROSS JOIN days_in_qtr d
      WHERE t.market_id IN (SELECT market_id FROM markets)
        AND t.period_start_time >= d.qtr_start
        AND t.period_start_time <= d.end_day
      GROUP BY t.market_id
      
      UNION ALL
      
      SELECT 'SOUTH', COUNT_IF(t.outage_index >= 23.895)
      FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_OUTAGEINDEX_REG_DAY t
      CROSS JOIN days_in_qtr d
      WHERE t.region_id = 'SOUTH'
        AND t.period_start_time >= d.qtr_start
        AND t.period_start_time <= d.end_day
    ),

    all_markets AS (
      SELECT UPPER(market_id) AS Market FROM markets
      UNION ALL
      SELECT 'SOUTH'
    )

    SELECT 
      m.Market,
      COALESCE(ao.Value, 0) AS AvailOne,
      COALESCE(ad.Value, 0) AS Daily,
      COALESCE(at.Value, 0) AS Trend,
      COALESCE(ald.Value, 0) AS AllinDaily,
      COALESCE(alt.Value, 0) AS AllinTrend,
      COALESCE(od.Value, 0) AS OutageIndex,
      COALESCE(ot.Value, 0) AS OutageIndexTrend
    FROM all_markets m
    LEFT JOIN avail_one ao ON m.Market = ao.Market
    LEFT JOIN avail_daily ad ON m.Market = ad.Market
    LEFT JOIN avail_trend at ON m.Market = at.Market
    LEFT JOIN allin_daily ald ON m.Market = ald.Market
    LEFT JOIN allin_trend alt ON m.Market = alt.Market
    LEFT JOIN outage_daily od ON m.Market = od.Market
    LEFT JOIN outage_trend ot ON m.Market = ot.Market
    """
    
    print("Fetching availability data...")
    df = run_direct_query(query, config_file=config_file, user_email=user_email, environment=environment)
    return df


def fetch_incident_data(config_file='config_sso.json', user_email=None, environment='PROD'):
    """Fetch incident metrics from Snowflake."""
    
    query = """
    WITH markets AS (
      SELECT column1 AS market_id
      FROM VALUES ('Atlanta'),('Austin'),('Birmingham'),('Dallas'),('Houston'),
                  ('Jacksonville'),('Memphis'),('Miami'),('Mobile'),('Orlando'),
                  ('Puerto Rico'),('Tampa')
    ),

    inc_24hrs AS (
      SELECT 
        UPPER(m.MARKET_ID) AS Market,
        COUNT(DISTINCT A.INCIDENT_NUMBER) AS Value
      FROM BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_ALL A
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_SITE_TRACKER s ON A.config_item = s.site_id
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_RING_TRACKER r ON s.ring_sys_id = r.ring_sys_id
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_MARKET_TRACKER m ON r.market_sys_id = m.market_sys_id
      WHERE A.STATE IN ('Assigned','Monitoring','Returned','Transferred','Working','Waiting','New','In Progress','On Hold')
        AND A.CONFIG_ITEM NOT ILIKE '%BA' 
        AND A.CONFIG_ITEM NOT ILIKE '%WA'
        AND DATEDIFF('hour', A.OPENED_DATE, CURRENT_TIMESTAMP()) > 24
        AND UPPER(m.MARKET_ID) IN (SELECT UPPER(market_id) FROM markets)
      GROUP BY m.MARKET_ID
      
      UNION ALL
      
      SELECT 'SOUTH', COUNT(DISTINCT A.INCIDENT_NUMBER)
      FROM BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_ALL A
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_SITE_TRACKER s ON A.config_item = s.site_id
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_RING_TRACKER r ON s.ring_sys_id = r.ring_sys_id
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_MARKET_TRACKER m ON r.market_sys_id = m.market_sys_id
      WHERE m.RGN_RGN_ABBRV = 'S'
        AND A.STATE IN ('Assigned','Monitoring','Returned','Transferred','Working','Waiting','New','In Progress','On Hold')
        AND A.CONFIG_ITEM NOT ILIKE '%BA' 
        AND A.CONFIG_ITEM NOT ILIKE '%WA'
        AND DATEDIFF('hour', A.OPENED_DATE, CURRENT_TIMESTAMP()) > 24
    ),

    tts_30days AS (
      SELECT 
        UPPER(m.MARKET_ID) AS Market,
        COUNT(DISTINCT A.INCIDENT_NUMBER) AS Value
      FROM BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_ALL A
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_SITE_TRACKER s ON A.config_item = s.site_id
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_RING_TRACKER r ON s.ring_sys_id = r.ring_sys_id
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_MARKET_TRACKER m ON r.market_sys_id = m.market_sys_id
      WHERE A.STATE IN ('Assigned','Monitoring','Returned','Transferred','Working','Waiting','New','In Progress','On Hold')
        AND A.CONFIG_ITEM NOT ILIKE '%BA' 
        AND A.CONFIG_ITEM NOT ILIKE '%WA'
        AND DATEDIFF('day', A.OPENED_DATE, CURRENT_TIMESTAMP()) > 30
        AND UPPER(m.MARKET_ID) IN (SELECT UPPER(market_id) FROM markets)
      GROUP BY m.MARKET_ID
      
      UNION ALL
      
      SELECT 'SOUTH', COUNT(DISTINCT A.INCIDENT_NUMBER)
      FROM BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_ALL A
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_SITE_TRACKER s ON A.config_item = s.site_id
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_RING_TRACKER r ON s.ring_sys_id = r.ring_sys_id
      INNER JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_MARKET_TRACKER m ON r.market_sys_id = m.market_sys_id
      WHERE m.RGN_RGN_ABBRV = 'S'
        AND A.STATE IN ('Assigned','Monitoring','Returned','Transferred','Working','Waiting','New','In Progress','On Hold')
        AND A.CONFIG_ITEM NOT ILIKE '%BA' 
        AND A.CONFIG_ITEM NOT ILIKE '%WA'
        AND DATEDIFF('day', A.OPENED_DATE, CURRENT_TIMESTAMP()) > 30
    ),

    all_markets AS (
      SELECT UPPER(market_id) AS Market FROM markets
      UNION ALL
      SELECT 'SOUTH'
    )

    SELECT 
      m.Market,
      COALESCE(i24.Value, 0) AS SiInc24hrs,
      COALESCE(t30.Value, 0) AS Tts30Days
    FROM all_markets m
    LEFT JOIN inc_24hrs i24 ON m.Market = i24.Market
    LEFT JOIN tts_30days t30 ON m.Market = t30.Market
    """
    
    print("Fetching incident data...")
    df = run_direct_query(query, config_file=config_file, user_email=user_email, environment=environment)
    return df


def generate_html(data: list, data_date: str) -> str:
    """Generate the HTML dashboard content."""
    
    data_json = json.dumps(data, default=str)
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Daily Operations Summary Report</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      background: #1a1a2e;
      color: #fff;
      min-height: 100vh;
      padding: 20px;
    }}
    .container {{
      max-width: 1600px;
      margin: 0 auto;
      background: #2d2d44;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }}
    .header {{
      background: linear-gradient(135deg, #e20074 0%, #b8005c 100%);
      padding: 20px 30px;
      text-align: center;
    }}
    .header h1 {{
      font-size: 1.8rem;
      font-weight: 600;
      letter-spacing: 1px;
      font-style: italic;
      margin: 0;
    }}
    .datadate {{
      position: absolute;
      top: 20px;
      right: 40px;
      background: #fff;
      color: #333;
      padding: 8px 12px;
      border-radius: 4px;
      font-size: 0.85rem;
      font-weight: 600;
    }}
    .datadate-label {{
      color: #e20074;
      font-weight: 700;
    }}
    .datadate-value {{
      display: block;
      font-size: 1rem;
    }}
    .table-wrapper {{
      overflow-x: auto;
      padding: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }}
    th {{
      background: linear-gradient(135deg, #e20074 0%, #b8005c 100%);
      color: #fff;
      padding: 12px 8px;
      text-align: center;
      font-weight: 600;
      font-size: 0.8rem;
      border: 1px solid #c9006a;
      white-space: nowrap;
    }}
    th.market-col {{
      text-align: left;
      padding-left: 15px;
      min-width: 100px;
    }}
    th.sub {{
      font-size: 0.75rem;
      font-weight: 500;
      padding: 4px 8px;
    }}
    td {{
      padding: 10px 8px;
      text-align: center;
      border: 1px solid #444;
      font-weight: 500;
    }}
    td.market-cell {{
      background: linear-gradient(135deg, #e20074 0%, #b8005c 100%);
      color: #fff;
      text-align: left;
      padding-left: 15px;
      font-weight: 600;
      font-size: 0.8rem;
    }}
    .links-row td {{
      background: linear-gradient(135deg, #e20074 0%, #b8005c 100%);
      color: #fff;
      font-weight: 700;
    }}
    .links-row td.link-cell {{
      color: #ffeb3b;
      text-decoration: underline;
      cursor: pointer;
    }}
    .green {{ background: #4caf50; color: #fff; }}
    .light-green {{ background: #8bc34a; color: #000; }}
    .yellow {{ background: #ffeb3b; color: #000; }}
    .orange {{ background: #ff9800; color: #000; }}
    .red {{ background: #f44336; color: #fff; }}
    .dark-red {{ background: #c62828; color: #fff; }}
    .magenta {{ background: #e20074; color: #fff; }}
    .white {{ background: #fff; color: #000; }}
    .gray {{ background: #9e9e9e; color: #000; }}
    .relative-wrapper {{
      position: relative;
    }}
    .generated-info {{
      text-align: center;
      padding: 10px;
      font-size: 0.75rem;
      color: #888;
    }}
  </style>
</head>
<body>
  <div class="relative-wrapper">
    <div class="datadate">
      <span class="datadate-label">DATADATE</span>
      <span class="datadate-value">{data_date}</span>
    </div>
  </div>
  <div class="container">
    <div class="header">
      <h1>Daily Operations Summary Report</h1>
    </div>
    <div class="table-wrapper">
      <table id="reportTable">
        <thead>
          <tr>
            <th class="market-col">Market</th>
            <th>Avail ONE</th>
            <th>Daily</th>
            <th>Trend</th>
            <th>ALLIN<br>Daily</th>
            <th>ALLIN<br>Trend</th>
            <th>Outage<br>Index</th>
            <th>OutageIndex<br>Trend</th>
            <th>At Risk Cost</th>
            <th>Alarms%</th>
            <th>SI<br>INC &gt;24HRS</th>
            <th>SI INC<br>Transport</th>
            <th>TT'S&gt; 30<br>Days</th>
            <th>Circuit_Delivery<br>QTD</th>
            <th>Gen Ex<br>WKLY</th>
          </tr>
          <tr>
            <th class="market-col sub"></th>
            <th class="sub">8</th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
            <th class="sub"></th>
          </tr>
        </thead>
        <tbody id="tableBody">
        </tbody>
        <tfoot>
          <tr class="links-row">
            <td class="market-cell">Links</td>
            <td class="link-cell">#</td>
            <td></td>
            <td class="link-cell">#</td>
            <td></td>
            <td class="link-cell">#</td>
            <td class="link-cell">#</td>
            <td class="link-cell">#</td>
            <td class="link-cell">#</td>
            <td class="link-cell">#</td>
            <td class="link-cell">#</td>
            <td class="link-cell">#</td>
            <td class="link-cell">#</td>
            <td class="link-cell">#</td>
            <td class="link-cell">#</td>
          </tr>
        </tfoot>
      </table>
    </div>
    <div class="generated-info">
      Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Data from Snowflake PROD
    </div>
  </div>

  <script>
    const DATA = {data_json};

    function getAvailOneClass(val) {{
      if (val >= 99.90) return 'green';
      if (val >= 99.80) return 'light-green';
      if (val >= 99.50) return 'yellow';
      if (val >= 99.00) return 'orange';
      return 'red';
    }}

    function getDailyClass(val) {{
      if (val >= 99.95) return 'green';
      if (val >= 99.85) return 'light-green';
      if (val >= 99.50) return 'yellow';
      if (val >= 99.00) return 'orange';
      return 'red';
    }}

    function getTrendClass(val) {{
      if (val >= 7) return 'green';
      if (val >= 5) return 'light-green';
      if (val >= 3) return 'yellow';
      return 'red';
    }}

    function getAllinClass(val) {{
      if (val >= 99.90) return 'green';
      if (val >= 99.80) return 'light-green';
      if (val >= 99.50) return 'yellow';
      if (val >= 99.00) return 'orange';
      return 'red';
    }}

    function getOutageIndexClass(val) {{
      if (val >= 23.93) return 'green';
      if (val >= 23.90) return 'light-green';
      if (val >= 23.80) return 'yellow';
      return 'red';
    }}

    function getAtRiskCostClass(val) {{
      if (val <= 0.02) return 'green';
      if (val <= 0.05) return 'light-green';
      if (val <= 0.10) return 'yellow';
      return 'red';
    }}

    function getAlarmsClass(val) {{
      if (val <= 5.00) return 'green';
      if (val <= 7.00) return 'light-green';
      if (val <= 10.00) return 'yellow';
      if (val <= 13.00) return 'orange';
      return 'red';
    }}

    function getSiIncClass(val) {{
      if (val <= 2) return 'green';
      if (val <= 4) return 'light-green';
      if (val <= 6) return 'yellow';
      if (val <= 10) return 'orange';
      return 'red';
    }}

    function getTransportClass(val) {{
      if (val === null || val === undefined || val === '') return 'white';
      if (val <= 10) return 'green';
      if (val <= 30) return 'yellow';
      if (val <= 80) return 'orange';
      return 'magenta';
    }}

    function getTts30Class(val) {{
      if (val <= 15) return 'green';
      if (val <= 25) return 'light-green';
      if (val <= 50) return 'yellow';
      if (val <= 100) return 'orange';
      return 'magenta';
    }}

    function getCircuitClass(val) {{
      if (val >= 95) return 'green';
      if (val >= 90) return 'light-green';
      if (val >= 80) return 'yellow';
      if (val >= 70) return 'orange';
      return 'red';
    }}

    function getGenExClass(val) {{
      if (val >= 97) return 'green';
      if (val >= 95) return 'light-green';
      if (val >= 92) return 'yellow';
      if (val >= 88) return 'orange';
      return 'red';
    }}

    function formatVal(val, decimals, suffix) {{
      if (val === null || val === undefined || val === '') return '';
      const num = parseFloat(val);
      if (isNaN(num)) return val;
      return num.toFixed(decimals) + (suffix || '');
    }}

    function renderTable() {{
      const tbody = document.getElementById('tableBody');
      tbody.innerHTML = '';

      DATA.forEach(row => {{
        const tr = document.createElement('tr');
        
        tr.innerHTML = `
          <td class="market-cell">${{row.market}}</td>
          <td class="${{getAvailOneClass(row.availOne)}}">${{formatVal(row.availOne, 2, '%')}}</td>
          <td class="${{getDailyClass(row.daily)}}">${{formatVal(row.daily, 2, '%')}}</td>
          <td class="${{getTrendClass(row.trend)}}">${{row.trend}}</td>
          <td class="${{getAllinClass(row.allinDaily)}}">${{formatVal(row.allinDaily, 2, '%')}}</td>
          <td class="${{getTrendClass(row.allinTrend)}}">${{row.allinTrend}}</td>
          <td class="${{getOutageIndexClass(row.outageIndex)}}">${{formatVal(row.outageIndex, 2, '')}}</td>
          <td class="${{getTrendClass(row.outageIndexTrend)}}">${{row.outageIndexTrend}}</td>
          <td class="${{getAtRiskCostClass(row.atRiskCost)}}">${{formatVal(row.atRiskCost, 2, '%')}}</td>
          <td class="${{getAlarmsClass(row.alarms)}}">${{formatVal(row.alarms, 2, '%')}}</td>
          <td class="${{getSiIncClass(row.siInc24)}}">${{row.siInc24}}</td>
          <td class="${{getTransportClass(row.siIncTransport)}}">${{row.siIncTransport !== null && row.siIncTransport !== undefined ? row.siIncTransport : ''}}</td>
          <td class="${{getTts30Class(row.tts30)}}">${{row.tts30}}</td>
          <td class="${{getCircuitClass(row.circuitDelivery)}}">${{row.circuitDelivery}}%</td>
          <td class="${{getGenExClass(row.genEx)}}">${{row.genEx}}%</td>
        `;
        
        tbody.appendChild(tr);
      }});
    }}

    document.addEventListener('DOMContentLoaded', renderTable);
  </script>
</body>
</html>'''
    
    return html


def merge_data(avail_df, incident_df):
    """Merge availability and incident data into final format."""
    
    # Create market index
    market_order = {m: i for i, m in enumerate(MARKETS_ORDER)}
    
    # Merge dataframes
    merged = avail_df.merge(incident_df, on='MARKET', how='outer')
    
    # Add sort order
    merged['sort_order'] = merged['MARKET'].map(market_order)
    merged = merged.sort_values('sort_order').drop('sort_order', axis=1)
    
    # Convert to list of dicts for JSON
    data = []
    for _, row in merged.iterrows():
        data.append({
            "market": row.get('MARKET', ''),
            "availOne": float(row.get('AVAILONE', 0) or 0),
            "daily": float(row.get('DAILY', 0) or 0),
            "trend": int(row.get('TREND', 0) or 0),
            "allinDaily": float(row.get('ALLINDAILY', 0) or 0),
            "allinTrend": int(row.get('ALLINTREND', 0) or 0),
            "outageIndex": float(row.get('OUTAGEINDEX', 0) or 0),
            "outageIndexTrend": int(row.get('OUTAGEINDEXTREND', 0) or 0),
            "atRiskCost": 0.05,  # Placeholder - add query when table is identified
            "alarms": 7.5,  # Placeholder - add query when table is identified
            "siInc24": int(row.get('SIINC24HRS', 0) or 0),
            "siIncTransport": None,  # Placeholder - add query when table is identified
            "tts30": int(row.get('TTS30DAYS', 0) or 0),
            "circuitDelivery": 90,  # Placeholder - add query when table is identified
            "genEx": 95  # Placeholder - add query when table is identified
        })
    
    return data


def main(config_file='config_sso.json', user_email=None, environment='PROD'):
    """Main function to generate the dashboard."""
    
    print("=" * 60)
    print("Daily Operations Summary Report Generator")
    print("=" * 60)
    print(f"Environment: {environment}")
    print(f"Output: {OUTPUT_HTML}")
    print("=" * 60)
    
    # Fetch data from Snowflake
    try:
        avail_df = fetch_availability_data(config_file, user_email, environment)
        incident_df = fetch_incident_data(config_file, user_email, environment)
    except Exception as e:
        print(f"\nError fetching data: {e}")
        print("\nUsing sample data instead...")
        
        # Fall back to sample data
        sample_data = [
            {"market": "ATLANTA", "availOne": 99.92, "daily": 99.91, "trend": 5, "allinDaily": 99.74, "allinTrend": 4, "outageIndex": 23.94, "outageIndexTrend": 8, "atRiskCost": 0.01, "alarms": 5.14, "siInc24": 4, "siIncTransport": 78, "tts30": 84, "circuitDelivery": 84, "genEx": 91},
            {"market": "AUSTIN", "availOne": 99.85, "daily": 99.86, "trend": 3, "allinDaily": 99.01, "allinTrend": 0, "outageIndex": 23.90, "outageIndexTrend": 5, "atRiskCost": 0.03, "alarms": 8.62, "siInc24": 5, "siIncTransport": 101, "tts30": 88, "circuitDelivery": 88, "genEx": 93},
            {"market": "BIRMINGHAM", "availOne": 98.08, "daily": 98.01, "trend": 3, "allinDaily": 97.97, "allinTrend": 3, "outageIndex": 23.56, "outageIndexTrend": 4, "atRiskCost": 0.08, "alarms": 13.01, "siInc24": 2, "siIncTransport": 79, "tts30": 100, "circuitDelivery": 100, "genEx": 88},
            {"market": "DALLAS", "availOne": 99.88, "daily": 99.89, "trend": 3, "allinDaily": 99.88, "allinTrend": 4, "outageIndex": 23.92, "outageIndexTrend": 6, "atRiskCost": 0.09, "alarms": 6.45, "siInc24": 5, "siIncTransport": 99, "tts30": 23, "circuitDelivery": 86, "genEx": 94},
            {"market": "HOUSTON", "availOne": 99.90, "daily": 99.87, "trend": 6, "allinDaily": 99.79, "allinTrend": 1, "outageIndex": 23.90, "outageIndexTrend": 8, "atRiskCost": 0.16, "alarms": 14.54, "siInc24": 10, "siIncTransport": 1, "tts30": 125, "circuitDelivery": 71, "genEx": 97},
            {"market": "JACKSONVILLE", "availOne": 99.94, "daily": 99.90, "trend": 6, "allinDaily": 99.88, "allinTrend": 5, "outageIndex": 23.93, "outageIndexTrend": 8, "atRiskCost": 0.02, "alarms": 7.00, "siInc24": 3, "siIncTransport": 4, "tts30": 90, "circuitDelivery": 86, "genEx": 95},
            {"market": "MEMPHIS", "availOne": 99.79, "daily": 99.96, "trend": 4, "allinDaily": 99.93, "allinTrend": 4, "outageIndex": 23.96, "outageIndexTrend": 4, "atRiskCost": 0.01, "alarms": 5.47, "siInc24": 1, "siIncTransport": 1, "tts30": 90, "circuitDelivery": 93, "genEx": 92},
            {"market": "MIAMI", "availOne": 99.96, "daily": 99.98, "trend": 7, "allinDaily": 99.95, "allinTrend": 7, "outageIndex": 23.97, "outageIndexTrend": 7, "atRiskCost": 0.01, "alarms": 6.84, "siInc24": 4, "siIncTransport": 23, "tts30": 11, "circuitDelivery": 100, "genEx": 96},
            {"market": "MOBILE", "availOne": 99.88, "daily": 99.90, "trend": 7, "allinDaily": 99.89, "allinTrend": 5, "outageIndex": 23.90, "outageIndexTrend": 5, "atRiskCost": 0.07, "alarms": 7.46, "siInc24": 4, "siIncTransport": 114, "tts30": 20, "circuitDelivery": 98, "genEx": 97},
            {"market": "ORLANDO", "availOne": 99.90, "daily": 99.94, "trend": 4, "allinDaily": 99.94, "allinTrend": 4, "outageIndex": 23.94, "outageIndexTrend": 7, "atRiskCost": 0.18, "alarms": 8.18, "siInc24": 3, "siIncTransport": None, "tts30": 20, "circuitDelivery": 90, "genEx": 97},
            {"market": "PUERTO RICO", "availOne": 99.90, "daily": 99.97, "trend": 6, "allinDaily": 99.90, "allinTrend": 6, "outageIndex": 23.94, "outageIndexTrend": 7, "atRiskCost": 0.00, "alarms": 4.51, "siInc24": 5, "siIncTransport": None, "tts30": 14, "circuitDelivery": 99, "genEx": 98},
            {"market": "TAMPA", "availOne": 99.94, "daily": 99.98, "trend": 7, "allinDaily": 99.91, "allinTrend": 4, "outageIndex": 23.92, "outageIndexTrend": 8, "atRiskCost": 0.02, "alarms": 8.11, "siInc24": 5, "siIncTransport": None, "tts30": 26, "circuitDelivery": 95, "genEx": 96},
            {"market": "SOUTH", "availOne": 99.88, "daily": 99.89, "trend": 3, "allinDaily": 99.84, "allinTrend": 2, "outageIndex": 23.92, "outageIndexTrend": 6, "atRiskCost": 0.05, "alarms": 8.14, "siInc24": 16, "siIncTransport": 18, "tts30": 211, "circuitDelivery": 90, "genEx": 94}
        ]
        
        data_date = (datetime.now() - timedelta(days=1)).strftime("%-m/%-d/%Y").replace("-", "/")
        html_content = generate_html(sample_data, data_date)
        
        Path(OUTPUT_HTML).write_text(html_content, encoding='utf-8')
        print(f"\nDashboard generated: {OUTPUT_HTML}")
        return
    
    # Merge data
    data = merge_data(avail_df, incident_df)
    
    # Save data to CSV
    df_out = pd.DataFrame(data)
    df_out.to_csv(OUTPUT_CSV, index=False)
    print(f"\nData saved to: {OUTPUT_CSV}")
    
    # Generate HTML
    data_date = (datetime.now() - timedelta(days=1)).strftime("%m/%d/%Y")
    html_content = generate_html(data, data_date)
    
    Path(OUTPUT_HTML).write_text(html_content, encoding='utf-8')
    print(f"Dashboard generated: {OUTPUT_HTML}")
    print("\n" + "=" * 60)
    print("SUCCESS! Dashboard ready.")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate Daily Operations Summary Report')
    parser.add_argument('--config', '-c', default='config_sso.json', help='Config file path')
    parser.add_argument('--user', '-u', dest='user_email', help='T-Mobile email for SSO')
    parser.add_argument('--env', '-e', dest='environment', default='PROD', 
                        choices=['DEV', 'QAT', 'PROD'], help='Environment')
    
    args = parser.parse_args()
    
    main(config_file=args.config, user_email=args.user_email, environment=args.environment)
