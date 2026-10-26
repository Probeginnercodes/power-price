import unittest

import pandas as pd

from download_data import clean_result


class DownloadTests(unittest.TestCase):
    def test_end_is_exclusive_and_negative_prices_are_valid(self):
        start = pd.Timestamp("2026-10-15", tz="UTC")
        end = start + pd.Timedelta(hours=1)
        series = pd.Series([-5, 3], index=pd.DatetimeIndex([start, end]))
        result = clean_result(series, start, end)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0, 0], -5)

    def test_local_fall_back_hours_remain_distinct_in_utc(self):
        index = pd.date_range("2024-10-27", periods=25, freq="h", tz="Europe/Berlin")
        result = clean_result(
            pd.Series(range(25), index=index),
            index[0].tz_convert("UTC"),
            (index[-1] + pd.Timedelta(hours=1)).tz_convert("UTC"),
        )
        self.assertEqual(len(result), 25)
        self.assertFalse(result.index.has_duplicates)

    def test_duplicates_rejected(self):
        start = pd.Timestamp("2026-10-15", tz="UTC")
        with self.assertRaises(ValueError):
            clean_result(
                pd.Series([1, 2], index=[start, start]), start, start + pd.Timedelta(days=1)
            )

    def test_timezone_required(self):
        start = pd.Timestamp("2026-10-15", tz="UTC")
        with self.assertRaises(ValueError):
            clean_result(
                pd.Series([1], index=pd.DatetimeIndex(["2026-10-15"])),
                start,
                start + pd.Timedelta(days=1),
            )


if __name__ == "__main__":
    unittest.main()
