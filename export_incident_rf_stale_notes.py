"""
Snowflake export: RF / Field Ops / Switch incidents with stale work notes
(no qualifying note in window, or last note > 30 days).

Uses config_sso.json + browser SSO (or --auth azure_ad_oauth).

Usage:
  .venv\\Scripts\\python.exe export_incident_rf_stale_notes.py
  .venv\\Scripts\\python.exe export_incident_rf_stale_notes.py --out my_export.csv --env PROD

To use the .sql file instead of the embedded query:
  .venv\\Scripts\\python.exe export_incident_rf_stale_notes.py --sql-file incident_rf_fieldops_switch_notes.sql
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Embedded query (keep in sync with incident_rf_fieldops_switch_notes.sql if you maintain both).
INCIDENT_EXTRACT_SQL = r"""
WITH TIX AS (
    SELECT DISTINCT inc.INCIDENT_NUMBER
    FROM BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_ALL INC
    INNER JOIN BDM_NDW_IDENTIFY_MANAGEMENT_DB.PROFILEMANAGER_V.V_GROUP G
        ON INC.ASSIGNMENT_GROUP = G.GROUP_NAME
    WHERE UPPER(G.CATEGORY) IN ('RF', 'FIELD OPS', 'SWITCH')
      AND (
          INC.OPENED_DATE BETWEEN DATEADD('year', -2, CURRENT_DATE) AND CURRENT_DATE
          OR INC.RESOLVED_DATE IS NULL
      )
      AND UPPER(INC.ASSIGNMENT_GROUP) <> 'FIELDGLASS'
),
LatestNotes AS (
    SELECT DISTINCT
        N.INCIDENT_NUMBER,
        MAX(N.SYS_CREATED_ON) AS MAX_CREATED_ON
    FROM BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_NOTES N
    WHERE N.SYS_CREATED_ON BETWEEN DATEADD('year', -2, CURRENT_DATE) AND CURRENT_DATE
      AND N.SYS_CREATED_BY NOT ILIKE '%SVC_PRD_ITSM_INT%'
    GROUP BY N.INCIDENT_NUMBER
),
NotesWithActivity AS (
    SELECT DISTINCT
        N.INCIDENT_NUMBER,
        LEFT(REGEXP_REPLACE(N.ACTIVITY, '<[^>]*>', ''), 1000) AS ACTIVITY,
        LN.MAX_CREATED_ON,
        ROW_NUMBER() OVER (
            PARTITION BY N.INCIDENT_NUMBER
            ORDER BY N.SYS_CREATED_ON DESC, N.ACTIVITY
        ) AS RN
    FROM BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_NOTES N
    INNER JOIN LatestNotes LN
        ON N.INCIDENT_NUMBER = LN.INCIDENT_NUMBER
       AND N.SYS_CREATED_ON = LN.MAX_CREATED_ON
),
FilteredNotesWithActivity AS (
    SELECT DISTINCT
        INCIDENT_NUMBER,
        REGEXP_REPLACE(
            REGEXP_REPLACE(ACTIVITY, '<[^>]+>', ''),
            '\\[CODE\\]|\\[/CODE\\]',
            ''
        ) AS ACTIVITY,
        MAX_CREATED_ON
    FROM NotesWithActivity N
    WHERE RN = 1
)
SELECT DISTINCT
    CASE
        WHEN UPPER(INC.STATE) IN ('RESOLVED', 'CLOSED') THEN 'RESOLVED_CLOSED'
        WHEN UPPER(INC.STATE) IN ('CANCELED', 'TERMINATED') THEN 'CANCELED_TERMINATED'
        ELSE 'OPEN'
    END AS REPORT_TYPE,
    INC.INCIDENT_NUMBER AS TT_ID,
    CASE
        WHEN MKT.MARKET_ID ILIKE '%EIT%' OR MKT.MARKET_ID ILIKE '%Enterprise IT%' THEN 'EIT'
        ELSE CASE
            WHEN MKT.REGION_ID IS NULL OR MKT.REGION_ID = 'CORPORATE' THEN
                CASE
                    WHEN LEFT(INC.ASSIGNMENT_GROUP, 2) = 'S-' THEN 'SOUTH'
                    WHEN LEFT(INC.ASSIGNMENT_GROUP, 2) = 'C-' THEN 'CENTRAL'
                    WHEN LEFT(INC.ASSIGNMENT_GROUP, 2) = 'W-' THEN 'WEST'
                    WHEN LEFT(INC.ASSIGNMENT_GROUP, 2) = 'N-' THEN 'NORTHEAST'
                    ELSE MKT.REGION_ID
                END
            ELSE MKT.REGION_ID
        END
    END AS REGION_NAME,
    MKT.M_MARKET_ABBREVATION AS MKT_CODE,
    MKT.MARKET_ID AS MARKETNAME,
    MKT.M_AREA AS M_AREA,
    INC.CONFIG_ITEM AS ELEMENT_ID,
    R.R_RING_ID_DESCRIPTION AS ELEMENT_CLASS,
    S.S_SITE_LATITUDE,
    S.S_SITE_LONGITUDE,
    INC.DESCRIPTION AS TT_DESCRIPTION,
    INC.OPENED_DATE AS CREATED_DATE,
    INC.RESOLVED_DATE,
    CASE
        WHEN UPPER(INC.STATE) NOT IN ('RESOLVED', 'CLOSED', 'TERMINATED', 'CANCELLED')
            THEN DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE)
        WHEN UPPER(INC.STATE) IN ('RESOLVED', 'CLOSED')
            THEN DATEDIFF('day', INC.OPENED_DATE, INC.RESOLVED_DATE)
    END AS DAYS_OPEN,
    CASE
        WHEN UPPER(INC.STATE) NOT IN ('RESOLVED', 'CLOSED', 'TERMINATED', 'CANCELLED')
            THEN DATEDIFF('hour', INC.OPENED_DATE, CURRENT_DATE)
        WHEN UPPER(INC.STATE) IN ('RESOLVED', 'CLOSED')
            THEN DATEDIFF('hour', INC.OPENED_DATE, INC.RESOLVED_DATE)
    END AS HOURS_OPEN,
    INC.STATE AS STATUS_DESC,
    INC.HOLD_REASON,
    INC.ASSIGNMENT_GROUP AS GROUP_NAME,
    INC.ASSIGNED_TO AS ASSIGNED_TO,
    U.MANAGER AS MANAGER,
    INC.PRIORITY AS PRIORITY_ID,
    CASE WHEN INC.OPENED_DATE < CURRENT_DATE - 30 THEN 'Greaterthan30' ELSE 'All' END AS AGETKT,
    CASE
        WHEN UPPER(INC.STATE) NOT IN ('RESOLVED', 'CLOSED', 'CANCELED', 'TERMINATED') THEN
            CASE
                WHEN DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) >= 10
                     AND DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) < 30 THEN '10+ days'
                WHEN DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) > 30 THEN '30+ days'
            END
    END AS LDT_OPEN,
    CASE
        WHEN UPPER(INC.STATE) NOT IN ('RESOLVED', 'CLOSED', 'CANCELED', 'TERMINATED') THEN
            CASE
                WHEN DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) < 5 THEN '0-5 days'
                WHEN DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) >= 5
                     AND DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) < 10 THEN '5+ days'
                WHEN DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) >= 10
                     AND DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) < 15 THEN '10+ days'
                WHEN DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) >= 15
                     AND DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) < 20 THEN '15+ days'
                WHEN DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) >= 20
                     AND DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) < 30 THEN '20+ days'
                WHEN DATEDIFF('day', INC.OPENED_DATE, CURRENT_DATE) >= 30 THEN '30+ days'
            END
    END AS LDT_OPEN_2,
    G.CATEGORY AS GROUP_CATEGORY,
    INC.CHANNEL AS SOURCE,
    N.MAX_CREATED_ON AS LAST_NOTE_DT,
    N.ACTIVITY AS LAST_NOTE,
    INC.U_SCR_SYMPTOM AS SYMPTOM,
    INC.U_SCR_CAUSE AS CAUSE,
    INC.U_SCR_RESOLUTION AS RESOLUTION,
    INC.U_CUSTOM_DATA,
    INC.U_FULLFILLMENT_SYSTEM,
    INC.U_FULLFILLMENT_SYSTEM_ID,
    INC.WORK_START AS ACTUAL_ETA,
    INC.EXPECTED_START AS ESTIMATED_ETA,
    INC.DUE_DATE AS ESTIMATED_ETR,
    INC.RESOLVED_DATE AS ACTUAL_ETR,
    CONVERT_TIMEZONE('UTC', 'America/Chicago', SYSDATE()) AS REFRESHED_AT,
    INC.MTTR_MINUTES / 60 AS MTTR_HR,
    CASE
        WHEN INC.WORK_START IS NOT NULL
             AND INC.RESOLVED_DATE IS NOT NULL
             AND INC.EXPECTED_START IS NOT NULL
             AND INC.DUE_DATE IS NOT NULL
            THEN 1
        ELSE 0
    END AS ALL_ETA_ETR,
    CASE WHEN INC.EXPECTED_START IS NOT NULL AND INC.DUE_DATE IS NOT NULL THEN 1 ELSE 0 END AS ETA_ETR,
    CASE
        WHEN INC.DUE_DATE > CURRENT_DATE THEN 1
        WHEN INC.DUE_DATE < CURRENT_DATE THEN 0
        WHEN INC.DUE_DATE IS NULL THEN NULL
    END AS ESTIMATED_ETR_VALID,
    CASE
        WHEN INC.DUE_DATE < CURRENT_DATE THEN 1
        WHEN INC.DUE_DATE > CURRENT_DATE THEN 0
        WHEN INC.DUE_DATE IS NULL THEN NULL
    END AS ESTIMATED_ETR_EXPIRED,
    CASE
        WHEN INC.DUE_DATE BETWEEN CURRENT_DATE AND DATEADD('day', 2, CURRENT_DATE) THEN 1
        WHEN INC.RESOLVED_DATE IS NULL AND INC.DUE_DATE > DATEADD('day', 2, CURRENT_DATE) THEN 0
        WHEN INC.RESOLVED_DATE IS NULL AND INC.DUE_DATE IS NULL THEN NULL
    END AS ESTIMATED_ETR_NEAR_EXPIRE,
    CASE WHEN INC.RESOLVED_DATE IS NULL AND INC.DUE_DATE IS NULL THEN 1 END AS ESTIMATED_ETR_BLANK,
    COALESCE(
        (
            SELECT LISTAGG(ASH_SUB.GROUP_TO, '>') WITHIN GROUP (ORDER BY ASH_SUB.CREATED_DATE)
            FROM BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_ASSIGNMENT_STATUS_HISTORY ASH_SUB
            WHERE ASH_SUB.INCIDENT_NUMBER = INC.INCIDENT_NUMBER
        ),
        INC.ASSIGNMENT_GROUP
    ) AS PATH,
    INC.RESOLVED_BY,
    CASE
        WHEN INC.PRIORITY = '2 - High' THEN 240
        WHEN INC.PRIORITY = '3 - Moderate' THEN 4320
        WHEN INC.PRIORITY = '4 - Low' THEN 10080
    END AS TICKET_SLA,
    CASE WHEN INC.RESOLVED_BY LIKE 'SVC_PRD_%' THEN 1 ELSE 0 END AS AUTO_CLOSE,
    INC.CATEGORY,
    INC.SUBCATEGORY,
    INC.OPENED_BY,
    'https://tess.service-now.com/now/sow/record/incident/' || INC.SYS_ID AS URL
