import unittest
from datetime import date
from signal_data import parse_us2


def feed(rows):
    return '<feed xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">' + ''.join(
        '<m:properties><d:NEW_DATE>' + day + 'T00:00:00</d:NEW_DATE><d:BC_2YEAR>' + value +
        '</d:BC_2YEAR><d:BC_10YEAR>9.99</d:BC_10YEAR></m:properties>' for day, value in rows) + '</feed>'


class YieldTests(unittest.TestCase):
    def test_two_year_column_and_basis_points(self):
        quote = parse_us2([feed([('2026-10-09', '4.80'), ('2026-10-08', '4.75')])], date(2026, 10, 11))
        self.assertEqual(quote['last'], 4.80)
        self.assertAlmostEqual(quote['change_bps'], 5)

    def test_year_boundary_and_missing_holiday(self):
        quote = parse_us2([feed([('2025-12-31', '3.50')]), feed([('2026-01-01', ''), ('2026-01-02', '3.40')])], date(2026, 1, 4))
        self.assertEqual(quote['previous_date'], '2025-12-31')
        self.assertAlmostEqual(quote['change_bps'], -10)

    def test_stale_future_missing_and_infinite_data(self):
        for rows in [[('2026-09-01','4'),('2026-09-02','5')], [('2026-10-08','4'),('2026-10-12','5')],
                     [('2026-10-08','4'),('2026-10-09','NaN')], [('2026-10-08','4'),('2026-10-09','inf')]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                parse_us2([feed(rows)], date(2026, 10, 11))


if __name__ == '__main__':
    unittest.main()
