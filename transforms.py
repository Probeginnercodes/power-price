"""Training-only robust asinh price transform. No downloads or model fitting here.

Fit on a timestamp-indexed training Series with an explicit exclusive boundary.
Reuse that fitted object for validation/test data; never fit on the full history.
This date check does not replace the information-set/publication-time audit.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


def aware_utc(value):
    """Require an explicit timezone before normalising a training boundary to UTC."""
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError("Training boundaries require valid timezone-aware timestamps")
    return timestamp.tz_convert("UTC")


def finite_values(values):
    """Reject missing or nonfinite prices before fitting or applying a transform."""
    array = np.asarray(values, dtype=float)
    if array.size == 0 or not np.isfinite(array).all():
        raise ValueError(
            "Prices must be nonempty, finite numeric values; handle missing data explicitly"
        )
    return array


def restore_container(values, original):
    """Preserve Series labels or scalar shape when applying numerical operations."""
    if isinstance(original, pd.Series):
        return pd.Series(values, index=original.index, name=original.name)
    if np.ndim(original) == 0:
        return float(values)
    return values


@dataclass(frozen=True)
class AsinhTransform:
    location: float
    scale: float
    scale_method: str
    training_start_utc: str
    training_last_utc: str
    training_end_exclusive_utc: str
    training_rows: int

    def __post_init__(self):
        if not np.isfinite(self.location) or not np.isfinite(self.scale) or self.scale <= 0:
            raise ValueError("Location must be finite and scale must be finite and positive")
        if self.training_rows < 1:
            raise ValueError("At least one training observation is required")
        first = aware_utc(self.training_start_utc)
        last = aware_utc(self.training_last_utc)
        end = aware_utc(self.training_end_exclusive_utc)
        if not first <= last < end:
            raise ValueError("Invalid training period")

    @classmethod
    def fit(cls, training_prices, *, training_end):
        """Estimate robust location and scale using observations strictly before training_end."""
        if not isinstance(training_prices, pd.Series) or not isinstance(
            training_prices.index, pd.DatetimeIndex
        ):
            raise ValueError("Pass a pandas Series indexed by delivery timestamps")
        if training_prices.index.tz is None or training_prices.index.hasnans:
            raise ValueError("Training timestamps require a timezone and no missing dates")
        if training_prices.index.has_duplicates:
            raise ValueError("Duplicate training timestamps")
        end = aware_utc(training_end)
        index = training_prices.index.tz_convert("UTC")
        if (index >= end).any():
            raise ValueError(
                "Training data crosses its exclusive boundary; possible future-data leakage"
            )
        values = finite_values(training_prices)
        location = float(np.median(values))
        # Robust scale: normal-consistent median absolute deviation (MAD).
        scale = float(1.4826 * np.median(np.abs(values - location)))
        method = "1.4826 * MAD"
        if scale == 0:
            # Constant/mostly constant prices must not cause division by zero.
            q25, q75 = np.percentile(values, [25, 75])
            scale = float((q75 - q25) / 1.349)
            method = "IQR / 1.349 fallback"
        if scale == 0:
            scale = float(np.std(values, ddof=0))
            method = "population standard deviation fallback"
        if scale == 0:
            scale, method = 1.0, "constant training sample: unit scale"
        return cls(
            location,
            scale,
            method,
            index.min().isoformat(),
            index.max().isoformat(),
            end.isoformat(),
            len(values),
        )

    def transform(self, prices):
        """Apply the fitted asinh mapping without updating training statistics."""
        values = finite_values(prices)
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                result = np.arcsinh((values - self.location) / self.scale)
        except FloatingPointError:
            raise ValueError(
                "Transformation overflow; inspect price units and fitted scale"
            ) from None
        return restore_container(result, prices)

    def inverse_transform(self, transformed):
        """Restore original price units, rejecting numerical overflow."""
        values = finite_values(transformed)
        try:
            with np.errstate(over="raise", invalid="raise"):
                result = self.location + self.scale * np.sinh(values)
        except FloatingPointError:
            raise ValueError(
                "Inverse overflow; transformed predictions are numerically extreme"
            ) from None
        if not np.isfinite(result).all():
            raise ValueError("Inverse returned nonfinite prices")
        return restore_container(result, transformed)

    def save(self, path):
        # Exclusive create prevents accidental replacement of fitted parameters.
        """Write fitted transform parameters and training provenance as a new JSON file."""
        with Path(path).open("x", encoding="utf-8") as file:
            json.dump({"schema_version": 1, "parameters": asdict(self)}, file, indent=2)

    @classmethod
    def load(cls, path):
        """Restore an immutable fitted transform and validate its training provenance."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("Unsupported transform file version")
        return cls(**payload["parameters"])