FROM BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_ALL INC
INNER JOIN TIX ON INC.INCIDENT_NUMBER = TIX.INCIDENT_NUMBER
LEFT JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_SITE_TRACKER S
    ON SPLIT_PART(INC.CONFIG_ITEM, '_', 1) = S.SITE_ID
LEFT JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_RING_TRACKER R
    ON S.RING_ID = R.RING_ID
LEFT JOIN BDM_NDW_NTWK_SITE_DEVELOPMENT_DB.MAGENTABUILT_REFERENCE_V.V_MARKET_TRACKER MKT
    ON R.MARKET_ID = MKT.MARKET_ID
LEFT JOIN BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_SYS_USER U
    ON INC.ASSIGNED_TO = U.NAME
LEFT JOIN BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_SYS_USER_GROUP AG
    ON INC.ASSIGNMENT_GROUP = AG.NAME
LEFT JOIN BDM_NDW_IDENTIFY_MANAGEMENT_DB.PROFILEMANAGER_V.V_GROUP G
    ON INC.ASSIGNMENT_GROUP = G.GROUP_NAME
LEFT JOIN FilteredNotesWithActivity N
    ON TIX.INCIDENT_NUMBER = N.INCIDENT_NUMBER
WHERE (
      N.MAX_CREATED_ON IS NULL
      OR DATEDIFF('day', N.MAX_CREATED_ON, CURRENT_DATE) > 30
  )
  AND UPPER(TRIM(COALESCE(INC.STATE, ''))) NOT IN (
      'RESOLVED',
      'CLOSED',
      'CANCELED',
      'CANCELLED',
      'TERMINATED'
  )
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export RF Field Ops / Switch incident stale-notes from Snowflake.")
    parser.add_argument(
        "--sql-file",
        type=Path,
        default=None,
        help="Read query from this file instead of embedded SQL",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=HERE / "incident_rf_fieldops_stale_notes.csv",
        help="Output CSV path",
    )
    parser.add_argument("--config", "-c", type=Path, default=HERE / "config_sso.json")
    parser.add_argument("--user", "-u", dest="user_email", default=None)
    parser.add_argument("--env", "-e", choices=["DEV", "QAT", "PROD", "PROD_PCMD"], default=None)
    parser.add_argument("--auth", choices=["snowflake_sso", "azure_ad_oauth"], default="snowflake_sso")
    args = parser.parse_args()

    from simple_agent_with_sso_auth import (
        AUTH_AZURE_AD_OAUTH,
        AUTH_SNOWFLAKE_SSO,
        run_query_with_sso,
    )

    import tempfile

    auth = AUTH_AZURE_AD_OAUTH if args.auth == "azure_ad_oauth" else AUTH_SNOWFLAKE_SSO
    tmp_created: Path | None = None

    if args.sql_file:
        if not args.sql_file.is_file():
            print(f"SQL file not found: {args.sql_file}", file=sys.stderr)
            sys.exit(1)
        query_path = args.sql_file.resolve()
    else:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".sql",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(INCIDENT_EXTRACT_SQL)
            tmp_created = Path(tmp.name)
        query_path = tmp_created
    try:
        run_query_with_sso(
            str(query_path),
            config_file=str(args.config.resolve()),
            output_file=str(args.out.resolve()),
            user_email=args.user_email,
            environment=args.env,
            auth_method=auth,
        )
    finally:
        if tmp_created is not None:
            tmp_created.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
