import unittest
from datetime import date
from gold_flow_data import parse_gold_trade


def table(label, values, periods=("AUG 2026", "JUL 2026 r"), section="Exports", unit="Millions of Baht"):
    return '<span id="lblUOQ">'+unit+'</span><table><tr><th></th><th></th>'+''.join('<th>'+p+'</th>' for p in periods)+\
        '</tr><tr><td>1</td><td>'+section+'</td><td>999999</td></tr><tr><td>2</td><td>'+label+'</td>'+\
        ''.join('<td>'+v+'</td>' for v in values)+'</tr></table>'


class GoldTradeTests(unittest.TestCase):
    def setUp(self):
        self.exports = table('Non-monetary gold (excl. articles of goldsmiths)', ['79,142.45','13,692.45'])
        self.imports = table('Gold', ['61,350.64','33,979.70'], section='Imports')

    def test_net_exports_and_shared_month(self):
        quote = parse_gold_trade(self.exports,self.imports,date(2026,10,11))
        self.assertEqual(quote['period'],'2026-08')
        self.assertEqual(quote['net_exports_m_thb'],17791.81)
        self.assertIs(quote['proxy'],True)

    def test_header_alignment_prevents_mixing_different_months(self):
        imports = table('Gold',['1','61,350.64'],periods=('SEP 2026','AUG 2026'),section='Imports')
        quote = parse_gold_trade(self.exports,imports,date(2026,10,11))
        self.assertEqual(quote['period'],'2026-08')
        self.assertEqual(quote['imports_m_thb'],61350.64)

    def test_missing_values_are_not_zero_and_units_must_match(self):
        for imports in (self.imports.replace('61,350.64','NA').replace('33,979.70','NA'),
                        self.imports.replace('Millions of Baht','Millions of US Dollar'),
                        self.imports.replace('Imports','Exports')):
            with self.subTest(imports=imports),self.assertRaises(ValueError):
                parse_gold_trade(self.exports,imports,date(2026,10,11))

    def test_future_or_stale_months_are_rejected(self):
        for today in (date(2026,7,1),date(2027,1,1)):
            with self.subTest(today=today),self.assertRaises(ValueError):
                parse_gold_trade(self.exports,self.imports,today)


if __name__ == '__main__':
    unittest.main()
