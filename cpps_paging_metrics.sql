-- ============================================================================
-- CPPS PAGING Metrics - Market Level Dashboard
-- ============================================================================
-- Source: PRESENTATION.PCMD.PCMD_AMF_AGG_HOURLY
-- Run with: python simple_agent_with_sso_auth.py cpps_paging_metrics.sql --env PROD_PCMD
--
-- Metrics:
--   - Paging Success Count
--   - Paging Success Rate (based on downtime hours)
--   - Availability % (hours with successful paging / total hours)
--   - Downtime Hours (hours where PAGING_SUCC = 0)
-- ============================================================================

WITH date_params AS (
    SELECT 
        DATEADD('day', -30, CURRENT_DATE()) AS START_DATE,
        CURRENT_DATE() AS END_DATE
),

-- Base data from PCMD AMF hourly aggregates
base AS (
    SELECT *
    FROM PCMD_AMF_AGG_HOURLY, date_params
    WHERE LOCAL_DATE_PART >= date_params.START_DATE
      AND LOCAL_DATE_PART <= date_params.END_DATE
),

-- Market-hour level aggregation (determines downtime per market-hour)
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

-- Daily aggregation per market
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

-- Overall market summary (last 30 days)
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

-- Latest day metrics per market
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

-- Final output: combine summary with latest day
SELECT
    ms.MARKET,
    ms.REGION,
    ms.DATE_START,
    ms.DATE_END,
    ms.DAYS_COUNT,
    
    -- Overall metrics (30 days)
    ms.TOTAL_PAGING_SUCC,
    ms.TOTAL_PAGING_ATT,
    ms.PAGING_SUCCESS_RATE_PCT,
    ms.TOTAL_HOURS,
    ms.TOTAL_DOWNTIME_HOURS,
    ms.TOTAL_UPTIME_HOURS,
    ms.AVAILABILITY_PCT,
    ms.DOWNTIME_PCT,
    
    -- Latest day metrics
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
ORDER BY ms.AVAILABILITY_PCT ASC, ms.MARKET;
