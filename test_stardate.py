import unittest
from datetime import datetime, timezone

import stardate


class StardateTests(unittest.TestCase):
    def test_compute_stardate_for_2026_start_of_year(self):
        dt = datetime(2026, 1, 1, 0, 0)
        adjusted_year, value = stardate.compute_stardate(dt, offset_years=347)
        self.assertEqual(adjusted_year, 2373)
        self.assertAlmostEqual(value, 50000.0, places=6)

    def test_compute_stardate_midyear_fraction(self):
        dt = datetime(2026, 7, 2, 12, 0)
        _, value = stardate.compute_stardate(dt, offset_years=347)
        self.assertGreater(value, 50000.0)
        self.assertLess(value, 51000.0)

    def test_build_personal_reference_with_color_and_tag(self):
        expected = "(stardate: 50000.0) [Purple / Project]"
        self.assertEqual(
            stardate.build_personal_reference("50000.0", color="Purple", tag="Project"),
            expected,
        )

    def test_build_personal_reference_with_color_only(self):
        expected = "(stardate: 50000.0) [Purple]"
        self.assertEqual(
            stardate.build_personal_reference("50000.0", color="Purple", tag=None),
            expected,
        )

    def test_build_personal_reference_with_tag_only(self):
        expected = "(stardate: 50000.0) [Project]"
        self.assertEqual(
            stardate.build_personal_reference("50000.0", color=None, tag="Project"),
            expected,
        )

    def test_parse_date_rejects_invalid_format(self):
        with self.assertRaises(Exception):
            stardate.parse_date("2026/06/07")

    def test_parse_precision_rejects_negative_values(self):
        with self.assertRaises(Exception):
            stardate.parse_precision("-1")

    def test_parse_offset_years_rejects_non_integer(self):
        with self.assertRaises(Exception):
            stardate.parse_offset_years("three")

    def test_compute_stardate_utc_aware_datetime(self):
        dt = datetime(2026, 6, 7, 21, 14, tzinfo=timezone.utc)
        adjusted_year, value = stardate.compute_stardate(dt, offset_years=347)
        self.assertEqual(adjusted_year, 2373)
        self.assertGreater(value, 50430.0)
        self.assertLess(value, 50435.0)


if __name__ == "__main__":
    unittest.main()
