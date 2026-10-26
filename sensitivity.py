"""Battery cost/physical sensitivity using frozen forecasts and actual settlement.

Each scenario changes one assumption, reoptimises all policies and recomputes
perfect foresight under identical constraints. It is not a model-tuning search.
"""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from battery import value_forecasts

PROJECT = Path(__file__).resolve().parent


def sensitivity_scenarios(baseline: dict) -> list[tuple[str, dict]]:
    """Return a declared one-factor-at-a-time grid, including the baseline."""
    scenarios = [("baseline", dict(baseline))]
    grid = {
        "throughput_cost_eur_mwh": (0.0, 2.0, 5.0, 10.0),
        "import_fee_eur_mwh": (0.0, 5.0, 10.0),
        "round_trip_efficiency": (0.8, 0.9, 0.95),
        "capacity_mwh": (2.0, 4.0, 8.0),
    }
    for setting, values in grid.items():
        for value in values:
            if value != float(baseline.get(setting, 0)):
                scenarios.append((f"{setting}={value:g}", dict(baseline, **{setting: value})))
    return scenarios


def evaluate_sensitivity(predictions: pd.DataFrame, baseline: dict) -> pd.DataFrame:
    """Return period-total value and matched-upper-bound capture per scenario."""
    records = []
    for scenario, settings in sensitivity_scenarios(baseline):
        daily_values, _ = value_forecasts(predictions, settings)
        totals = daily_values.groupby("model")[["gross_eur", "cost_eur", "net_eur"]].sum()
        upper_bound = float(totals.loc["perfect_foresight", "net_eur"])
        for model, values in totals.iterrows():
            records.append(
                {
                    "scenario": scenario,
                    **settings,
                    "duration_at_rated_power_hours": settings["capacity_mwh"]
                    / settings["power_mw"],
                    "model": model,
                    **values.to_dict(),
                    "perfect_foresight_net_eur": upper_bound,
                    "capture_fraction": float(values.net_eur) / upper_bound
                    if upper_bound > 1e-6
                    else None,
                    "evaluation_days": predictions.delivery_date_local.nunique(),
                    "planning_policy": "reoptimised at each setting using unchanged price forecasts",
                }
            )
    return pd.DataFrame(records)


def write_sensitivity(predictions: pd.DataFrame, baseline: dict, output: Path) -> pd.DataFrame:
    """Save explicit scenario settings and results inside an experiment directory."""
    results = evaluate_sensitivity(predictions, baseline)
    results.to_csv(output / "sensitivity.csv", index=False)
    return results


def main() -> None:
    """Analyse a completed run into a new directory without editing its archive."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    import re

    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
        raise ValueError("Invalid run id")
    source = PROJECT / "data" / "results" / args.run_id
    report = json.loads((source / "results.json").read_text(encoding="utf-8"))
    predictions = pd.read_csv(source / "forecasts.csv")
    output = PROJECT / "data" / "sensitivity" / (args.run_id + "_" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True)
    results = write_sensitivity(predictions, report["config"]["battery"], output)
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "source_run": args.run_id,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "mode": report["mode"],
                "forecast_vintages_verified": report.get("publication_vintages_verified", False),
                "scenarios": results.scenario.nunique(),
                "purpose": "descriptive sensitivity, not strategy selection",
                "omitted_costs": [
                    "market impact",
                    "unconfigured grid/tax/capacity charges",
                    "capital and financing costs",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
