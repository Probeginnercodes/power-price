"""Build candidate model inputs; publication evidence remains unverified.

Price lags use the same Berlin clock hour on prior LOCAL delivery days.
This initial policy excludes incomplete and 23/25-hour local days, including lag
source days. It never resolves repeated hours by silently picking one.
"""

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from information_set import cutoff_for_day

PROJECT = Path(__file__).resolve().parent
LAGS = (1, 2, 3, 7)
FORECAST_COLUMNS = [
    "load_forecast_mw",
    "solar_forecast_mw",
    "wind_offshore_forecast_mw",
    "wind_onshore_forecast_mw",
]
INPUT_COLUMNS = (
    [f"price_lag_{lag}d" for lag in LAGS]
    + FORECAST_COLUMNS
    + ["hour_local", "weekday_local", "is_weekend"]
)
TARGET_COLUMN = "target_price_eur_mwh"


def build_features(hourly, cutoff_local="11:00"):
    """Build auditable candidate same-hour lags with explicit source timestamps and exclusions."""
    required = ["delivery_start_utc", "price_eur_mwh", *FORECAST_COLUMNS]
    if not set(required).issubset(hourly.columns):
        raise ValueError(f"Missing required columns: {sorted(set(required) - set(hourly.columns))}")
    source = hourly[required].copy()
    if not source["delivery_start_utc"].map(lambda x: pd.Timestamp(x).tzinfo is not None).all():
        raise ValueError("Delivery timestamps require explicit timezones")
    source.index = pd.DatetimeIndex(pd.to_datetime(source.pop("delivery_start_utc"), utc=True))
    if source.index.has_duplicates or source.index.hasnans:
        raise ValueError("Duplicate or invalid delivery timestamps")
    source = source.sort_index()
    if not source.index.equals(source.index.floor("h")):
        raise ValueError("Expected whole-hour UTC observations")
    for column in source:
        source[column] = pd.to_numeric(source[column], errors="raise")
        if source[column].isna().any() or not source[column].map(math.isfinite).all():
            raise ValueError(f"Missing/nonfinite source values: {column}")
    local = source.index.tz_convert("Europe/Berlin")
    source["_day"] = local.strftime("%Y-%m-%d")
    source["_hour"] = local.hour
    valid_days = {}
    day_data = {}
    day_quality = []
    for day, group in source.groupby("_day"):
        start = pd.Timestamp(day, tz="Europe/Berlin")
        end = start + pd.DateOffset(days=1)
        expected_hours = int(
            (end.tz_convert("UTC") - start.tz_convert("UTC")).total_seconds() / 3600
        )
        expected_index = pd.date_range(
            start.tz_convert("UTC"), end.tz_convert("UTC"), freq="h", inclusive="left"
        )
        complete = group.index.equals(expected_index)
        supported = expected_hours == 24
        valid_days[day] = complete and supported
        day_data[day] = group
        day_quality.append(
            {
                "delivery_date_local": day,
                "observed_hours": len(group),
                "expected_hours": expected_hours,
                "complete": complete,
                "supported_by_initial_lag_policy": supported,
            }
        )
    records = []
    for stamp, row in source.iterrows():
        day, hour = row["_day"], int(row["_hour"])
        local_stamp = stamp.tz_convert("Europe/Berlin")
        record = {
            "delivery_start_utc": stamp.isoformat(),
            "delivery_date_local": day,
            "forecast_cutoff_utc": cutoff_for_day(day, cutoff_local).isoformat(),
            TARGET_COLUMN: row["price_eur_mwh"],
            **{name: row[name] for name in FORECAST_COLUMNS},
            "hour_local": hour,
            "weekday_local": local_stamp.weekday(),
            "is_weekend": int(local_stamp.weekday() >= 5),
        }
        reasons = []
        if not valid_days[day]:
            reasons.append("target_day_incomplete_or_dst")
        for lag in LAGS:
            lag_day = (date.fromisoformat(day) - timedelta(days=lag)).isoformat()
            record[f"price_lag_{lag}d"] = None
            record[f"lag_{lag}d_source_delivery_start_utc"] = None
            if not valid_days.get(lag_day, False):
                reasons.append(f"lag_{lag}d_day_missing_incomplete_or_dst")
                continue
            matching = day_data[lag_day].loc[day_data[lag_day]["_hour"] == hour]
            if len(matching) != 1:
                raise ValueError("Ambiguous local-hour price lag")
            record[f"price_lag_{lag}d"] = float(matching["price_eur_mwh"].iloc[0])
            record[f"lag_{lag}d_source_delivery_start_utc"] = matching.index[0].isoformat()
        record["history_complete"] = not reasons
        record["exclusion_reasons"] = "|".join(reasons)
        # Downloaded vintage publication times are not known; never invent them.
        record["forecast_vintage_verified"] = False
        records.append(record)
    if not records:
        raise ValueError("No hourly observations")
    return pd.DataFrame(records), day_quality


