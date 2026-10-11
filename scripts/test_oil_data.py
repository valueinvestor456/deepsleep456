import unittest
from datetime import date
from oil_data import parse_brent_csv


class BrentTests(unittest.TestCase):
    def parse(self, rows, header="observation_date"):
        return parse_brent_csv(header + ",DCOILBRENTEU\n" + rows, today=date(2026, 10, 11))

    def test_missing_holiday_rows_are_skipped(self):
        quote = self.parse("2026-10-08,100\n2026-10-09,102\n2026-10-10,.\n")
        self.assertEqual(quote["last"], 102)
        self.assertEqual(quote["previous_date"], "2026-10-08")
        self.assertAlmostEqual(quote["pct"], 2)

    def test_old_date_header_and_unordered_data(self):
        quote = self.parse("2026-10-09,98\n2026-10-08,100\n", header="DATE")
        self.assertAlmostEqual(quote["pct"], -2)

    def test_bad_prices_and_future_dates_cannot_be_used(self):
        for value in ("NaN", "inf", "-1", "0", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse("2026-10-08,100\n2026-10-09," + value + "\n2026-10-12,110\n")

    def test_stale_and_widely_separated_observations_are_rejected(self):
        for rows in ("2026-09-01,100\n2026-09-02,102\n", "2026-09-01,100\n2026-10-09,102\n"):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.parse(rows)

    def test_html_error_is_not_a_price(self):
        with self.assertRaises(ValueError):
            parse_brent_csv("<html>Unavailable</html>", today=date(2026, 10, 11))


if __name__ == "__main__":
    unittest.main()
