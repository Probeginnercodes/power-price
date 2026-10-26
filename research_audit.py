"""Retrospective run inventory and prospectively maintained trial accounting.

Saved runs are evidence of executions, not a complete history of human model
choices. Holm correction is descriptive here and cannot repair leakage or an
unknown number of earlier trials. Never interpret these adjusted values as a
certified final hypothesis test.
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


def fingerprint(value) -> str:
    """Use stable JSON to distinguish archived configurations and code versions."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def holm_adjust(p_values: list[float]) -> list[float]:
    """Return Holm family-wise adjusted p-values in their original order."""
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in p_values):
        raise ValueError("P-values must be finite numbers in [0, 1]")
    ordering = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [0.0] * len(p_values)
    running_maximum = 0.0
    for rank, index in enumerate(ordering):
        running_maximum = max(running_maximum, (len(p_values) - rank) * p_values[index])
        adjusted[index] = min(1.0, running_maximum)
    return adjusted


def inventory_runs(results_directory: Path) -> tuple[pd.DataFrame, dict]:
    """Include failures and repeated runs; collapse only identical test signatures."""
    records = []
    unreadable = []
    for manifest_path in sorted(results_directory.glob("*/run.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            result_path = manifest_path.parent / "results.json"
            report = (
                json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
            )
            config = manifest.get("config", {})
            model_config = {
                name: config.get(name)
                for name in (
                    "quantiles",
                    "training_days",
                    "calibration_days",
                    "lasso_alphas",
                    "lightgbm",
                    "seed",
                )
            }
            # Repeated executions do not create extra hypotheses. Distinct code,
            # data, settings or evaluation dates are counted conservatively.
            signature = fingerprint(
                {
                    "config": model_config,
                    "code": report.get("source_code_sha256"),
                    "source": report.get("source_sha256"),
                    "days": report.get("forecast_days"),
                }
            )
            dm = report.get("dm_test", {})
            records.append(
                {
                    "run_id": manifest_path.parent.name,
                    "mode": manifest.get("mode"),
                    "status": manifest.get("status"),
                    "started_utc": manifest.get("started_utc"),
                    "finished_utc": manifest.get("finished_utc"),
                    "error_type": manifest.get("error_type"),
                    "configuration_signature": fingerprint(model_config),
                    "test_signature": signature,
                    "evaluation_days": len(report.get("forecast_days", [])),
                    "raw_dm_p_value": dm.get("p_value"),
                    "forecast_vintages_verified": report.get("publication_vintages_verified")
                    is True,
                    "research_inference_permitted": False,
                    "accounting_note": "retrospective archive inventory; pre-archive human trials unknown",
                }
            )
        except (OSError, ValueError, TypeError) as error:
            unreadable.append(
                {"run_id": manifest_path.parent.name, "error_type": type(error).__name__}
            )
    ledger = pd.DataFrame(records)
    hypotheses = {}
    for record in records:
        p_value = record["raw_dm_p_value"]
        if (
            record["mode"] == "empirical"
            and record["status"] == "success"
            and p_value is not None
            and math.isfinite(p_value)
        ):
            hypotheses.setdefault(record["test_signature"], float(p_value))
    adjusted = dict(zip(hypotheses, holm_adjust(list(hypotheses.values())), strict=True))
    if not ledger.empty:
        ledger["holm_adjusted_dm_p_value_diagnostic"] = ledger.apply(
            lambda row: adjusted.get(row.test_signature) if row["mode"] == "empirical" else None,
            axis=1,
        )
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "archived_executions": len(records),
        "failed_executions": sum(record["status"] == "failed" for record in records),
        "distinct_archived_model_configurations": len(
            {record["configuration_signature"] for record in records}
        ),
        "distinct_empirical_test_signatures_with_p_values": len(hypotheses),
        "unreadable_manifests": unreadable,
        "complete_lifetime_trial_count_known": False,
        "research_inference_permitted": False,
        "adjustment": "Holm over unique available empirical test signatures, diagnostic only",
        "limitations": "Pre-archive trials unknown; code-only refactors may split signatures; vintages unverified and evaluation previously inspected. No final significance claim.",
    }
    return ledger, summary


def export_trial_ledger(project: Path = PROJECT, *, data_root: Path | None = None) -> dict:
    """Atomically replace derived ledger views; source run manifests stay immutable."""
    data_root = data_root or project / "data"
    ledger, summary = inventory_runs(data_root / "results")
    output = data_root / "research"
    output.mkdir(parents=True, exist_ok=True)
    for name, content in (
        ("trial_ledger.csv", ledger.to_csv(index=False)),
        ("trial_summary.json", json.dumps(summary, indent=2)),
    ):
        temporary = output / (name + "." + uuid.uuid4().hex + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(output / name)
    return summary


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(export_trial_ledger(), indent=2))
