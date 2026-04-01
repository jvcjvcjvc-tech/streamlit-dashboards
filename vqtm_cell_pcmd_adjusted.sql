-- =============================================================================
-- VQTM cell daily + PCMD (AMF/MME) COTTR QHOUR — adjusted downtime
--
-- RULE: If UNIQUE_SUBSCRIBER_COUNT >= 1 in AMF OR MME PCMD rows for the cell
--       on the calendar day, then adjusted downtime = 0; else keep VQTM raw.
--
-- DATE: 2026-03-21  (search/replace if needed)
--
-- BEFORE FIRST RUN: DESCRIBE VIEW ... each object; rename columns below to match.
--
-- Typical renames (examples only — confirm in your account):
--   PCMD time: QHOUR_START | REPORT_QHOUR | PERIOD_START
--   PCMD cell: CELL_ID | NCGI | GLOBAL_CELL_ID | EUTRANCELL_ID
--   PCMD subs: UNIQUE_SUBSCRIBER_COUNT | DISTINCT_SUBSCRIBER_CNT | UNIQUE_IMSI_CNT
--   Cell daily date: PERIOD_START_TIME | REPORT_DATE | AVAIL_DATE
--   Cell daily downtime: TOTAL_DOWNTIME | CELL_DOWNTIME_SEC | DOWNTIME_SECONDS
-- =============================================================================

WITH amf_sub_cells AS (
    SELECT DISTINCT UPPER(TRIM(TO_VARCHAR(CELL_ID))) AS cell_key
    FROM BDM_QTM_PRESENTATION_SH.PCMD_ML_LAB.VPCMD_AMF_COTTR_QHOUR_AGG
    WHERE DATE(QHOUR_START) = DATE('2026-03-21')
      AND NVL(UNIQUE_SUBSCRIBER_COUNT, 0) >= 1
),
mme_sub_cells AS (
    SELECT DISTINCT UPPER(TRIM(TO_VARCHAR(CELL_ID))) AS cell_key
    FROM BDM_QTM_PRESENTATION_SH.PCMD_ML_LAB.VPCMD_MME_COTTR_QHOUR_AGG
    WHERE DATE(QHOUR_START) = DATE('2026-03-21')
      AND NVL(UNIQUE_SUBSCRIBER_COUNT, 0) >= 1
),
pcmd_any_sub AS (
    SELECT cell_key FROM amf_sub_cells
    UNION
    SELECT cell_key FROM mme_sub_cells
),
cell_day AS (
    SELECT
        UPPER(TRIM(TO_VARCHAR(CELL_ID))) AS cell_key,
        SITE_ID AS site_id,
        REGION_ID AS region_id,
        MARKET_ID AS market_id,
        NVL(TOTAL_DOWNTIME, 0) AS raw_downtime_sec,
        NVL(TOTAL_TIME, 0) AS total_time_sec
    FROM BDM_QTM_PRESENTATION_SH.QI_SHARED.VQTM_RAN_AVAILABILITY_CELL_DAILY
    WHERE DATE(PERIOD_START_TIME) = DATE('2026-03-21')
),
joined AS (
    SELECT
        c.cell_key,
        c.site_id,
        c.region_id,
        c.market_id,
        c.raw_downtime_sec,
        c.total_time_sec,
        (p.cell_key IS NOT NULL) AS has_pcmd_subscriber,
        CASE WHEN p.cell_key IS NOT NULL THEN 0 ELSE c.raw_downtime_sec END AS adjusted_downtime_sec
    FROM cell_day c
    LEFT JOIN pcmd_any_sub p ON c.cell_key = p.cell_key
)
SELECT
    cell_key,
    site_id,
    region_id,
    market_id,
    raw_downtime_sec,
    total_time_sec,
    has_pcmd_subscriber,
    adjusted_downtime_sec,
    CASE
        WHEN total_time_sec > 0
        THEN 100.0 * (total_time_sec - adjusted_downtime_sec) / NULLIF(total_time_sec, 0)
    END AS adjusted_avail_pct_approx
FROM joined
ORDER BY adjusted_downtime_sec DESC, cell_key
;
