-- Daily Operations Summary Report - Combined Query
-- Fetches all metrics for the Daily Operations Summary Report dashboard

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

-- ============================================================
-- AVAILABILITY ONE (Latest daily weighted avg score)
-- ============================================================
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

-- ============================================================
-- AVAILABILITY DAILY (Latest combo availability)
-- ============================================================
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

-- ============================================================
-- AVAILABILITY TREND (Days meeting threshold this quarter)
-- ============================================================
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

-- ============================================================
-- ALLIN DAILY (Latest ALLIN availability)
-- ============================================================
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

-- ============================================================
-- ALLIN TREND (Days meeting ALLIN threshold this quarter)
-- ============================================================
allin_trend AS (
  SELECT UPPER(t.market_id) AS Market, COUNT(*) AS Value
  FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_FINAL_MKT_DAY t
  CROSS JOIN days_in_qtr d
  WHERE t.market_id IN (SELECT market_id FROM markets)
    AND t.period_start_time >= d.qtr_start
    AND t.period_start_time <= d.end_day
    AND t.COMBO_AVAILABILITY >= 0.99895
  GROUP BY t.market_id
  
  UNION ALL
  
  SELECT 'SOUTH', COUNT(*)
  FROM CDW_UDP_NETWORK_DB.NETWORK_V.AVAIL_FINAL_REG_DAY t
  CROSS JOIN days_in_qtr d
  WHERE t.region_id = 'SOUTH'
    AND t.period_start_time >= d.qtr_start
    AND t.period_start_time <= d.end_day
    AND t.COMBO_AVAILABILITY >= 0.99895
),

-- ============================================================
-- OUTAGE INDEX DAILY (Latest outage index)
-- ============================================================
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

-- ============================================================
-- OUTAGE INDEX TREND (Days meeting threshold this quarter)
-- ============================================================
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

-- ============================================================
-- INCIDENTS > 24 HOURS (SI INC >24HRS) by Market
-- ============================================================
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

-- ============================================================
-- TROUBLE TICKETS > 30 DAYS by Market
-- ============================================================
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

-- ============================================================
-- ALL MARKETS LIST (to ensure we have all markets even with null data)
-- ============================================================
all_markets AS (
  SELECT UPPER(market_id) AS Market FROM markets
  UNION ALL
  SELECT 'SOUTH'
)

-- ============================================================
-- FINAL OUTPUT: Combine all metrics by market
-- ============================================================
SELECT 
  m.Market,
  COALESCE(ao.Value, 0) AS AvailOne,
  COALESCE(ad.Value, 0) AS Daily,
  COALESCE(at.Value, 0) AS Trend,
  COALESCE(ald.Value, 0) AS AllinDaily,
  COALESCE(alt.Value, 0) AS AllinTrend,
  COALESCE(od.Value, 0) AS OutageIndex,
  COALESCE(ot.Value, 0) AS OutageIndexTrend,
  COALESCE(i24.Value, 0) AS SiInc24hrs,
  COALESCE(t30.Value, 0) AS Tts30Days
FROM all_markets m
LEFT JOIN avail_one ao ON m.Market = ao.Market
LEFT JOIN avail_daily ad ON m.Market = ad.Market
LEFT JOIN avail_trend at ON m.Market = at.Market
LEFT JOIN allin_daily ald ON m.Market = ald.Market
LEFT JOIN allin_trend alt ON m.Market = alt.Market
LEFT JOIN outage_daily od ON m.Market = od.Market
LEFT JOIN outage_trend ot ON m.Market = ot.Market
LEFT JOIN inc_24hrs i24 ON m.Market = i24.Market
LEFT JOIN tts_30days t30 ON m.Market = t30.Market
ORDER BY 
  CASE m.Market 
    WHEN 'ATLANTA' THEN 1
    WHEN 'AUSTIN' THEN 2
    WHEN 'BIRMINGHAM' THEN 3
    WHEN 'DALLAS' THEN 4
    WHEN 'HOUSTON' THEN 5
    WHEN 'JACKSONVILLE' THEN 6
    WHEN 'MEMPHIS' THEN 7
    WHEN 'MIAMI' THEN 8
    WHEN 'MOBILE' THEN 9
    WHEN 'ORLANDO' THEN 10
    WHEN 'PUERTO RICO' THEN 11
    WHEN 'TAMPA' THEN 12
    WHEN 'SOUTH' THEN 13
    ELSE 99
  END;
