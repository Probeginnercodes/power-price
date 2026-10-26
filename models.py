"""Daily LEAR-style and quantile-boosting models for the reduced research scope.

The design builder owns lag construction; training helpers own chronological
selection, fitting and model artefacts. Delivery timestamps are UTC, while price
profiles and rolling windows follow Europe/Berlin calendar days.
"""

import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import Lasso
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from transforms import AsinhTransform

FORECASTS = [
    "load_forecast_mw",
    "solar_forecast_mw",
    "wind_offshore_forecast_mw",
    "wind_onshore_forecast_mw",
]
LOCAL_TIMEZONE = "Europe/Berlin"
HOURS_PER_STANDARD_DAY = 24


def design_table(hourly: pd.DataFrame) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    """Return complete model rows, ordered feature names and exclusion counts.

    Lags 1, 2 and 7 supply full 24-hour price profiles; lag 3 supplies the same
    clock hour. A calendar reindex prevents missing days from shifting lag
    meanings. Incomplete and 23/25-hour days are excluded, never reshaped.
    """
    frame = hourly.copy()
    timestamps = pd.to_datetime(frame["delivery_start_utc"], utc=True)
    if timestamps.duplicated().any():
        raise ValueError("Duplicate delivery timestamps")
    frame.index = pd.DatetimeIndex(timestamps)
    frame = frame.sort_index()
    local_timestamps = frame.index.tz_convert(LOCAL_TIMEZONE)
    frame["day"] = local_timestamps.strftime("%Y-%m-%d")
    frame["hour"] = local_timestamps.hour
    daily_profiles = {}
    for delivery_day, daily_rows in frame.groupby("day"):
        day_start = pd.Timestamp(delivery_day, tz=LOCAL_TIMEZONE)
        day_end = day_start + pd.DateOffset(days=1)
        expected_index = pd.date_range(
            day_start.tz_convert("UTC"), day_end.tz_convert("UTC"), freq="h", inclusive="left"
        )
        if len(expected_index) == HOURS_PER_STANDARD_DAY and daily_rows.index.equals(
            expected_index
        ):
            daily_profiles[delivery_day] = daily_rows.price_eur_mwh.to_numpy()
    calendar_dates = pd.date_range(frame.day.min(), frame.day.max(), freq="D").strftime("%Y-%m-%d")
    price_profiles = pd.DataFrame.from_dict(
        daily_profiles, orient="index", columns=range(HOURS_PER_STANDARD_DAY)
    ).reindex(calendar_dates)
    design = pd.DataFrame(index=frame.index)
    feature_columns = []
    for lag_days in (1, 2, 7):
        lagged_profile = price_profiles.shift(lag_days).reindex(frame.day).to_numpy()
        for local_hour in range(HOURS_PER_STANDARD_DAY):
            feature_name = f"price_d{lag_days}_h{local_hour:02d}"
            design[feature_name] = lagged_profile[:, local_hour]
            feature_columns.append(feature_name)
    lagged_profile = price_profiles.shift(3).reindex(frame.day).to_numpy()
    design["price_d3_same_hour"] = lagged_profile[np.arange(len(frame)), frame.hour.to_numpy()]
    feature_columns.append("price_d3_same_hour")
    for column in FORECASTS:
        design[column] = pd.to_numeric(frame[column], errors="raise")
        feature_columns.append(column)
    design["hour_local"] = frame.hour
    feature_columns.append("hour_local")
    for weekday in range(7):
        feature_name = f"weekday_{weekday}"
        design[feature_name] = (local_timestamps.weekday == weekday).astype(int)
        feature_columns.append(feature_name)
    design["actual"] = pd.to_numeric(frame.price_eur_mwh, errors="raise")
    design["delivery_date_local"] = frame.day
    valid_rows = design[feature_columns + ["actual"]].notna().all(axis=1) & frame.day.isin(
        daily_profiles
    )
    if not np.isfinite(design.loc[valid_rows, feature_columns + ["actual"]].to_numpy(float)).all():
        raise ValueError("Nonfinite features")
    return (
        design.loc[valid_rows].copy(),
        feature_columns,
        {
            "original_hours": len(frame),
            "usable_hours": int(valid_rows.sum()),
            "complete_24h_source_days": len(daily_profiles),
            "excluded_hours": int((~valid_rows).sum()),
            "dst_policy": "Exclude 23/25-hour or incomplete target and lag-source days; never silently reshape them.",
        },
    )


