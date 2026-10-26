import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pandas as pd

from transforms import AsinhTransform


class TransformTests(unittest.TestCase):
    def setUp(self):
        self.boundary = pd.Timestamp("2026-01-02", tz="UTC")
        self.training = pd.Series(
            [-100.0, -10.0, 0.0, 20.0, 1000.0],
            index=pd.date_range("2026-01-01", periods=5, freq="h", tz="UTC"),
            name="price_eur_mwh",
        )
        self.transformer = AsinhTransform.fit(self.training, training_end=self.boundary)

    def test_round_trip_negative_zero_spike(self):
        values = np.array([-1000.0, -1.0, 0.0, 1.0, 10000.0])
        restored = self.transformer.inverse_transform(self.transformer.transform(values))
        np.testing.assert_allclose(restored, values, atol=1e-10)

    def test_future_rows_cannot_enter_fit(self):
        extended = pd.concat([self.training, pd.Series([99999.0], index=[self.boundary])])
        with self.assertRaisesRegex(ValueError, "boundary"):
            AsinhTransform.fit(extended, training_end=self.boundary)

    def test_future_transformation_does_not_refit_parameters(self):
        before = (self.transformer.location, self.transformer.scale)
        self.transformer.transform([1e9])
        self.assertEqual(before, (self.transformer.location, self.transformer.scale))
        with self.assertRaises(FrozenInstanceError):
            self.transformer.scale = 10

    def test_constant_training_sample(self):
        fitted = AsinhTransform.fit(self.training * 0 + 25, training_end=self.boundary)
        np.testing.assert_allclose(fitted.transform([25, 25]), [0, 0])
        np.testing.assert_allclose(fitted.inverse_transform([0, 0]), [25, 25])

    def test_missing_data_rejected(self):
        broken = self.training.copy()
        broken.iloc[0] = np.nan
        with self.assertRaises(ValueError):
            AsinhTransform.fit(broken, training_end=self.boundary)

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            AsinhTransform.fit(self.training.tz_localize(None), training_end=self.boundary)
        with self.assertRaises(ValueError):
            AsinhTransform.fit(self.training, training_end="2026-01-02")

    def test_duplicate_dates_rejected(self):
        with self.assertRaises(ValueError):
            AsinhTransform.fit(
                pd.concat([self.training, self.training.iloc[:1]]), training_end=self.boundary
            )

    def test_save_load_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "transform.json"
            self.transformer.save(path)
            loaded = AsinhTransform.load(path)
            np.testing.assert_allclose(
                loaded.transform(self.training), self.transformer.transform(self.training)
            )
            with self.assertRaises(FileExistsError):
                loaded.save(path)

    def test_series_labels_preserved(self):
        result = self.transformer.transform(self.training)
        self.assertTrue(result.index.equals(self.training.index))
        self.assertEqual(result.name, self.training.name)

    def test_inverse_overflow_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "overflow"):
            self.transformer.inverse_transform([1000])

    def test_quantile_order_preserved(self):
        ordered = self.transformer.transform([-100, 0, 50, 1000])
        self.assertTrue((np.diff(ordered) > 0).all())


if __name__ == "__main__":
    unittest.main()