def choose_source(data, processed_id):
    """Select an explicit processed run or the largest validated hourly history."""
    folders = (
        [data / "processed" / processed_id] if processed_id else (data / "processed").glob("*")
    )
    choices = []
    for folder in folders:
        if (folder / "validation.json").is_file() and (folder / "hourly.csv").is_file():
            report = json.loads((folder / "validation.json").read_text(encoding="utf-8"))
            if report.get("status") == "success":
                choices.append((report.get("created_utc", ""), folder))
    if not choices:
        raise ValueError("No successful prepared dataset")
    return max(choices, key=lambda item: item[0])[1]


def main():
    """Export educational candidate features, lineage and training-readiness diagnostics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT / "data")
    parser.add_argument("--processed-id")
    parser.add_argument(
        "--cutoff-local",
        default="11:00",
        help="D-1 Berlin research cutoff; market deadline not verified",
    )
    args = parser.parse_args()
    source = choose_source(args.data_dir, args.processed_id)
    original = source / "hourly.csv"
    candidates, day_quality = build_features(pd.read_csv(original), args.cutoff_local)
    complete = candidates.loc[candidates["history_complete"]].copy()
    output = args.data_dir / "features" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True)
    candidates.to_csv(output / "candidate_features.csv", index=False, mode="x")
    complete.to_csv(output / "history_complete_candidates.csv", index=False, mode="x")
    pd.DataFrame(day_quality).to_csv(output / "local_day_quality.csv", index=False, mode="x")
    report = {
        "source_processed": str(source.resolve()),
        "source_hourly_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "candidate_rows": len(candidates),
        "history_complete_rows": len(complete),
        "input_columns": INPUT_COLUMNS,
        "target_column": TARGET_COLUMN,
        "training_ready": False,
        "cutoff_policy": f"D-1 at {args.cutoff_local} Europe/Berlin; research assumption.",
        "lag_policy": "Same local hour on delivery days D-1, D-2, D-3, D-7. Require complete 24-hour target/source days; DST days are flagged and excluded in this initial version.",
        "limitations": [
            "Forecast vintages and actual availability remain unverified.",
            "Source delivery timestamps are lineage, not publication timestamps.",
            "A week cannot supply seven-day lag history for its own observations.",
            "These are initial candidate features, not a claim to replicate the full published LEAR feature specification.",
            "No transformations, imputation, model fitting or evaluation is performed.",
        ],
        "next_step": "Resolve availability assumptions and obtain a longer history with training, lag warm-up and evaluation periods.",
    }
    with (output / "report.json").open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
    print(f"Candidate rows: {len(candidates)}")
    print(f"Rows with complete lag history: {len(complete)}")
    print(f"Saved feature tables: {output}")
    if complete.empty:
        print(
            "Expected for a one-week sample: seven-day lag history is unavailable. No history was fabricated."
        )
    print(
        "Training readiness: NOT VERIFIED. Review forecast-vintage evidence before a leakage-verified backtest."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Feature preparation stopped: {error}")
        raise SystemExit(1) from error
