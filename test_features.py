import unittest

import numpy as np
import pandas as pd

from features import FORECAST_COLUMNS, INPUT_COLUMNS, TARGET_COLUMN, build_features


def sample(start="2026-01-01", days=10):
    first = pd.Timestamp(start, tz="Europe/Berlin")
    last = first + pd.DateOffset(days=days)
    stamps = pd.date_range(
        first.tz_convert("UTC"), last.tz_convert("UTC"), freq="h", inclusive="left"
    )
    frame = pd.DataFrame(
        {"delivery_start_utc": stamps, "price_eur_mwh": np.arange(len(stamps), dtype=float) - 100}
    )
    for name in FORECAST_COLUMNS:
        frame[name] = 10.0
    return frame


class FeatureTests(unittest.TestCase):
    def test_lags_are_same_local_hour_on_earlier_dates(self):
        result, _ = build_features(sample())
        row = result.loc[
            (result["delivery_date_local"] == "2026-01-08") & (result["hour_local"] == 12)
        ].iloc[0]
        self.assertEqual(row["price_lag_1d"], 56.0)
        self.assertEqual(row["price_lag_7d"], -88.0)
        self.assertEqual(int(result["history_complete"].sum()), 72)

    def test_current_target_does_not_enter_its_inputs(self):
        frame = sample()
        before, _ = build_features(frame)
        frame.loc[180, "price_eur_mwh"] = 99999
        after, _ = build_features(frame)
        pd.testing.assert_series_equal(
            before.loc[180, INPUT_COLUMNS], after.loc[180, INPUT_COLUMNS]
        )
        self.assertNotIn(TARGET_COLUMN, INPUT_COLUMNS)
        self.assertNotIn("price_eur_mwh", INPUT_COLUMNS)

    def test_one_week_is_not_enough_for_seven_day_lags(self):
        result, _ = build_features(sample(days=7))
        self.assertEqual(int(result["history_complete"].sum()), 0)
        self.assertTrue(result["price_lag_7d"].isna().all())

    def test_missing_source_hour_is_not_filled(self):
        frame = sample().drop(index=36)
        result, _ = build_features(frame)
        rows = result.loc[result["delivery_date_local"] == "2026-01-03"]
        self.assertTrue(rows["price_lag_1d"].isna().all())

    def test_dst_day_is_flagged_and_not_silently_reshaped(self):
        result, quality = build_features(sample("2024-10-20", 10))
        rows = result.loc[result["delivery_date_local"] == "2024-10-27"]
        self.assertEqual(len(rows), 25)
        self.assertFalse(rows["history_complete"].any())
        self.assertEqual(
            next(q["expected_hours"] for q in quality if q["delivery_date_local"] == "2024-10-27"),
            25,
        )
        # One week after the offset change, the lag must still reference noon local time.
        noon = result.loc[
            (result["delivery_date_local"] == "2024-10-28") & (result["hour_local"] == 12)
        ].iloc[0]
        source_time = pd.Timestamp(noon["lag_7d_source_delivery_start_utc"]).tz_convert(
            "Europe/Berlin"
        )
        self.assertEqual(source_time.hour, 12)
        self.assertEqual(str(source_time.date()), "2024-10-21")

    def test_duplicate_timestamps_fail(self):
        frame = sample()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            build_features(pd.concat([frame, frame.iloc[:1]]))

    def test_missing_forecast_fails(self):
        frame = sample()
        frame.loc[0, "load_forecast_mw"] = np.nan
        with self.assertRaisesRegex(ValueError, "Missing"):
            build_features(frame)

    def test_original_is_not_changed_and_vintage_not_certified(self):
        frame = sample()
        saved = frame.copy(deep=True)
        result, _ = build_features(frame)
        pd.testing.assert_frame_equal(frame, saved)
        self.assertFalse(result["forecast_vintage_verified"].any())


if __name__ == "__main__":
    unittest.main()
