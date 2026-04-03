"""
Export Incident Open Backlog data from Snowflake to CSV.

Usage:
  python export_incident_open_backlog.py
  python export_incident_open_backlog.py --env PROD
  python export_incident_open_backlog.py --dashboard
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
SQL_FILE = ROOT / "incident_open_backlog.sql"
CSV_FILE = ROOT / "incident_open_backlog.csv"
AGENT = ROOT / "simple_agent_with_sso_auth.py"
DASHBOARD = ROOT / "app_incident_open_backlog.py"


def export_data(env: str = "PROD") -> bool:
    """Run SQL export via SSO agent."""
    if not SQL_FILE.is_file():
        print(f"ERROR: SQL file not found: {SQL_FILE}", file=sys.stderr)
        return False
    
    if not AGENT.is_file():
        print(f"ERROR: SSO agent not found: {AGENT}", file=sys.stderr)
        return False
    
    cmd = [
        sys.executable,
        str(AGENT),
        str(SQL_FILE),
        str(CSV_FILE),
        "--env", env,
    ]
    
    print(f"\n{'='*60}")
    print("Exporting Incident Open Backlog Data")
    print(f"{'='*60}")
    print(f"SQL: {SQL_FILE.name}")
    print(f"Output: {CSV_FILE.name}")
    print(f"Environment: {env}")
    print(f"{'='*60}\n")
    print("Running export... (complete browser SSO if prompted)\n")
    
    result = subprocess.run(cmd, cwd=str(ROOT))
    
    if result.returncode == 0 and CSV_FILE.is_file():
        size_mb = CSV_FILE.stat().st_size / (1024 * 1024)
        print(f"\n{'='*60}")
        print(f"SUCCESS: CSV exported")
        print(f"File: {CSV_FILE}")
        print(f"Size: {size_mb:.2f} MB")
        print(f"{'='*60}\n")
        return True
    else:
        print(f"\nERROR: Export failed with return code {result.returncode}", file=sys.stderr)
        return False


def launch_dashboard() -> None:
    """Launch the Streamlit dashboard."""
    if not DASHBOARD.is_file():
        print(f"ERROR: Dashboard not found: {DASHBOARD}", file=sys.stderr)
        sys.exit(1)
    
    print(f"\nStarting Streamlit dashboard: {DASHBOARD.name}\n")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(DASHBOARD)],
        cwd=str(ROOT),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Incident Open Backlog data")
    parser.add_argument("--env", "-e", default="PROD", choices=["DEV", "QAT", "PROD"],
                        help="Snowflake environment (default: PROD)")
    parser.add_argument("--dashboard", "-d", action="store_true",
                        help="Launch Streamlit dashboard after export")
    parser.add_argument("--dashboard-only", action="store_true",
                        help="Skip export, just launch dashboard")
    parser.add_argument("--export-only", action="store_true",
                        help="Export only, don't launch dashboard")
    
    args = parser.parse_args()
    
    if not args.dashboard_only:
        success = export_data(args.env)
        if not success and not args.export_only:
            sys.exit(1)
    
    if args.dashboard or args.dashboard_only:
        if not args.export_only:
            launch_dashboard()


if __name__ == "__main__":
    main()
