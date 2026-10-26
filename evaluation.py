"""Forecast losses on the original EUR/MWh scale and daily paired comparisons."""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

EVALUATED_MODELS = ("lear", "lightgbm", "naive")
EVALUATED_QUANTILES = (0.1, 0.5, 0.9)
MINIMUM_DM_DAYS = 30


def pinball(y: Sequence[float], q: Sequence[float], tau: float) -> np.ndarray:
    """Return asymmetric quantile loss for each observation.

    Underprediction is weighted by tau; overprediction by 1-tau. Inputs use
    original price units, so averaging produces comparable EUR/MWh losses.
    """
    if not 0 < tau < 1:
        raise ValueError("Quantile must lie strictly between 0 and 1")
    actual_prices = np.asarray(y, dtype=float)
    quantile_predictions = np.asarray(q, dtype=float)
    if actual_prices.shape != quantile_predictions.shape:
        raise ValueError("Actual prices and quantile predictions must have matching shapes")
    if not np.isfinite(actual_prices).all() or not np.isfinite(quantile_predictions).all():
        raise ValueError("Quantile scoring requires finite values")
    forecast_error = actual_prices - quantile_predictions
    return np.maximum(tau * forecast_error, (tau - 1) * forecast_error)


def dm_test(differences: Sequence[float]) -> dict[str, Any]:
    """Compare daily LEAR-minus-LightGBM mean absolute losses.

    Positive differences favour LightGBM. Bartlett/Newey-West autocovariances
    account for dependence between daily losses. The horizon-one HLN factor
    and approximate t reference are retained from the baseline implementation.
    The 30-day gate is a reporting policy, not a guarantee of valid inference.
    """
    loss_differences = np.asarray(differences, dtype=float)
    if loss_differences.ndim != 1:
        raise ValueError("DM test requires a one-dimensional daily loss sequence")
    day_count = len(loss_differences)
    if day_count < 3 or not np.isfinite(loss_differences).all():
        return {
            "statistic": None,
            "p_value": None,
            "days": day_count,
            "inference_eligible": False,
            "note": "Insufficient matched daily losses.",
        }
    centered_losses = loss_differences - loss_differences.mean()
    hac_lags = min(int(np.floor(day_count ** (1 / 3))), day_count - 1)
    long_run_variance = np.dot(centered_losses, centered_losses) / day_count
    for lag in range(1, hac_lags + 1):
        bartlett_weight = 1 - lag / (hac_lags + 1)
        autocovariance = np.dot(centered_losses[lag:], centered_losses[:-lag]) / day_count
        long_run_variance += 2 * bartlett_weight * autocovariance
    if long_run_variance <= 1e-14:
        statistic, p_value = None, None
    else:
        standard_error = np.sqrt(long_run_variance / day_count)
        hln_correction = np.sqrt((day_count - 1) / day_count)
        statistic = float(loss_differences.mean() / standard_error * hln_correction)
        p_value = float(2 * student_t.sf(abs(statistic), df=day_count - 1))
    return {
        "statistic": statistic,
        "p_value": p_value,
        "days": day_count,
        "hac_lags": hac_lags,
        "mean_lear_minus_lightgbm_absolute_loss": float(loss_differences.mean()),
        "inference_eligible": day_count >= MINIMUM_DM_DAYS and p_value is not None,
        "method": "Daily mean absolute loss; Bartlett/Newey-West long-run variance; horizon-one HLN correction and approximate t reference.",
        "note": "Positive difference favours LightGBM. Short samples are diagnostic, not persuasive significance evidence.",
    }


def _probabilistic_metrics(
    predictions: pd.DataFrame, model_name: str
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Score the fixed 10/50/90% quantiles and inclusive central 80% interval."""
    actual_prices = predictions["actual"].to_numpy()
    quantile_losses = []
    calibration_records = []
    for quantile in EVALUATED_QUANTILES:
        quantile_column = f"{model_name}_q{int(quantile * 100)}"
        quantile_losses.append(
            pinball(actual_prices, predictions[quantile_column], quantile).mean()
        )
        calibration_records.append(
            {
                "model": model_name,
                "quantile": quantile,
                "empirical_fraction_below": float(
                    (actual_prices <= predictions[quantile_column]).mean()
                ),
            }
        )
    lower_bound = predictions[f"{model_name}_q10"]
    upper_bound = predictions[f"{model_name}_q90"]
    return {
        "mean_pinball": float(np.mean(quantile_losses)),
        "coverage_80": float(
            ((actual_prices >= lower_bound) & (actual_prices <= upper_bound)).mean()
        ),
        "interval_width": float((upper_bound - lower_bound).mean()),
    }, calibration_records


def evaluate(
    predictions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return overall, quantile-calibration, hourly and daily DM diagnostics.

    The paired comparison aggregates hours into delivery-day losses first;
    treating all 168 observations of a week as independent would overstate
    the information available for model comparison.
    """
    if predictions.empty:
        raise ValueError("Cannot evaluate an empty forecast table")
    metric_records = []
    calibration_records = []
    hourly_records = []
    actual_prices = predictions["actual"].to_numpy()
    for model_name in EVALUATED_MODELS:
        forecast_error = actual_prices - predictions[model_name].to_numpy()
        if not np.isfinite(forecast_error).all():
            raise ValueError("Evaluation requires finite actual prices and forecasts")
        metric_record = {
            "model": model_name,
            "mae": float(np.abs(forecast_error).mean()),
            "rmse": float(np.sqrt(np.square(forecast_error).mean())),
        }
        if model_name != "naive":
            probabilistic_metrics, model_calibration = _probabilistic_metrics(
                predictions, model_name
            )
            metric_record.update(probabilistic_metrics)
            calibration_records.extend(model_calibration)
        metric_records.append(metric_record)
        for local_hour, hourly_predictions in predictions.groupby("hour_local"):
            hourly_error = hourly_predictions.actual - hourly_predictions[model_name]
            hourly_records.append(
                {
                    "model": model_name,
                    "hour_local": int(local_hour),
                    "mae": float(np.abs(hourly_error).mean()),
                    "rmse": float(np.sqrt(np.square(hourly_error).mean())),
                }
            )
    daily_losses = (
        predictions.assign(
            lear_loss=np.abs(predictions.actual - predictions.lear),
            lightgbm_loss=np.abs(predictions.actual - predictions.lightgbm),
        )
        .groupby("delivery_date_local")[["lear_loss", "lightgbm_loss"]]
        .mean()
    )
    return (
        pd.DataFrame(metric_records),
        pd.DataFrame(calibration_records),
        pd.DataFrame(hourly_records),
        dm_test(daily_losses.lear_loss - daily_losses.lightgbm_loss),
    )
