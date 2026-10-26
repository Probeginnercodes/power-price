"""Validate the supported reduced-project configuration before creating a run.

The scoring and dashboard contracts currently use exactly 10/50/90% quantiles.
Reject unsupported settings explicitly rather than silently scoring another set.
"""

import json
import math
from pathlib import Path
from typing import Any

from battery import validate_battery_settings


def _integer(value: Any, name: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")


def validate_config(config: dict[str, Any]) -> None:
    """Validate required fields and supported ranges without mutating config."""
    required = {
        "quantiles",
        "training_days",
        "calibration_days",
        "evaluation_days",
        "lasso_alphas",
        "lightgbm",
        "seed",
        "battery",
    }
    missing = required - config.keys()
    if missing:
        raise ValueError(f"Missing configuration fields: {sorted(missing)}")
    unknown = config.keys() - required
    if unknown:
        raise ValueError(f"Unknown configuration fields: {sorted(unknown)}")
    if config["quantiles"] != [0.1, 0.5, 0.9]:
        raise ValueError("The reduced project requires ordered quantiles [0.1, 0.5, 0.9]")
    _integer(config["training_days"], "training_days", 60, 1095)
    _integer(config["evaluation_days"], "evaluation_days", 1, 60)
    _integer(config["calibration_days"], "calibration_days", 7, config["training_days"] - 30)
    _integer(config["seed"], "seed", 0, 2**31 - 1)
    alphas = config["lasso_alphas"]
    if (
        not isinstance(alphas, list)
        or not alphas
        or any(
            isinstance(alpha, bool)
            or not isinstance(alpha, (int, float))
            or not math.isfinite(alpha)
            or alpha <= 0
            for alpha in alphas
        )
    ):
        raise ValueError("lasso_alphas must be a nonempty list of finite positive numbers")
    lightgbm = config["lightgbm"]
    supported = {"n_estimators", "learning_rate", "num_leaves", "min_child_samples"}
    if not isinstance(lightgbm, dict) or set(lightgbm) != supported:
        raise ValueError(f"lightgbm must contain exactly {sorted(supported)}")
    for name in ("n_estimators", "min_child_samples"):
        _integer(lightgbm[name], f"lightgbm.{name}", 1, 100000)
    _integer(lightgbm["num_leaves"], "lightgbm.num_leaves", 2, 100000)
    learning_rate = lightgbm["learning_rate"]
    if (
        isinstance(learning_rate, bool)
        or not isinstance(learning_rate, (int, float))
        or not math.isfinite(learning_rate)
        or not 0 < learning_rate <= 1
    ):
        raise ValueError("lightgbm.learning_rate must be finite and in (0, 1]")
    if not isinstance(config["battery"], dict):
        raise ValueError("battery must be a settings object")
    battery_required = {
        "power_mw",
        "capacity_mwh",
        "round_trip_efficiency",
        "throughput_cost_eur_mwh",
    }
    if not battery_required <= config["battery"].keys() or config["battery"].keys() - (
        battery_required | {"import_fee_eur_mwh"}
    ):
        raise ValueError("Battery configuration has missing or unknown settings")
    validate_battery_settings(config["battery"])


def load_config(path: Path, *, training_days: int, evaluation_days: int) -> dict[str, Any]:
    """Read JSON, apply explicit run overrides, then validate the effective config."""
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object")
    config.update(training_days=training_days, evaluation_days=evaluation_days)
    validate_config(config)
    return config
