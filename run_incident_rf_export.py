"""
Run the RF / Field Ops / Switch stale-notes extract in Python (Snowflake SSO).

Usage (from this folder):
  .venv\\Scripts\\python.exe run_incident_rf_export.py
  .venv\\Scripts\\python.exe run_incident_rf_export.py --env PROD --user you@t-mobile.com

Or call from your own code:
  from simple_agent_with_sso_auth import run_query_with_sso
  run_query_with_sso("incident_rf_fieldops_switch_notes.sql", output_file="incident_rf_fieldops_stale_notes.csv")
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQL = HERE / "incident_rf_fieldops_switch_notes.sql"
CSV = HERE / "incident_rf_fieldops_stale_notes.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export incident RF FieldOps stale-notes CSV via Snowflake SSO.")
    parser.add_argument(
        "--sql",
        type=Path,
        default=SQL,
        help=f"Path to .sql file (default: {SQL.name})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=CSV,
        help=f"Output CSV (default: {CSV.name})",
    )
    parser.add_argument("--config", "-c", default="config_sso.json")
    parser.add_argument("--user", "-u", dest="user_email", default=None)
    parser.add_argument("--env", "-e", choices=["DEV", "QAT", "PROD", "PROD_PCMD"], default=None)
    parser.add_argument(
        "--auth",
        choices=["snowflake_sso", "azure_ad_oauth"],
        default="snowflake_sso",
    )
    args = parser.parse_args()

    if not args.sql.is_file():
        print(f"SQL file not found: {args.sql}", file=sys.stderr)
        sys.exit(1)

    from simple_agent_with_sso_auth import AUTH_AZURE_AD_OAUTH, AUTH_SNOWFLAKE_SSO, run_query_with_sso

    auth = AUTH_AZURE_AD_OAUTH if args.auth == "azure_ad_oauth" else AUTH_SNOWFLAKE_SSO
    run_query_with_sso(
        str(args.sql.resolve()),
        config_file=str(HERE / args.config),
        output_file=str(args.out.resolve()),
        user_email=args.user_email,
        environment=args.env,
        auth_method=auth,
    )


if __name__ == "__main__":
    main()
