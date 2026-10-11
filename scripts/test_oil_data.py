import unittest
from datetime import date
from unittest.mock import patch, MagicMock
from oil_data import parse_brent_csv, parse_brent_eia, fetch_brent


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

    def eia_html(self, week="2026 Oct- 5 to Oct- 9", values=("100", "102", "", "", "")):
        return "<title>Europe Brent Spot Price FOB (Dollars per Barrel)</title><table><tr><td>" + week + \
            "</td>" + "".join("<td>" + value + "</td>" for value in values) + "</tr></table>"

    def test_eia_holidays_keep_their_calendar_positions(self):
        quote = parse_brent_eia(self.eia_html(values=("100", "", "102", "", "")), today=date(2026, 10, 11))
        self.assertEqual(quote["date"], "2026-10-07")
        self.assertEqual(quote["previous_date"], "2026-10-05")
        self.assertEqual(quote["source"], "EIA")

    def test_eia_week_crossing_year_boundary(self):
        quote = parse_brent_eia(self.eia_html("2025 Dec-29 to Jan- 2", ("98", "99", "100", "", "102")),
                                today=date(2026, 1, 4))
        self.assertEqual(quote["date"], "2026-01-02")
        self.assertEqual(quote["previous_date"], "2025-12-31")

    def test_eia_rejects_wrong_series_invalid_week_and_stale_data(self):
        for html in (self.eia_html().replace("Europe Brent", "WTI"),
                     self.eia_html("2026 Oct- 6 to Oct- 9"), self.eia_html("2026 Sep- 7 to Sep-11")):
            with self.subTest(html=html), self.assertRaises(ValueError):
                parse_brent_eia(html, today=date(2026, 10, 11))

    def test_network_timeout_falls_back_to_eia(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"EIA fixture"
        with patch("oil_data.urlopen", side_effect=[TimeoutError("timed out"), response]) as request, \
             patch("oil_data.parse_brent_eia", return_value={"source": "EIA"}):
            quote = fetch_brent()
        self.assertEqual(quote["source"], "EIA")
        self.assertIn("fetched_at", quote)
        self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
