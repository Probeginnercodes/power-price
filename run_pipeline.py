"""Run the reduced research pipeline. Demo mode is synthetic, never market evidence."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from battery import value_forecasts
from configuration import load_config
from evaluation import evaluate
from models import design_table, forecast_day
from research_audit import export_trial_ledger
from sensitivity import write_sensitivity
from synthetic_data import generate_hourly

PROJECT = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("POWER_DATA_DIR", PROJECT / "data"))


def json_safe(value):
    """Convert NumPy scalars and nonfinite values into strict JSON-safe values."""
    if isinstance(value, dict):
        return {str(k): json_safe(candidate) for k, candidate in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(candidate) for candidate in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def source_dataset(processed_id: str | None = None) -> Path:
    """Select an explicit run or the largest validated history, breaking ties by creation time."""
    if processed_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]+", processed_id):
        raise ValueError("Invalid processed run identifier")
    folders = (
        [DATA_ROOT / "processed" / processed_id]
        if processed_id
        else (DATA_ROOT / "processed").glob("*")
    )
    dataset_candidates = []
    for folder in folders:
        if (folder / "validation.json").is_file() and (folder / "hourly.csv").is_file():
            validation_report = json.loads((folder / "validation.json").read_text(encoding="utf-8"))
            if validation_report.get("status") == "success":
                dataset_candidates.append(
                    (
                        validation_report.get("hourly_rows", 0),
                        validation_report.get("created_utc", ""),
                        folder,
                    )
                )
    if not dataset_candidates:
        raise ValueError("No prepared hourly data. Run download_data.py and prepare_data.py first.")
    return (
        max(dataset_candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]
        / "hourly.csv"
    )


def _rolling_forecasts(design, feature_columns, evaluation_dates, config, output):
    """Refit each delivery day on the trailing calendar window and checkpoint it.

    Exclusions can reduce usable observations; the existing minimum-history
    policy is explicit here rather than silently shortening the requested window.
    """
    training_days = config["training_days"]
    forecasts = []
    diagnostics = []
    for day in evaluation_dates:
        training_start_date = (pd.Timestamp(day) - pd.DateOffset(days=training_days)).strftime(
            "%Y-%m-%d"
        )
        training = design.loc[
            (design.delivery_date_local >= training_start_date) & (design.delivery_date_local < day)
        ]
        forecast_rows = design.loc[design.delivery_date_local == day]
        if training.delivery_date_local.nunique() < max(60, training_days - 25):
            raise ValueError(f"{day}: too few training days after lag/DST exclusions")
        print(
            f"Forecasting {day}: {len(training)} training hours; {training.delivery_date_local.nunique()} usable local days in {training_days}-day window",
            flush=True,
        )
        prediction, daily_diagnostic = forecast_day(
            training, forecast_rows, feature_columns, config, output / "models" / day
        )
        forecasts.append(prediction)
        diagnostics.append(daily_diagnostic)
        pd.concat(forecasts, ignore_index=True).to_csv(
            output / "forecasts_checkpoint.csv", index=False
        )
    predictions = pd.concat(forecasts, ignore_index=True)
    return predictions, diagnostics


def _write_result_tables(
    output, predictions, metrics, calibration, hourly_metrics, battery_values, schedules
):
    """Persist stable CSV contracts and calculate period-total capture fractions."""
    for name, frame in [
        ("forecasts", predictions),
        ("metrics", metrics),
        ("calibration", calibration),
        ("metrics_by_hour", hourly_metrics),
        ("battery_values", battery_values),
        ("battery_dispatch", schedules),
    ]:
        frame.to_csv(output / f"{name}.csv", index=False)
    battery_summary = (
        battery_values.groupby("model")[["gross_eur", "cost_eur", "net_eur"]].sum().reset_index()
    )
    perfect_foresight_net_eur = float(
        battery_summary.loc[battery_summary.model == "perfect_foresight", "net_eur"].iloc[0]
    )
    battery_summary["capture_fraction"] = (
        battery_summary.net_eur / perfect_foresight_net_eur
        if perfect_foresight_net_eur > 1e-6
        else np.nan
    )
    battery_summary.to_csv(output / "battery_summary.csv", index=False)
    return battery_summary


def run(
    mode: str = "demo",
    evaluation_days: int = 7,
    training_days: int = 364,
    acknowledge: bool = False,
    processed_id: str | None = None,
    require_verified_vintages: bool = False,
) -> Path:
    """Orchestrate one auditable run; mark failures and preserve their traceback.

    Public CLI arguments and result schemas remain compatible with earlier runs.
    Raw downloads and existing result directories are never modified.
    """
    config = load_config(
        PROJECT / "config.json", training_days=training_days, evaluation_days=evaluation_days
    )
    if mode not in ("demo", "empirical"):
        raise ValueError("Unknown mode")
    if mode == "empirical" and not acknowledge:
        raise ValueError(
            "Historical forecast vintages are unverified. Explicit acknowledgement is required for an exploratory empirical run."
        )
    # The acknowledgement permits exploration; it never supplies publication evidence.
    # Strict research runs fail closed until original forecast vintages can be proved.
    if mode == "empirical" and require_verified_vintages:
        raise ValueError(
            "Verified research run blocked: original forecast-vintage evidence is unavailable. Use exploratory mode only; acknowledgement cannot certify timing."
        )
    output = (
        DATA_ROOT
        / "results"
        / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            + "_"
            + mode
            + "_"
            + uuid.uuid4().hex[:6]
        )
    )
    output.mkdir(parents=True)
    manifest = {
        "status": "running",
        "mode": mode,
        "config": config,
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    (output / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    try:
        if mode == "demo":
            hourly = generate_hourly(
                config["seed"], days=max(410, training_days + evaluation_days + 35)
            )
            source = output / "synthetic_hourly.csv"
            hourly.to_csv(source, index=False)
        else:
            source = source_dataset(processed_id)
            hourly = pd.read_csv(source)
        print(f"Mode: {mode}. Data: {source}", flush=True)
        design, feature_columns, design_report = design_table(hourly)
        delivery_days = sorted(design.delivery_date_local.unique())
        if len(delivery_days) < training_days // 2 + evaluation_days:
            raise ValueError(
                "Not enough usable history. Complete the longer historical download first."
            )
        evaluation_dates = delivery_days[-evaluation_days:]
        predictions, diagnostics = _rolling_forecasts(
            design, feature_columns, evaluation_dates, config, output
        )
        metrics, calibration, hourly_metrics, dm_result = evaluate(predictions)
        print("Forecast evaluation complete. Optimising battery schedules...", flush=True)
        battery_values, schedules = value_forecasts(predictions, config["battery"])
        battery_summary = _write_result_tables(
            output, predictions, metrics, calibration, hourly_metrics, battery_values, schedules
        )
        print("Evaluating declared battery sensitivity scenarios...", flush=True)
        sensitivity = write_sensitivity(predictions, config["battery"], output)
        feature_importance = pd.DataFrame(diagnostics[-1]["feature_importance_gain"]).sort_values(
            "gain", ascending=False
        )
        report = {
            "status": "success",
            "mode": mode,
            "run_id": output.name,
            "data_label": "SYNTHETIC DEMONSTRATION — not empirical evidence"
            if mode == "demo"
            else "EXPLORATORY HISTORICAL DATA — forecast vintages unverified",
            "publication_vintages_verified": False if mode == "empirical" else None,
            "source_file": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "config": config,
            "forecast_hours": len(predictions),
            "forecast_days": evaluation_dates,
            "metrics": metrics.to_dict("records"),
            "calibration": calibration.to_dict("records"),
            "dm_test": dm_result,
            "sensitivity": sensitivity.where(pd.notna(sensitivity), None).to_dict("records"),
            "research_readiness": {
                "final_holdout": False,
                "publication_evidence_verified": False,
                "question_recorded_before_data": False,
                "trial_history_complete": False,
                "inference_permitted": False,
                "reason": "Development period already inspected; historical vintages and pre-archive trial count unverified.",
            },
            "battery_summary": battery_summary.to_dict("records"),
            "design_report": design_report,
            "daily_diagnostics": diagnostics,
            "feature_importance": feature_importance.head(15).to_dict("records"),
            "assumptions": [
                "LEAR-style specification: 24 per-hour LASSOs; full daily price profiles at lags 1,2,7; same-hour lag 3; current-hour load/wind/solar forecasts; calendar dummies.",
                "Alpha selected on the final chronological calibration segment inside each training window. Residual intervals use that same segment; they are heuristic, not conformal guarantees.",
                "Asinh/scalers fit inside each training split. Inverse of transformed point prediction is not asserted to be a conditional mean.",
                "LightGBM uses fixed hyperparameters and separate 10/50/90% models. Crossing quantiles are sorted before scoring; raw forecasts are retained.",
                "Local-day policy excludes incomplete/DST target and lag-source days. Training window is 364 calendar days, with fewer usable days explicitly recorded.",
                "Daily price-lag availability relies on prior auction publication; current forecast-vintage timing remains unverified for downloaded data.",
                "Battery is price-taking, energy-only, daily empty start/end, no simultaneous charge/discharge; throughput and import costs are configured. No multi-day carry, market impact or other grid charges.",
                "Daily aggregation research prices are used; hourly aggregation loses quarter-hour trading opportunities.",
                "Seven-day runs are development checks, not persuasive significance evidence. No final untouched holdout has been established.",
            ],
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in ["numpy", "pandas", "scipy", "scikit-learn", "lightgbm", "entsoe-py"]
            },
            "source_code_sha256": {
                source_file.name: hashlib.sha256(source_file.read_bytes()).hexdigest()
                for source_file in PROJECT.glob("*.py")
            },
            "finished_utc": datetime.now(timezone.utc).isoformat(),
        }
        with (output / "results.json").open("x", encoding="utf-8") as file:
            json.dump(json_safe(report), file, indent=2, allow_nan=False)
        manifest.update(status="success", finished_utc=report["finished_utc"])
        print(f"Pipeline complete: {output}", flush=True)
        return output
    except Exception as error:
        manifest.update(status="failed", error_type=type(error).__name__, error=str(error))
        (output / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        (output / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        # Inventory successes AND failures; a ledger failure must not mask a model error.
        try:
            export_trial_ledger(PROJECT, data_root=DATA_ROOT)
        except (OSError, ValueError) as ledger_error:
            print(f"Warning: trial ledger refresh failed: {ledger_error}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["demo", "empirical"], default="demo")
    parser.add_argument("--evaluation-days", type=int, default=7)
    parser.add_argument("--training-days", type=int, default=364)
    parser.add_argument("--acknowledge-unverified-vintages", action="store_true")
    parser.add_argument("--processed-id")
    parser.add_argument(
        "--require-verified-vintages",
        action="store_true",
        help="Fail closed for historical data until original publication evidence is verified",
    )
    args = parser.parse_args()
    try:
        run(
            args.mode,
            args.evaluation_days,
            args.training_days,
            args.acknowledge_unverified_vintages,
            args.processed_id,
            args.require_verified_vintages,
        )
    except Exception as error:
        print(f"Pipeline failed: {error}", flush=True)
        raise SystemExit(1) from error
