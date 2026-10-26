import unittest

import numpy as np
import pandas as pd

from prepare_history import complete_hour_means


class HistoryPreparationTests(unittest.TestCase):
    def setUp(self):
        self.start = pd.Timestamp("2026-01-01", tz="UTC")
        self.end = self.start + pd.Timedelta(hours=1)
        self.frame = pd.DataFrame(
            {"price": [1, 2, 3, 4]}, index=pd.date_range(self.start, periods=4, freq="15min")
        )

    def test_complete_hour_average(self):
        result = complete_hour_means(self.frame, 15, self.start, self.end)
        self.assertEqual(result.iloc[0, 0], 2.5)

    def test_missing_quarter_does_not_produce_partial_mean(self):
        result = complete_hour_means(self.frame.iloc[:3], 15, self.start, self.end)
        self.assertTrue(np.isnan(result.iloc[0, 0]))

    def test_missing_value_is_not_filled(self):
        self.frame.loc[self.frame.index[0], "price"] = np.nan
        self.assertTrue(
            complete_hour_means(self.frame, 15, self.start, self.end).isna().all().all()
        )


if __name__ == "__main__":
    unittest.main()
