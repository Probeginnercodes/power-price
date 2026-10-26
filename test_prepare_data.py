import unittest

import pandas as pd

from prepare_data import hourly_average, validate_frame


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.start = pd.Timestamp("2026-10-15", tz="UTC")
        self.end = self.start + pd.Timedelta(hours=1)
        self.frame = pd.DataFrame(
            {"price_eur_mwh": [-20, 0, 20, 40], "load_forecast_mw": [100, 200, 300, 400]},
            index=pd.date_range(self.start, periods=4, freq="15min"),
        )

    def test_average_not_sum_and_negative_prices_preserved(self):
        result = hourly_average(self.frame, self.start, self.end, 15)
        self.assertEqual(result.iloc[0]["price_eur_mwh"], 10)
        self.assertEqual(result.iloc[0]["load_forecast_mw"], 250)

    def test_missing_quarter_hour_fails(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            hourly_average(self.frame.iloc[:3], self.start, self.end, 15)

    def test_missing_value_fails(self):
        self.frame.iloc[0, 0] = float("nan")
        with self.assertRaisesRegex(ValueError, "Missing"):
            validate_frame(self.frame, self.start, self.end, 15)

    def test_duplicate_fails(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_frame(pd.concat([self.frame, self.frame.iloc[:1]]), self.start, self.end, 15)

    def test_naive_timestamp_fails(self):
        self.frame.index = self.frame.index.tz_localize(None)
        with self.assertRaisesRegex(ValueError, "timezone"):
            validate_frame(self.frame, self.start, self.end, 15)

    def test_missing_every_other_row_not_misread_as_half_hourly(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            hourly_average(self.frame.iloc[::2], self.start, self.end, 15)

    def test_daylight_saving_days_have_correct_hour_counts(self):
        for day, expected in [("2024-03-31", 23), ("2024-10-27", 25)]:
            local_start = pd.Timestamp(day, tz="Europe/Berlin")
            local_end = local_start + pd.DateOffset(days=1)
            start, end = local_start.tz_convert("UTC"), local_end.tz_convert("UTC")
            frame = pd.DataFrame(
                {"load_forecast_mw": 100},
                index=pd.date_range(start, end, freq="15min", inclusive="left"),
            )
            result = hourly_average(frame, start, end, 15)
            self.assertEqual(len(result), expected)
            self.assertFalse(result.index.has_duplicates)

    def test_hourly_inputs_need_no_expansion(self):
        frame = self.frame.iloc[:1]
        result = hourly_average(frame, self.start, self.end, 60)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["price_eur_mwh"], -20)


if __name__ == "__main__":
    unittest.main()
