"""Explicit historical preparation policy: exclude incomplete HOURS, never fill.

The original prepare_data.py remains strict. Every removed interval is reported.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from prepare_data import SCHEMAS, source_resolution

PROJECT = Path(__file__).resolve().parent


def complete_hour_means(frame, minutes, start, end):
    """Return hourly means only where every native interval is present in each column."""
    expected = pd.date_range(start, end, freq=f"{minutes}min", inclusive="left")
    if frame.index.has_duplicates:
        raise ValueError("Duplicate native timestamps")
    if len(frame.index.difference(expected)):
        raise ValueError("Unexpected native timestamps")
    frame = frame.reindex(expected)
    counts = frame.resample("h").count()
    return frame.resample("h").mean().where(counts == 60 // minutes)


def main():
    """Prepare historical hours under the explicit exclusion policy and archive exclusions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run = PROJECT / "data" / "downloads" / args.run_id
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "success" or manifest.get("area") != "DE_LU":
        raise ValueError("Require successful DE-LU download")
    start = pd.Timestamp(manifest["start_utc"])
    end = pd.Timestamp(manifest["end_utc_exclusive"])
    tables = []
    inputs = [run / "manifest.json"]
    diagnostics = {}
    for dataset, schema in SCHEMAS.items():
        minutes, metadata = source_resolution(run, dataset)
        path = run / dataset / "native.csv"
        inputs.extend([path, *metadata])
        frame = pd.read_csv(path)
        if set(frame.columns) != {"delivery_start_utc", *schema}:
            raise ValueError("Unexpected source schema")
        stamps = frame.pop("delivery_start_utc")
        if not stamps.map(lambda x: pd.Timestamp(x).tzinfo is not None).all():
            raise ValueError("Naive timestamps")
        frame.index = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True))
        frame = frame.rename(columns=schema)
        frame = frame.apply(pd.to_numeric, errors="raise")
        if np.isinf(frame.to_numpy()).any():
            raise ValueError("Infinite source value")
        for column in frame:
            if column.endswith("_mw") and (frame[column].dropna() < 0).any():
                raise ValueError("Negative power forecast")
        hourly = complete_hour_means(frame, minutes, start, end)
        diagnostics[dataset] = {
            "native_rows": len(frame),
            "native_missing_values": {k: int(v) for k, v in frame.isna().sum().items()},
            "resolution_minutes": minutes,
        }
        tables.append(hourly)
    combined = pd.concat(tables, axis=1)
    bad = combined.isna().any(axis=1)
    excluded = pd.DataFrame(
        {
            "delivery_start_utc": combined.index[bad],
            "missing_columns": [
                ",".join(combined.columns[row.isna()]) for _, row in combined.loc[bad].iterrows()
            ],
        }
    )
    clean = combined.loc[~bad].copy()
    if clean.empty:
        raise ValueError("No complete hourly observations")
    clean.index.name = "delivery_start_utc"
    clean.insert(0, "delivery_end_utc", clean.index + pd.Timedelta(hours=1))
    clean.insert(1, "duration_hours", 1.0)
    local = clean.index.tz_convert("Europe/Berlin")
    clean["delivery_start_local"] = [t.isoformat() for t in local]
    clean["delivery_date_local"] = local.strftime("%Y-%m-%d")
    clean["hour_local"] = local.hour
    clean["utc_offset_minutes"] = [int(t.utcoffset().total_seconds() / 60) for t in local]
    out = (
        PROJECT
        / "data"
        / "processed"
        / (run.name + "_completehours_" + datetime.now(timezone.utc).strftime("%H%M%S%f"))
    )
    out.mkdir(parents=True)
    clean.to_csv(out / "hourly.csv", mode="x")
    excluded.to_csv(out / "excluded_hours.csv", index=False, mode="x")
    report = {
        "status": "success",
        "source_run": str(run.resolve()),
        "start_utc": start.isoformat(),
        "end_utc_exclusive": end.isoformat(),
        "hourly_rows": len(clean),
        "expected_hourly_rows": len(combined),
        "excluded_hour_count": int(bad.sum()),
        "datasets": diagnostics,
        "processing_policy": "EXCLUDE incomplete hours and record them; no imputation. Modelling must exclude incomplete local days and affected lags.",
        "availability_note": "Forecast vintages remain unverified; no leakage-free certification.",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": {
            str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs
        },
    }
    (out / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"Historical hourly rows: {len(clean)}; excluded incomplete hours: {bad.sum()}. Output: {out}",
        flush=True,
    )


if __name__ == "__main__":
    main()
