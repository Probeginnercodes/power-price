"""Document the information set; do not invent historical publication times."""

import argparse
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parent
FORECASTS = [
    "load_forecast_mw",
    "solar_forecast_mw",
    "wind_offshore_forecast_mw",
    "wind_onshore_forecast_mw",
]


def cutoff_for_day(day, clock="11:00"):
    """Convert the assumed previous-day Berlin research cutoff to an aware UTC instant."""
    previous = date.fromisoformat(str(day)) - timedelta(days=1)
    local = pd.Timestamp(datetime.combine(previous, time.fromisoformat(clock)))
    return local.tz_localize("Europe/Berlin", ambiguous="raise", nonexistent="raise").tz_convert(
        "UTC"
    )


def check_availability(available_at, cutoff, vintage_verified=False):
    """Require verified publication evidence strictly before the cutoff; otherwise flag it."""
    if available_at is None or not vintage_verified:
        return "unverified"
    available, cutoff = pd.Timestamp(available_at), pd.Timestamp(cutoff)
    if available.tzinfo is None or cutoff.tzinfo is None:
        raise ValueError("Publication and cutoff timestamps require timezones")
    return "available" if available < cutoff else "too_late"


def main():
    """Write the feature information-set table and audit without inventing publication times."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT / "data")
    parser.add_argument("--processed-id")
    parser.add_argument(
        "--cutoff-local",
        default="11:00",
        help="D-1 Berlin time: research assumption, not a verified auction deadline",
    )
    args = parser.parse_args()
    candidates = []
    folders = (
        [args.data_dir / "processed" / args.processed_id]
        if args.processed_id
        else (args.data_dir / "processed").glob("*")
    )
    for folder in folders:
        if not (folder / "validation.json").is_file() or not (folder / "hourly.csv").is_file():
            continue
        validation = json.loads((folder / "validation.json").read_text(encoding="utf-8"))
        if validation.get("status") == "success":
            candidates.append((validation.get("created_utc", ""), folder, validation))
    if not candidates:
        raise ValueError("No successful processed dataset; run prepare_data.py first")
    _, source, validation = max(candidates, key=lambda item: item[0])
    frame = pd.read_csv(source / "hourly.csv")
    stamps = pd.to_datetime(frame["delivery_start_utc"], utc=True)
    if stamps.duplicated().any():
        raise ValueError("Duplicate delivery timestamps")
    local = stamps.dt.tz_convert("Europe/Berlin")
    days = local.dt.strftime("%Y-%m-%d")
    definitions = [
        {
            "feature": "price_eur_mwh",
            "role": "target_only",
            "rule": "Target-day prices cannot be forecast inputs.",
        },
        *[
            {
                "feature": f,
                "role": "candidate_input",
                "rule": "Exact vintage must be published before cutoff; NOT VERIFIED.",
            }
            for f in FORECASTS
        ],
        {
            "feature": "hour_local",
            "role": "known_input",
            "rule": "Known calendar; preserve UTC offset for repeated hours.",
        },
        {
            "feature": "delivery_date_local",
            "role": "known_input",
            "rule": "Known delivery calendar date.",
        },
        {
            "feature": "price_lags_1_2_3_7_days",
            "role": "planned_not_built",
            "rule": "Use local-day alignment and verify historical price availability.",
        },
    ]
    audit = []
    for stamp, day in zip(stamps, days, strict=True):
        cutoff = cutoff_for_day(day, args.cutoff_local)
        for feature in FORECASTS:
            if feature not in frame:
                raise ValueError(f"Missing feature: {feature}")
            audit.append(
                {
                    "delivery_start_utc": stamp.isoformat(),
                    "feature": feature,
                    "forecast_cutoff_utc": cutoff.isoformat(),
                    "available_at_utc": None,
                    "availability": check_availability(None, cutoff),
                }
            )
    boundaries = []
    for day in sorted(set(days)):
        start = pd.Timestamp(day, tz="Europe/Berlin")
        end = start + pd.DateOffset(days=1)
        expected = int((end.tz_convert("UTC") - start.tz_convert("UTC")).total_seconds() / 3600)
        observed = int((days == day).sum())
        cutoff = cutoff_for_day(day, args.cutoff_local)
        boundaries.append(
            {
                "delivery_date_local": day,
                "cutoff_utc": cutoff.isoformat(),
                "cutoff_local": cutoff.tz_convert("Europe/Berlin").isoformat(),
                "observed_hours": observed,
                "expected_hours": expected,
                "complete_local_day": observed == expected,
            }
        )
    metadata_records = []
    raw_run = Path(validation["source_run"])
    for dataset in ("prices", "load", "wind_solar"):
        for path in sorted((raw_run / dataset / "raw").glob("*.metadata.json")):
            metadata = json.loads(path.read_text(encoding="utf-8"))
            metadata_records.append(
                {
                    "dataset": dataset,
                    "file": str(path.relative_to(raw_run)),
                    "document_created_utc": metadata.get("document_created_utc"),
                    "document_revision": metadata.get("document_revision"),
                    "received_utc": metadata.get("received_utc"),
                }
            )
    output = (
        args.data_dir / "information_set" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output.mkdir(parents=True)
    pd.DataFrame(definitions).to_csv(output / "feature_definitions.csv", index=False, mode="x")
    pd.DataFrame(audit).to_csv(output / "availability_audit.csv", index=False, mode="x")
    pd.DataFrame(boundaries).to_csv(output / "delivery_day_cutoffs.csv", index=False, mode="x")
    report = {
        "status": "unverified_forecast_vintages",
        "ready_for_leakage_verified_training": False,
        "source_processed": str(source.resolve()),
        "hourly_rows": len(frame),
        "hourly_sha256": hashlib.sha256((source / "hourly.csv").read_bytes()).hexdigest(),
        "cutoff_policy": f"D-1 at {args.cutoff_local} Europe/Berlin. Research assumption; verify market rules.",
        "unverified_feature_rows": len(audit),
        "source_document_metadata": metadata_records,
        "complete_local_days": sum(b["complete_local_day"] for b in boundaries),
        "partial_local_days": [
            b["delivery_date_local"] for b in boundaries if not b["complete_local_day"]
        ],
        "limitations": [
            "Retrieval and document creation times do not prove original forecast publication.",
            "No publication times are fabricated; exact-vintage evidence is required.",
            "Price lag features are not built yet.",
            "Exclude partial local days before daily evaluation.",
        ],
        "next_steps": [
            "Review publication evidence for exact forecast vintages.",
            "Document final cutoff policy.",
            "Obtain enough history for 364 training days, seven-day lags and separate evaluation.",
        ],
    }
    with (output / "report.json").open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
    print(f"Audited {len(frame)} hourly rows from {source.name}")
    print(
        f"Complete local days: {report['complete_local_days']}; partial days: {report['partial_local_days']}"
    )
    print(f"Information-set tables and report: {output}")
    print("Training gate: UNVERIFIED. Publication/vintage evidence still needs review.")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f"Information-set audit stopped: {error}")
        raise SystemExit(1) from error
