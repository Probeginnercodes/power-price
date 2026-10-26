import unittest

import pandas as pd

from information_set import check_availability, cutoff_for_day


class InformationSetTests(unittest.TestCase):
    def test_future_publication_rejected(self):
        self.assertEqual(
            check_availability("2026-10-14T09:01Z", "2026-10-14T09:00Z", True), "too_late"
        )

    def test_exact_cutoff_rejected(self):
        self.assertEqual(
            check_availability("2026-10-14T09:00Z", "2026-10-14T09:00Z", True), "too_late"
        )

    def test_earlier_verified_vintage_allowed(self):
        self.assertEqual(
            check_availability("2026-10-14T08:59Z", "2026-10-14T09:00Z", True), "available"
        )

    def test_timestamp_alone_is_not_evidence(self):
        self.assertEqual(check_availability("2026-10-14T08:00Z", "2026-10-14T09:00Z"), "unverified")

    def test_missing_publication_remains_unverified(self):
        self.assertEqual(check_availability(None, "2026-10-14T09:00Z"), "unverified")

    def test_naive_evidence_rejected(self):
        with self.assertRaises(ValueError):
            check_availability("2026-10-14T08:00", "2026-10-14T09:00Z", True)

    def test_cutoff_uses_previous_local_date_across_dst(self):
        self.assertEqual(cutoff_for_day("2024-10-28"), pd.Timestamp("2024-10-27T10:00Z"))
        self.assertEqual(cutoff_for_day("2024-04-01"), pd.Timestamp("2024-03-31T09:00Z"))


if __name__ == "__main__":
    unittest.main()
