"""Validate one complete download run and build hourly DE-LU tables.

python prepare_data.py --run-id 20261021T231249530385Z_af7e7839
Without --run-id, choose the newest successful run containing all three datasets.
"""

import argparse
import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parent
SCHEMAS = {
    "prices": {"price_eur_mwh": "price_eur_mwh"},
    "load": {"load_forecast_mw": "load_forecast_mw"},
    "wind_solar": {
        "Solar": "solar_forecast_mw",
        "Wind Offshore": "wind_offshore_forecast_mw",
        "Wind Onshore": "wind_onshore_forecast_mw",
    },
}
RESOLUTIONS = {"PT15M": 15, "PT30M": 30, "PT60M": 60, "PT1H": 60}


def read_json(path):
    """Read an archived manifest or metadata document as UTF-8 JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    """Create a new report without overwriting a previous run."""
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, indent=2)


def choose_run(downloads, run_id=None):
    """Select the requested complete download or the newest successful complete run."""
    candidates = [downloads / run_id] if run_id else sorted(downloads.glob("*"), reverse=True)
    for run in candidates:
        manifest_path = run / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = read_json(manifest_path)
        complete = manifest.get("status") == "success" and all(
            manifest.get("datasets", {}).get(name, {}).get("status") == "success"
            and (run / name / "native.csv").is_file()
            for name in SCHEMAS
        )
        if complete:
            return run, manifest
    raise ValueError(
        "No successful run with prices, load and wind_solar. Download all three together first."
    )


def source_resolution(run, dataset):
    """Use archived XML metadata, not the spacing between possibly missing rows."""
    resolutions, currencies, units = set(), set(), set()
    paths = list((run / dataset / "raw").glob("*.metadata.json"))
    for path in paths:
        metadata = read_json(path)
        if metadata.get("http_status") != 200:
            continue
        resolutions.update(metadata.get("resolutions", []))
        currencies.update(metadata.get("currency_units", []))
        units.update(metadata.get("measure_units", []))
    if not resolutions or not resolutions.issubset(RESOLUTIONS):
        raise ValueError(
            f"{dataset}: missing or unsupported raw resolution metadata: {sorted(resolutions)}"
        )
    minutes = {RESOLUTIONS[value] for value in resolutions}
    if len(minutes) != 1:
        raise ValueError(
            f"{dataset}: mixed resolutions. Prepare separate periods before combining them."
        )
    if dataset == "prices":
        if currencies != {"EUR"} or units != {"MWH"}:
            raise ValueError("Prices must have verified EUR/MWh source units")
    elif units != {"MAW"}:
        # IEC XML uses MAW to denote MW.
        raise ValueError(f"{dataset}: expected MAW (MW) in raw unit metadata, got {sorted(units)}")
    return minutes.pop(), paths


def validate_frame(frame, start, end, minutes):
    """Reject missing, extra, duplicate or nonfinite native observations before aggregation."""
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Delivery timestamps must have a timezone")
    if minutes not in (15, 30, 60):
        raise ValueError("Unsupported interval duration")
    frame = frame.copy()
    frame.index = frame.index.tz_convert("UTC")
    if frame.index.has_duplicates:
        raise ValueError("Duplicate delivery timestamps")
    frame = frame.sort_index()
    expected = pd.date_range(start, end, freq=f"{minutes}min", inclusive="left")
    missing = expected.difference(frame.index)
    extra = frame.index.difference(expected)
    if len(missing) or len(extra):
        raise ValueError(
            f"Incomplete/misaligned interval grid: {len(missing)} missing, {len(extra)} extra timestamps"
        )
    for column in frame:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if frame[column].isna().any() or not frame[column].map(math.isfinite).all():
            raise ValueError(f"Missing or nonfinite values in {column}")
        if column.endswith("_mw") and (frame[column] < 0).any():
            raise ValueError(f"Negative load/generation forecast in {column}")
    frame.index.name = "delivery_start_utc"
    return frame


def load_frame(path, dataset, start, end, minutes):
    """Load a native CSV, enforce its dataset schema and validate the delivery grid."""
    frame = pd.read_csv(path)
    schema = SCHEMAS[dataset]
    if set(frame.columns) != {"delivery_start_utc", *schema}:
        raise ValueError(f"Unexpected {dataset} columns: {list(frame.columns)}")
    # utc=True alone would silently interpret naive timestamps as UTC.
    times = frame.pop("delivery_start_utc")
    if not times.map(lambda value: pd.Timestamp(value).tzinfo is not None).all():
        raise ValueError("A source timestamp has no timezone")
    frame.index = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    return validate_frame(frame.rename(columns=schema), start, end, minutes)


def hourly_average(frame, start, end, minutes):
    """Average only complete native grids into UTC hours; never fill missing values."""
    frame = validate_frame(frame, start, end, minutes)
    # All intervals within each source are equal length, so the ordinary mean
    # equals the duration-weighted mean. Never sum MW or EUR/MWh values.
    grouped = frame.resample("h", closed="left", label="left")
    if not grouped.size().eq(60 // minutes).all():
        raise ValueError("An hour lacks complete interval coverage")
    return grouped.mean()


def prepare(run, manifest, processed):
    """Build a uniquely named hourly dataset with validation and source hashes."""
    if manifest.get("area") != "DE_LU":
        raise ValueError("Expected DE_LU area")
    start = pd.Timestamp(manifest["start_utc"])
    end = pd.Timestamp(manifest["end_utc_exclusive"])
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Manifest date boundaries must have timezones")
    start, end = start.tz_convert("UTC"), end.tz_convert("UTC")
    if end <= start or start != start.floor("h") or end != end.floor("h"):
        raise ValueError("Expected increasing whole-hour boundaries")
    expected_hours = pd.date_range(start, end, freq="h", inclusive="left")
    tables, report, input_files = [], {}, [run / "manifest.json"]
    for dataset in SCHEMAS:
        minutes, metadata_paths = source_resolution(run, dataset)
        path = run / dataset / "native.csv"
        frame = load_frame(path, dataset, start, end, minutes)
        hourly = hourly_average(frame, start, end, minutes)
        if not hourly.index.equals(expected_hours):
            raise ValueError(f"{dataset}: hourly grid differs from requested dates")
        tables.append(hourly)
        input_files.extend([path, *metadata_paths])
        report[dataset] = {
            "native_rows": len(frame),
            "source_interval_minutes": minutes,
            "hourly_rows": len(hourly),
        }
    # All indexes were checked against the same UTC grid; no join-by-row-number.
    result = pd.concat(tables, axis=1, join="outer")
    if result.isna().any().any():
        raise ValueError("Joining datasets introduced missing values")
    result.index.name = "delivery_start_utc"
    result.insert(0, "delivery_end_utc", result.index + pd.Timedelta(hours=1))
    result.insert(1, "duration_hours", 1.0)
    local = result.index.tz_convert("Europe/Berlin")
    result["delivery_start_local"] = [value.isoformat() for value in local]
    result["delivery_date_local"] = local.strftime("%Y-%m-%d")
    result["hour_local"] = local.hour
    result["utc_offset_minutes"] = [int(value.utcoffset().total_seconds() / 60) for value in local]
    destination = processed / (run.name + "_" + uuid.uuid4().hex[:8])
    destination.mkdir(parents=True)
    with (destination / "hourly.csv").open("x", encoding="utf-8", newline="") as file:
        result.to_csv(file)
    summary = {
        "status": "success",
        "source_run": str(run.resolve()),
        "start_utc": start.isoformat(),
        "end_utc_exclusive": end.isoformat(),
        "hourly_rows": len(result),
        "datasets": report,
        "local_day_row_counts": {
            str(key): int(value)
            for key, value in result.groupby("delivery_date_local").size().items()
        },
        "boundary_note": "A UTC date range can include partial local days. Repeated local clock hours remain distinct through UTC and explicit offsets.",
        "availability_note": "Forecast availability before the auction is NOT verified. Historical revisions may be present. Do not train until the information set is documented.",
        "hourly_price_note": "An hourly average of shorter-interval prices is a research target, not a separately traded hourly product price.",
        "imputation": "None. Incomplete grids or missing values fail validation.",
        "input_sha256": {
            str(path.relative_to(run)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in input_files
        },
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(destination / "validation.json", summary)
    return destination, summary


def main():
    """Parse preparation options and report validation failures clearly."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id", help="Download run folder name; default: newest complete successful run"
    )
    parser.add_argument("--data-dir", type=Path, default=PROJECT / "data")
    args = parser.parse_args()
    try:
        run, manifest = choose_run(args.data_dir / "downloads", args.run_id)
        destination, summary = prepare(run, manifest, args.data_dir / "processed")
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f"Preparation stopped: {error}")
        return 1
    print(f"Source run: {run.name}")
    for dataset, values in summary["datasets"].items():
        print(
            f"{dataset}: {values['native_rows']} native rows -> {values['hourly_rows']} hourly rows"
        )
    print(f"Saved {summary['hourly_rows']} hourly rows: {destination / 'hourly.csv'}")
    print(f"Validation report: {destination / 'validation.json'}")
    print(
        "Next: information-set/publication-time checks. This is not yet a leakage-verified training table."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
