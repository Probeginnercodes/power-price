"""Refactor contracts: configuration, scoring, artefact compatibility and leakage."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from battery import dispatch
from configuration import load_config, validate_config
from evaluation import evaluate, pinball
from models import design_table, forecast_day
from run_pipeline import source_dataset
from serve import launch
from synthetic_data import generate_hourly

PROJECT = Path(__file__).resolve().parent


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8-sig"))

    def test_default_configuration_is_supported(self):
        validate_config(self.config)

    def test_unsupported_quantile_sets_are_rejected(self):
        for quantiles in ([0.9, 0.5, 0.1], [0.1, 0.9], [0.2, 0.5, 0.8]):
            with self.subTest(quantiles=quantiles), self.assertRaises(ValueError):
                validate_config(dict(self.config, quantiles=quantiles))

    def test_nonfinite_physical_settings_are_rejected(self):
        for name in self.config["battery"]:
            for value in (float("nan"), float("inf")):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    dispatch([10, 100], dict(self.config["battery"], **{name: value}))

    def test_noninteger_windows_and_unknown_keys_are_rejected(self):
        for override in (
            {"training_days": 364.5},
            {"evaluation_days": True},
            {"trainig_days": 364},
        ):
            with self.subTest(override=override), self.assertRaises(ValueError):
                validate_config(dict(self.config, **override))

    def test_invalid_calibration_split_and_alpha_are_rejected(self):
        for override in (
            {"calibration_days": 350},
            {"lasso_alphas": []},
            {"lasso_alphas": [float("nan")]},
        ):
            with self.subTest(override=override), self.assertRaises(ValueError):
                validate_config(dict(self.config, **override))

    def test_run_overrides_are_validated(self):
        with self.assertRaises(ValueError):
            load_config(PROJECT / "config.json", training_days=364, evaluation_days=0)

    def test_config_validation_does_not_mutate_input(self):
        original = copy.deepcopy(self.config)
        validate_config(self.config)
        self.assertEqual(self.config, original)


class ScoringContractTests(unittest.TestCase):
    def test_pinball_rejects_silent_broadcasting_and_nonfinite_data(self):
        for actual, forecast in (([1, 2], [1]), ([float("nan")], [1])):
            with self.assertRaises(ValueError):
                pinball(actual, forecast, 0.5)

    def test_hourly_rmse_uses_same_original_scale_as_overall_metrics(self):
        rows = pd.DataFrame(
            {
                "actual": [0, 4],
                "lear": [1, 1],
                "lightgbm": [1, 1],
                "naive": [1, 1],
                "hour_local": [1, 1],
                "delivery_date_local": ["2026-01-01", "2026-01-02"],
            }
        )
        for model in ("lear", "lightgbm"):
            for quantile in (10, 50, 90):
                rows[f"{model}_q{quantile}"] = 1
        overall, _, hourly, _ = evaluate(rows)
        self.assertAlmostEqual(hourly.loc[0, "rmse"], np.sqrt(5))
        self.assertAlmostEqual(hourly.loc[0, "rmse"], overall.loc[0, "rmse"])

    def test_empty_evaluation_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate(pd.DataFrame())

    def test_non_object_job_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            launch([])

    def test_explicit_processed_run_cannot_escape_dataset_directory(self):
        with self.assertRaises(ValueError):
            source_dataset("../outside")


class ModelLeakageTests(unittest.TestCase):
    def test_observed_test_prices_do_not_change_predictions(self):
        """Changing only held-out outcomes must not change fitted forecasts."""
        config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8-sig"))
        design, columns, _ = design_table(generate_hourly(days=140))
        forecast_date = design.delivery_date_local.max()
        training = design.loc[design.delivery_date_local < forecast_date]
        forecast_rows = design.loc[design.delivery_date_local == forecast_date].copy()
        with tempfile.TemporaryDirectory() as directory:
            original, _ = forecast_day(
                training, forecast_rows, columns, config, Path(directory) / "original"
            )
            forecast_rows["actual"] = 99999.0
            changed, _ = forecast_day(
                training, forecast_rows, columns, config, Path(directory) / "changed"
            )
        forecast_columns = [
            name for name in original if name.startswith(("lear", "lightgbm", "naive"))
        ]
        np.testing.assert_allclose(
            original[forecast_columns], changed[forecast_columns], rtol=0, atol=0
        )


if __name__ == "__main__":
    unittest.main()
