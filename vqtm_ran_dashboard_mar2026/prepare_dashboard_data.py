"""
Stream the large Snowflake export and produce:
  - summary.json  — aggregates (safe to commit)
  - sample.csv    — reservoir sample of SAMPLE_SIZE rows for charts/table

Usage (from repo root or this folder):
  python prepare_dashboard_data.py [path/to/vqtm_ran_avail_from_20260320.csv]
"""
from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

SAMPLE_SIZE = 8000
DEFAULT_INPUT = Path(
    r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR"
    r"\query_execution_agent_sso_auth 5\query_execution_agent_sso_auth"
    r"\vqtm_ran_avail_from_20260320.csv"
)

HERE = Path(__file__).resolve().parent


def num(s: str, default: float = 0.0) -> float:
    if s is None or str(s).strip() == "":
        return default
    try:
        return float(s)
    except ValueError:
        return default


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    if not src.is_file():
        print(f"Input not found: {src}")
        sys.exit(1)

    out_summary = HERE / "summary.json"
    out_sample = HERE / "sample.csv"

    region_c: Counter[str] = Counter()
    vendor_c: Counter[str] = Counter()
    market_c: Counter[str] = Counter()
    sites: set[str] = set()

    rows_total = 0
    lte_down_pos = 0
    fg_down_pos = 0
    sum_lte_d = 0.0
    sum_5g_d = 0.0
    min_period: str | None = None
    max_period: str | None = None

    reservoir: list[dict] = []
    rng = random.Random(42)

    with src.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            print("CSV has no header")
            sys.exit(1)

        for row in reader:
            rows_total += 1
            i = rows_total  # 1-based count for reservoir
            site = (row.get("SITE_ID") or "").strip()
            if site:
                sites.add(site)

            region_c[(row.get("REGION_ID") or "—").strip()] += 1
            vendor_c[(row.get("VENDOR") or "—").strip()] += 1
            market_c[(row.get("MARKET_ID") or "—").strip()] += 1

            lte_d = num(row.get("TOTAL_DOWNTIME_LTE"))
            g5_d = num(row.get("TOTAL_DOWNTIME_5G"))
            sum_lte_d += lte_d
            sum_5g_d += g5_d
            if lte_d > 0:
                lte_down_pos += 1
            if g5_d > 0:
                fg_down_pos += 1

            pst = (row.get("PERIOD_START_TIME") or "").strip()
            if pst:
                if min_period is None or pst < min_period:
                    min_period = pst
                if max_period is None or pst > max_period:
                    max_period = pst

            if i <= SAMPLE_SIZE:
                reservoir.append(row)
            else:
                j = rng.randint(1, i)
                if j <= SAMPLE_SIZE:
                    reservoir[j - 1] = row

            if rows_total % 200_000 == 0:
                print(f"  scanned {rows_total:,} rows…")

    # Enrich sample rows with derived pct for dashboard
    for r in reservoir:
        tt_lte = num(r.get("TOTAL_TIME_LTE"))
        tt_5g = num(r.get("TOTAL_TIME_5G"))
        r["_lte_pct"] = (
            round(100 * num(r.get("TOTAL_AVAIL_TIME_LTE")) / tt_lte, 4)
            if tt_lte > 0
            else None
        )
        r["_5g_pct"] = (
            round(100 * num(r.get("TOTAL_AVAIL_TIME_5G")) / tt_5g, 4)
            if tt_5g > 0
            else None
        )

    summary = {
        "source_file": src.name,
        "total_rows": rows_total,
        "unique_sites": len(sites),
        "period_start_min": min_period,
        "period_start_max": max_period,
        "rows_lte_downtime_gt0": lte_down_pos,
        "rows_5g_downtime_gt0": fg_down_pos,
        "sum_total_downtime_lte": round(sum_lte_d, 2),
        "sum_total_downtime_5g": round(sum_5g_d, 2),
        "by_region": dict(region_c.most_common(50)),
        "by_vendor": dict(vendor_c.most_common(20)),
        "top_markets": dict(market_c.most_common(30)),
        "sample_size": len(reservoir),
        "sample_note": f"Random reservoir sample of {SAMPLE_SIZE} rows for visualization; totals above are from full extract.",
    }

    out_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {out_summary}")

    if not reservoir:
        print("No rows sampled")
        sys.exit(1)

    keys = list(dict.fromkeys(k for r in reservoir for k in r.keys()))
    with out_sample.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(reservoir)
    print(f"Wrote {out_sample} ({len(reservoir)} rows)")


if __name__ == "__main__":
    main()
