"""Deterministic synthetic plumbing test: these are NOT market observations."""

import numpy as np
import pandas as pd


def generate_hourly(seed=42, days=410):
    """Generate deterministic artificial hourly patterns for software checks, not market evidence."""
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2025-08-01", tz="Europe/Berlin")
    end = start + pd.DateOffset(days=days)
    index = pd.date_range(
        start.tz_convert("UTC"), end.tz_convert("UTC"), freq="h", inclusive="left"
    )
    local = index.tz_convert("Europe/Berlin")
    hour = local.hour.to_numpy()
    seasonal = np.cos(2 * np.pi * local.dayofyear.to_numpy() / 365.25)
    load = (
        49000
        + 6500 * np.cos(2 * np.pi * (hour - 17) / 24)
        + 5000 * seasonal
        + rng.normal(0, 900, len(index))
    )
    wind = np.maximum(
        1000, 13000 + 6000 * np.sin(np.arange(len(index)) / 90) + rng.normal(0, 1500, len(index))
    )
    solar = np.maximum(0, np.sin(np.pi * (hour - 6) / 12)) * 14000 * (1 - 0.35 * seasonal)
    base = 60 + 0.002 * (load - 49000) - 0.0022 * wind - 0.003 * solar + 8 * seasonal
    residual = rng.standard_t(5, len(index)) * 6
    price = base + residual + rng.binomial(1, 0.005, len(index)) * rng.uniform(60, 200, len(index))
    return pd.DataFrame(
        {
            "delivery_start_utc": index,
            "price_eur_mwh": price,
            "load_forecast_mw": load,
            "solar_forecast_mw": solar,
            "wind_offshore_forecast_mw": wind * 0.25,
            "wind_onshore_forecast_mw": wind * 0.75,
        }
    )
