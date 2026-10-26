"""Prepare an explicit curated demo seed; never copy .env or native archives."""

import json
import shutil
from pathlib import Path

from hosted_api import public_report
from hosted_settings import PROJECT
from run_pipeline import source_dataset


def prepare_seed(output: Path = PROJECT / "deployment" / "seed") -> None:
    historical = output / "historical"
    historical.mkdir(parents=True, exist_ok=True)
    source = source_dataset()
    shutil.copy2(source, historical / "hourly.csv")
    validation = json.loads((source.parent / "validation.json").read_text(encoding="utf-8"))
    validation = {
        key: validation.get(key)
        for key in ("status", "hourly_rows", "start_utc", "end_utc_exclusive", "created_utc")
    }
    validation["publication_vintages_verified"] = False
    (historical / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    # Explicitly select the reviewed seven-day example, never arbitrary private jobs.
    run_id = "20261024T170430888686Z_empirical_b972e4"
    source_run = PROJECT / "data" / "results" / run_id
    featured = output / "featured"
    featured.mkdir(exist_ok=True)
    report = public_report(json.loads((source_run / "results.json").read_text(encoding="utf-8")))
    report["run_id"] = "featured_historical"
    (featured / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name in (
        "forecasts.csv",
        "metrics.csv",
        "calibration.csv",
        "metrics_by_hour.csv",
        "battery_values.csv",
        "battery_summary.csv",
        "battery_dispatch.csv",
    ):
        shutil.copy2(source_run / name, featured / name)
    supplements = sorted(
        (PROJECT / "data" / "sensitivity").glob(run_id + "_*/sensitivity.csv"),
        key=lambda path: path.stat().st_mtime,
    )
    if supplements:
        shutil.copy2(supplements[-1], featured / "sensitivity.csv")
    print(f"Curated historical seed and featured results prepared: {output}")


if __name__ == "__main__":
    prepare_seed()
