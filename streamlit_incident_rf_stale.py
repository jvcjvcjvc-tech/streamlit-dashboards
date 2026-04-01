"""
Streamlit Community Cloud entrypoint for the RF / Field Ops stale-notes dashboard.

Deploy settings:
  Main file: streamlit_incident_rf_stale.py
  Python 3.11 (or 3.10+)

Locally:
  streamlit run streamlit_incident_rf_stale.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_and_run() -> None:
    path = Path(__file__).resolve().parent / "pages" / "1_Incident_RF_FieldOps_Stale.py"
    spec = importlib.util.spec_from_file_location("incident_rf_fieldops_stale_page", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load dashboard module: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


_load_and_run()