def lasso(alpha: float) -> Pipeline:
    """Create an unfitted scaler/LASSO pair so scaling stays within each split."""
    return make_pipeline(StandardScaler(), Lasso(alpha=alpha, max_iter=20000, tol=1e-3))


def _fit_lasso(features: pd.DataFrame, transformed_prices: pd.Series, alpha: float) -> Pipeline:
    """Treat failure to converge as an error rather than publish dubious fits."""
    model = lasso(alpha)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model.fit(features, transformed_prices)
    return model


def _fit_lear(
    training: pd.DataFrame,
    inner_training: pd.DataFrame,
    calibration: pd.DataFrame,
    forecast_rows: pd.DataFrame,
    feature_columns: list[str],
    config: dict[str, Any],
    inner_transform: AsinhTransform,
    final_transform: AsinhTransform,
    output: pd.DataFrame,
    model_directory: Path,
) -> None:
    """Select alpha on past calibration data, then refit 24 hourly models.

    Residual quantiles extend point LEAR into heuristic intervals. They reuse
    the alpha-selection segment and therefore provide no conformal guarantee.
    """
    hourly_models = []
    output["lear"] = np.nan
    for quantile in config["quantiles"]:
        output[f"lear_q{int(quantile * 100)}"] = np.nan
    for local_hour in range(HOURS_PER_STANDARD_DAY):
        inner_hour = inner_training.loc[inner_training.hour_local == local_hour]
        calibration_hour = calibration.loc[calibration.hour_local == local_hour]
        training_hour = training.loc[training.hour_local == local_hour]
        forecast_hour = forecast_rows.loc[forecast_rows.hour_local == local_hour]
        candidates = []
        for alpha in config["lasso_alphas"]:
            candidate = _fit_lasso(
                inner_hour[feature_columns], inner_transform.transform(inner_hour.actual), alpha
            )
            calibration_prediction = inner_transform.inverse_transform(
                candidate.predict(calibration_hour[feature_columns])
            )
            calibration_mae = float(
                np.abs(calibration_hour.actual.to_numpy() - calibration_prediction).mean()
            )
            candidates.append((calibration_mae, alpha, calibration_prediction))
        _, selected_alpha, calibration_prediction = min(
            candidates, key=lambda candidate: candidate[0]
        )
        calibration_residuals = calibration_hour.actual.to_numpy() - calibration_prediction
        fitted_model = _fit_lasso(
            training_hour[feature_columns],
            final_transform.transform(training_hour.actual),
            selected_alpha,
        )
        point_forecast = final_transform.inverse_transform(
            fitted_model.predict(forecast_hour[feature_columns])
        )
        output.loc[forecast_hour.index, "lear"] = point_forecast
        for quantile in config["quantiles"]:
            output.loc[forecast_hour.index, f"lear_q{int(quantile * 100)}"] = (
                point_forecast + np.quantile(calibration_residuals, quantile)
            )
        scaler, regressor = fitted_model.steps[0][1], fitted_model.steps[1][1]
        hourly_models.append(
            {
                "hour": local_hour,
                "alpha": selected_alpha,
                # Preserve every inner-selection candidate, not just the winning alpha.
                "alpha_candidates": [
                    {"alpha": alpha, "calibration_mae": score} for score, alpha, _ in candidates
                ],
                "scaler_mean": scaler.mean_.tolist(),
                "scaler_scale": scaler.scale_.tolist(),
                "coefficients": regressor.coef_.tolist(),
                "intercept": float(regressor.intercept_),
            }
        )
    with (model_directory / "lear.json").open("x", encoding="utf-8") as model_file:
        json.dump({"columns": feature_columns, "hour_models": hourly_models}, model_file)


