import unittest
from datetime import date
from auto_signal_data import parse_current_account, parse_bond_flow, parse_dxy

TODAY = date(2026, 10, 11)


class AutoSignalsTests(unittest.TestCase):
    def test_account_exact_row_units_and_current_period(self):
        html = '<span id="lblUOQ">Millions of US Dollars</span><table><tr><th></th><th></th><th>AUG 2026 p</th><th>JUL 2026 p</th></tr><tr><td>3</td><td>Trade balance</td><td>999</td><td>999</td></tr><tr><td>5</td><td>Current account balance</td><td>-2,351.78</td><td>698.03</td></tr></table>'
        self.assertEqual(parse_current_account(html, TODAY)['value_m_usd'], -2351.78)
        for invalid in (html.replace('US Dollars', 'Baht'), html.replace('2026', '2020'), html.replace('AUG 2026 p', 'DEC 2026 p').replace('JUL 2026 p', 'NOV 2026 p')):
            with self.assertRaises(ValueError):
                parse_current_account(invalid, TODAY)

    def test_bonds_use_net_flow_not_net_trade_and_accept_explicit_zero(self):
        rows = [{'Asof': '2026-10-09T00:00:00', 'NetFlow': -20, 'TotalNetTrade': 80},
                {'Asof': '2026-10-08T00:00:00', 'NetFlow': 0}]
        self.assertEqual(parse_bond_flow(rows, TODAY)['net_m_thb'], -20)
        self.assertEqual(parse_bond_flow(rows[1:], TODAY)['net_m_thb'], 0)
        for value in (None, '', False, float('nan')):
            with self.assertRaises(ValueError):
                parse_bond_flow([{'Asof': '2026-10-09', 'NetFlow': value}], TODAY)

    def test_dxy_needs_complete_matching_dates_and_uses_correct_direction(self):
        rates = {'EUR': .9, 'JPY': 150, 'GBP': .8, 'CAD': 1.3, 'SEK': 10, 'CHF': .9}
        rows = [{'base':'USD', 'date':stamp, 'quote':key, 'rate':value*mult}
                for stamp, mult in [('2026-10-08',1), ('2026-10-09',1.01)] for key,value in rates.items()]
        self.assertAlmostEqual(parse_dxy(rows, TODAY)['pct'], 1, places=8)
        for invalid in (rows[:-1], [{**r, 'date':r['date'].replace('2026','2020')} for r in rows]):
            with self.assertRaises(ValueError):
                parse_dxy(invalid, TODAY)


if __name__ == '__main__':
    unittest.main()
