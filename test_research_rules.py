"""Research-rule checks: trial accounting, corrections, strict gates and costs."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from research_audit import holm_adjust, inventory_runs
from run_pipeline import run
from sensitivity import evaluate_sensitivity, sensitivity_scenarios

BATTERY = {
    "power_mw": 1,
    "capacity_mwh": 4,
    "round_trip_efficiency": 0.9,
    "throughput_cost_eur_mwh": 2,
    "import_fee_eur_mwh": 0,
}


class TrialAccountingTests(unittest.TestCase):
    def test_holm_known_values_and_input_order(self):
        np.testing.assert_allclose(holm_adjust([0.04, 0.01, 0.03]), [0.06, 0.03, 0.06])
        self.assertEqual(holm_adjust([]), [])

    def test_holm_rejects_invalid_p_values(self):
        for values in ([float("nan")], [-0.1], [1.1]):
            with self.assertRaises(ValueError):
                holm_adjust(values)

    def test_repeated_tests_and_failures_are_counted_honestly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, status in (("first", "success"), ("repeat", "success"), ("failed", "failed")):
                folder = root / name
                folder.mkdir()
                (folder / "run.json").write_text(
                    json.dumps({"mode": "empirical", "status": status, "config": {"seed": 42}}),
                    encoding="utf-8",
                )
                if status == "success":
                    (folder / "results.json").write_text(
                        json.dumps(
                            {
                                "source_sha256": "same",
                                "source_code_sha256": {"models.py": "same"},
                                "forecast_days": ["2026-10-15"],
                                "dm_test": {"p_value": 0.03},
                            }
                        ),
                        encoding="utf-8",
                    )
            ledger, summary = inventory_runs(root)
        self.assertEqual(len(ledger), 3)
        self.assertEqual(summary["failed_executions"], 1)
        self.assertEqual(summary["distinct_empirical_test_signatures_with_p_values"], 1)
        self.assertFalse(summary["complete_lifetime_trial_count_known"])
        self.assertFalse(ledger.research_inference_permitted.any())

    def test_corrupt_manifest_is_reported_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "corrupt"
            folder.mkdir()
            (folder / "run.json").write_text("{", encoding="utf-8")
            _, summary = inventory_runs(Path(directory))
        self.assertEqual(summary["unreadable_manifests"][0]["run_id"], "corrupt")

    def test_strict_historical_gate_cannot_be_bypassed_by_acknowledgement(self):
        with self.assertRaisesRegex(ValueError, "Verified research run blocked"):
            run(mode="empirical", acknowledge=True, require_verified_vintages=True)


class SensitivityTests(unittest.TestCase):
    def test_scenarios_change_only_one_setting_and_include_baseline(self):
        scenarios = sensitivity_scenarios(BATTERY)
        self.assertEqual(len(scenarios), 10)
        self.assertEqual(scenarios[0], ("baseline", BATTERY))
        for _, settings in scenarios[1:]:
            self.assertEqual(sum(settings[key] != BATTERY[key] for key in BATTERY), 1)

    def test_matched_perfect_foresight_and_frozen_forecasts(self):
        prices = np.tile([-20.0, 100.0], 12)
        predictions = pd.DataFrame(
            {
                "actual": prices,
                "lear": prices,
                "lightgbm": prices,
                "naive": prices,
                "delivery_date_local": "2026-01-01",
                "delivery_start_utc": pd.date_range(
                    "2026-01-01", periods=24, freq="h", tz="UTC"
                ).astype(str),
            }
        )
        original = predictions.copy(deep=True)
        # Two real solver scenarios are enough to test the value contract cheaply.
        with patch(
            "sensitivity.sensitivity_scenarios",
            return_value=[
                ("baseline", BATTERY),
                ("expensive", dict(BATTERY, throughput_cost_eur_mwh=10)),
            ],
        ):
            result = evaluate_sensitivity(predictions, BATTERY)
        pd.testing.assert_frame_equal(predictions, original)
        self.assertTrue((result.net_eur <= result.perfect_foresight_net_eur + 1e-6).all())
        self.assertTrue((result.capture_fraction <= 1 + 1e-6).all())
        baseline = result.loc[
            (result.scenario == "baseline") & (result.model == "perfect_foresight"), "net_eur"
        ].iloc[0]
        expensive = result.loc[
            (result.scenario == "expensive") & (result.model == "perfect_foresight"), "net_eur"
        ].iloc[0]
        self.assertLessEqual(expensive, baseline)


class ResearchExportTests(unittest.TestCase):
    @staticmethod
    def request(path):
        from serve import Handler

        handler = object.__new__(Handler)
        handler.path = path
        handler.replies = []
        handler.reply = (
            lambda status, body, content_type="application/json": handler.replies.append(
                (status, body, content_type)
            )
        )
        return handler

    def test_ledger_download_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            research = project / "data" / "research"
            research.mkdir(parents=True)
            (research / "trial_ledger.csv").write_text("run_id\nexample\n", encoding="utf-8")
            with patch("serve.PROJECT", project):
                allowed = self.request("/api/research/download?file=trial_ledger.csv")
                allowed.do_GET()
                denied = self.request("/api/research/download?file=../../.env")
                denied.do_GET()
        self.assertEqual(allowed.replies[0][0], 200)
        self.assertIn(b"example", allowed.replies[0][1])
        self.assertNotEqual(denied.replies[0][0], 200)

    def test_old_run_sensitivity_supplement_can_be_downloaded(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            supplement = project / "data" / "sensitivity" / "example_supplement"
            supplement.mkdir(parents=True)
            (supplement / "sensitivity.csv").write_text("scenario\nbaseline\n", encoding="utf-8")
            with patch("serve.PROJECT", project):
                handler = self.request("/api/download?run=example&file=sensitivity.csv")
                handler.do_GET()
        self.assertEqual(handler.replies[0][0], 200)
        self.assertIn(b"baseline", handler.replies[0][1])


if __name__ == "__main__":
    unittest.main()
