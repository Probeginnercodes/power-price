import unittest

import numpy as np
import pandas as pd

from battery import dispatch, settle
from evaluation import dm_test, pinball
from models import design_table
from run_pipeline import json_safe, run
from synthetic_data import generate_hourly

SETTINGS = {
    "power_mw": 1,
    "capacity_mwh": 1,
    "round_trip_efficiency": 1,
    "throughput_cost_eur_mwh": 0,
    "import_fee_eur_mwh": 0,
}


class BatteryTests(unittest.TestCase):
    def test_known_two_hour_arbitrage_and_energy_balance(self):
        schedule = dispatch([-10, 100], SETTINGS)
        gross, cost, net = settle(schedule, [-10, 100], SETTINGS)
        self.assertAlmostEqual(net.sum(), 110, places=5)
        self.assertAlmostEqual(schedule["energy_end_mwh"][-1], 0, places=6)
        self.assertAlmostEqual(schedule["energy_end_mwh"][0], 1, places=6)

    def test_negative_prices_do_not_allow_simultaneous_modes(self):
        cfg = dict(SETTINGS, round_trip_efficiency=0.8, capacity_mwh=4)
        schedule = dispatch([-100, -100, -100, -100], cfg)
        self.assertLess(np.max(schedule["charge_mw"] * schedule["discharge_mw"]), 1e-7)
        self.assertLessEqual(np.max(schedule["energy_end_mwh"]), 4 + 1e-7)

    def test_perfect_foresight_bounds_forecast_schedule(self):
        actual = [-50, 100, 20, 90]
        forecast = [80, 10, 90, -20]
        upper = settle(dispatch(actual, SETTINGS), actual, SETTINGS)[2].sum()
        realised = settle(dispatch(forecast, SETTINGS), actual, SETTINGS)[2].sum()
        self.assertLessEqual(realised, upper + 1e-6)

    def test_costs_and_efficiency_remove_unprofitable_cycle(self):
        cfg = dict(SETTINGS, round_trip_efficiency=0.8, throughput_cost_eur_mwh=20)
        schedule = dispatch([50, 60], cfg)
        self.assertAlmostEqual(schedule["charge_mw"].sum(), 0, places=5)

    def test_invalid_efficiency_rejected(self):
        with self.assertRaises(ValueError):
            dispatch([10, 20], dict(SETTINGS, round_trip_efficiency=1.1))


class EvaluationTests(unittest.TestCase):
    def test_pinball_asymmetric_known_values(self):
        np.testing.assert_allclose(pinball([100, 0], [50, 50], 0.9), [45, 5])

    def test_dm_short_sample_is_not_declared_significant(self):
        self.assertFalse(dm_test([1, 2])["inference_eligible"])
        self.assertIsNone(dm_test([1, 2])["p_value"])

    def test_dm_sign_and_dependence_aware_variance(self):
        result = dm_test(np.random.default_rng(5).normal(1, 0.2, 90))
        self.assertGreater(result["statistic"], 0)
        self.assertLess(result["p_value"], 0.05)

    def test_zero_variance_loss_difference_is_not_divided_by_zero(self):
        self.assertIsNone(dm_test(np.zeros(40))["p_value"])

    def test_json_does_not_emit_nan(self):
        self.assertIsNone(json_safe({"x": float("nan")})["x"])


class ModelDesignTests(unittest.TestCase):
    def test_target_mutation_does_not_change_its_own_features(self):
        hourly = generate_hourly(days=20)
        first, cols, _ = design_table(hourly)
        index = first.index[-12]
        mask = pd.to_datetime(hourly.delivery_start_utc, utc=True) == index
        hourly.loc[mask, "price_eur_mwh"] = 99999
        second, _, _ = design_table(hourly)
        np.testing.assert_allclose(
            first.loc[index, cols].to_numpy(float), second.loc[index, cols].to_numpy(float)
        )
        self.assertNotIn("actual", cols)

    def test_d1_profile_is_earlier_local_day(self):
        hourly = generate_hourly(days=20)
        design, _, _ = design_table(hourly)
        row = design.iloc[-12]
        day = pd.Timestamp(row.delivery_date_local) - pd.Timedelta(days=1)
        raw = hourly.copy()
        local = pd.to_datetime(raw.delivery_start_utc, utc=True).dt.tz_convert("Europe/Berlin")
        expected = raw.loc[
            (local.dt.strftime("%Y-%m-%d") == day.strftime("%Y-%m-%d")) & (local.dt.hour == 0),
            "price_eur_mwh",
        ].iloc[0]
        self.assertEqual(row["price_d1_h00"], expected)

    def test_empirical_mode_requires_acknowledgement(self):
        with self.assertRaisesRegex(ValueError, "acknowledgement"):
            run(mode="empirical")


if __name__ == "__main__":
    unittest.main()