def _fit_quantile_models(
    training: pd.DataFrame,
    forecast_rows: pd.DataFrame,
    feature_columns: list[str],
    config: dict[str, Any],
    transform: AsinhTransform,
    output: pd.DataFrame,
    model_directory: Path,
) -> tuple[int, list[dict[str, Any]]]:
    """Fit fixed quantile models and retain both raw and rearranged predictions."""
    raw_predictions = []
    feature_importance = []
    for quantile in config["quantiles"]:
        model = LGBMRegressor(
            objective="quantile",
            alpha=quantile,
            random_state=config["seed"],
            n_jobs=2,
            verbosity=-1,
            deterministic=True,
            force_col_wise=True,
            **config["lightgbm"],
        )
        model.fit(training[feature_columns], transform.transform(training.actual))
        raw_predictions.append(
            transform.inverse_transform(model.predict(forecast_rows[feature_columns]))
        )
        model.booster_.save_model(str(model_directory / f"lightgbm_q{int(quantile * 100)}.txt"))
        if quantile == 0.5:
            feature_importance = [
                {"feature": feature_name, "gain": float(gain)}
                for feature_name, gain in zip(
                    feature_columns,
                    model.booster_.feature_importance(importance_type="gain"),
                    strict=True,
                )
            ]
    raw_predictions = np.array(raw_predictions).T
    crossing_hours = int((np.diff(raw_predictions, axis=1) < 0).any(axis=1).sum())
    # Predeclared monotone rearrangement uses no observed test prices.
    ordered_predictions = np.sort(raw_predictions, axis=1)
    for index, quantile in enumerate(config["quantiles"]):
        output[f"lightgbm_raw_q{int(quantile * 100)}"] = raw_predictions[:, index]
        output[f"lightgbm_q{int(quantile * 100)}"] = ordered_predictions[:, index]
    output["lightgbm"] = output["lightgbm_q50"]
    return crossing_hours, feature_importance


def forecast_day(
    train: pd.DataFrame,
    test: pd.DataFrame,
    columns: list[str],
    config: dict[str, Any],
    model_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit on strictly earlier delivery days; return forecasts and audit metadata.

    The public arguments and CSV column names remain compatible with saved
    runs. Chronological separation cannot establish publication-vintage safety;
    empirical runs remain exploratory until that evidence is verified.
    """
    if len(test) != HOURS_PER_STANDARD_DAY or test.delivery_date_local.nunique() != 1:
        raise ValueError("Require one complete delivery day")
    forecast_day_start = pd.Timestamp(
        test.delivery_date_local.iloc[0], tz=LOCAL_TIMEZONE
    ).tz_convert("UTC")
    if not (train.index < forecast_day_start).all():
        raise ValueError("Training overlaps forecast day")
    calibration_start = (
        pd.Timestamp(test.delivery_date_local.iloc[0])
        - pd.Timedelta(days=config["calibration_days"])
    ).strftime("%Y-%m-%d")
    inner_training = train.loc[train.delivery_date_local < calibration_start]
    calibration = train.loc[train.delivery_date_local >= calibration_start]
    if (
        inner_training.delivery_date_local.nunique() < 30
        or calibration.delivery_date_local.nunique() < 7
    ):
        raise ValueError("Insufficient chronological training/calibration history")
    inner_end = pd.Timestamp(calibration_start, tz=LOCAL_TIMEZONE).tz_convert("UTC")
    inner_transform = AsinhTransform.fit(inner_training.actual, training_end=inner_end)
    final_transform = AsinhTransform.fit(train.actual, training_end=forecast_day_start)
    model_dir.mkdir(parents=True, exist_ok=False)
    final_transform.save(model_dir / "transform.json")
    output = test[["actual", "delivery_date_local", "hour_local"]].copy()
    output["delivery_start_utc"] = [timestamp.isoformat() for timestamp in test.index]
    output["naive"] = test.apply(lambda row: row[f"price_d1_h{int(row.hour_local):02d}"], axis=1)
    _fit_lear(
        train,
        inner_training,
        calibration,
        test,
        columns,
        config,
        inner_transform,
        final_transform,
        output,
        model_dir,
    )
    crossing_hours, feature_importance = _fit_quantile_models(
        train, test, columns, config, final_transform, output, model_dir
    )
    if not np.isfinite(output.select_dtypes(include="number")).all().all():
        raise ValueError("Invalid model outputs")
    diagnostics = {
        "day": test.delivery_date_local.iloc[0],
        "training_rows": len(train),
        "usable_training_days": int(train.delivery_date_local.nunique()),
        "training_end_exclusive_utc": forecast_day_start.isoformat(),
        "training_last_delivery_utc": train.index.max().isoformat(),
        "calibration_days_used": int(calibration.delivery_date_local.nunique()),
        "raw_quantile_crossing_hours": crossing_hours,
        "feature_importance_gain": feature_importance,
    }
    return output.reset_index(drop=True), diagnostics
