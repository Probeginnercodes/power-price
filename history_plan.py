"""Plan and optionally download the longer history for a development backtest.

python history_plan.py             # show the plan only
python history_plan.py --download  # download, prepare and build candidate features
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parent


def make_plan(first_day="2026-10-15", end_day="2026-10-22"):
    """Calculate calendar-day training and lag warmup before the development period."""
    first = pd.Timestamp(first_day, tz="Europe/Berlin")
    end = pd.Timestamp(end_day, tz="Europe/Berlin")
    if first != first.normalize() or end != end.normalize() or end <= first:
        raise ValueError("Use increasing delivery dates at local midnight")
    train_start = first - pd.DateOffset(days=364)
    warmup_start = train_start - pd.DateOffset(days=7)
    return {
        "purpose": "Development backtest, NOT a final untouched test period; the sample has already been inspected.",
        "first_forecast_local_day": first_day,
        "evaluation_end_local_day_exclusive": end_day,
        "first_training_start_local_day": train_start.strftime("%Y-%m-%d"),
        "first_training_end_local_day_exclusive": first_day,
        "lag_warmup_start_local_day": warmup_start.strftime("%Y-%m-%d"),
        "rolling_training_calendar_days": 364,
        "lag_warmup_calendar_days": 7,
        "development_delivery_days": int((end.date() - first.date()).days),
        "download_start_utc": warmup_start.tz_convert("UTC").floor("D").strftime("%Y-%m-%d"),
        "download_end_utc_exclusive": end.tz_convert("UTC").ceil("D").strftime("%Y-%m-%d"),
        "limitations": [
            "Publication/vintage evidence is still unverified.",
            "The first backtest period is only seven days: insufficient for strong performance or DM significance claims.",
            "DST exclusions in the initial feature builder reduce usable observations; the final LEAR calendar policy must be explicit.",
            "This script prepares data only; it does not fit a model or certify forecasting validity.",
        ],
    }


def main():
    """Print the download plan and optionally execute its documented preparation steps."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    plan = make_plan()
    print(json.dumps(plan, indent=2), flush=True)
    if not args.download:
        print("Plan only. Add --download to fetch and prepare the historical data.")
        return 0
    plans = PROJECT / "data" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    plan_path = plans / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    with plan_path.open("x", encoding="utf-8") as file:
        json.dump(plan, file, indent=2)
    downloads = PROJECT / "data" / "downloads"
    before = {p.name for p in downloads.glob("*") if p.is_dir()}
    command = [
        sys.executable,
        str(PROJECT / "download_data.py"),
        "--start",
        plan["download_start_utc"],
        "--end",
        plan["download_end_utc_exclusive"],
        "--datasets",
        "prices",
        "load",
        "wind_solar",
    ]
    result = subprocess.run(command, cwd=PROJECT)
    if result.returncode:
        print(
            "Historical download failed. Raw responses/checkpoints are preserved. No model was fitted."
        )
        return result.returncode
    new_runs = [p for p in downloads.glob("*") if p.is_dir() and p.name not in before]
    if len(new_runs) != 1:
        raise ValueError(
            "Cannot identify a unique download run; inspect manifests before proceeding"
        )
    run = new_runs[0]
    prepared = subprocess.run(
        [sys.executable, str(PROJECT / "prepare_data.py"), "--run-id", run.name], cwd=PROJECT
    )
    if prepared.returncode:
        print(
            "Preparation failed. Do not bypass data validation. Inspect source units, gaps and resolution."
        )
        return prepared.returncode
    # Select the exact processed run, not an unrelated latest sample.
    matches = []
    for path in (PROJECT / "data" / "processed").glob("*/validation.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        if Path(report["source_run"]).resolve() == run.resolve() and report["status"] == "success":
            matches.append((report["created_utc"], path.parent))
    if not matches:
        raise ValueError("Prepared output not found")
    processed = max(matches, key=lambda item: item[0])[1]
    return subprocess.run(
        [sys.executable, str(PROJECT / "features.py"), "--processed-id", processed.name],
        cwd=PROJECT,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
