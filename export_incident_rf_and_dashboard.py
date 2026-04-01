"""
1) Run incident RF / Field Ops stale-notes extract → incident_rf_fieldops_stale_notes.csv
2) Start Streamlit dashboard (streamlit_incident_rf_stale.py)

Usage:
  .venv\\Scripts\\python.exe export_incident_rf_and_dashboard.py
  .venv\\Scripts\\python.exe export_incident_rf_and_dashboard.py --dashboard-only
  .venv\\Scripts\\python.exe export_incident_rf_and_dashboard.py --export-only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SQL = ROOT / "incident_rf_fieldops_switch_notes.sql"
CSV = ROOT / "incident_rf_fieldops_stale_notes.csv"
STREAMLIT_ENTRY = ROOT / "streamlit_incident_rf_stale.py"
EXPORT = ROOT / "export_incident_rf_stale_notes.py"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--export-only", action="store_true")
    p.add_argument("--dashboard-only", action="store_true")
    p.add_argument("--skip-export", action="store_true", help="Open dashboard only (reuse existing CSV)")
    args, passthrough = p.parse_known_args()

    if not args.dashboard_only and not args.skip_export:
        if not SQL.is_file():
            print(f"Missing SQL: {SQL}", file=sys.stderr)
            sys.exit(1)
        cmd = [
            sys.executable,
            str(EXPORT),
            "--sql-file",
            str(SQL),
            "--out",
            str(CSV),
            *passthrough,
        ]
        print("Running export… (complete browser SSO if prompted)\n", " ".join(cmd))
        r = subprocess.run(cmd, cwd=str(ROOT))
        if r.returncode != 0:
            sys.exit(r.returncode)
        if CSV.is_file():
            print(f"\n✓ CSV: {CSV} ({CSV.stat().st_size:,} bytes)\n")
        else:
            print(f"\n⚠ Expected CSV not found: {CSV}", file=sys.stderr)

    if args.export_only:
        return

    if not STREAMLIT_ENTRY.is_file():
        print(f"Missing {STREAMLIT_ENTRY}", file=sys.stderr)
        sys.exit(1)
    print("Starting Streamlit…\n")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(STREAMLIT_ENTRY)],
        cwd=str(ROOT),
    )


if __name__ == "__main__":
    main()
