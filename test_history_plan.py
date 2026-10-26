import unittest

import pandas as pd

from history_plan import make_plan


class HistoryPlanTests(unittest.TestCase):
    def test_training_window_and_warmup_are_calendar_days(self):
        plan = make_plan()
        first = pd.Timestamp(plan["first_forecast_local_day"])
        training = pd.Timestamp(plan["first_training_start_local_day"])
        warmup = pd.Timestamp(plan["lag_warmup_start_local_day"])
        self.assertEqual((first - training).days, 364)
        self.assertEqual((training - warmup).days, 7)
        self.assertEqual(plan["development_delivery_days"], 7)

    def test_utc_request_encloses_complete_local_delivery_days(self):
        plan = make_plan()
        warmup = pd.Timestamp(plan["lag_warmup_start_local_day"], tz="Europe/Berlin").tz_convert(
            "UTC"
        )
        end = pd.Timestamp(
            plan["evaluation_end_local_day_exclusive"], tz="Europe/Berlin"
        ).tz_convert("UTC")
        self.assertLessEqual(pd.Timestamp(plan["download_start_utc"], tz="UTC"), warmup)
        self.assertGreaterEqual(pd.Timestamp(plan["download_end_utc_exclusive"], tz="UTC"), end)

    def test_period_is_not_presented_as_untouched_test(self):
        self.assertIn("NOT a final untouched", make_plan()["purpose"])

    def test_invalid_dates_rejected(self):
        with self.assertRaises(ValueError):
            make_plan("2026-10-22", "2026-10-15")


if __name__ == "__main__":
    unittest.main()
