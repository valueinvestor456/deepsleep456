"""Public daily FX/bond data and monthly BOT current account, with dated observations."""
from __future__ import annotations

import calendar
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen
from gold_flow_data import MONTHS, _BotTable

ACCOUNT_URL = 'https://app.bot.or.th/BTWS_STAT/statistics/BOTWEBSTAT.aspx?language=eng&reportID=1028'
BOND_URL = 'https://www.thaibma.or.th/nrdaily/GetNR/'
FX_URL = 'https://api.frankfurter.dev/v2/providers/ecb/rates'


def _get(url):
    with urlopen(Request(url, headers={'User-Agent': 'deepsleep456-market-data/1.0'}), timeout=30) as response:
        return response.read().decode('utf-8-sig')


def _number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('Missing/invalid number')
    value = float(str(value).replace(',', ''))
    if not math.isfinite(value):
        raise ValueError('Nonfinite number')
    return value


def parse_current_account(text, today=None):
    today = today or datetime.now(timezone.utc).date()
    table = _BotTable()
    table.feed(text)
    if 'Millions of US Dollars' not in table.metadata.get('lblUOQ', ''):
        raise ValueError('Current account must be in millions of USD')
    periods, observations = {}, {}
    for row in table.rows:
        if len(row) < 3:
            continue
        if re.fullmatch(r'[A-Z]{3} \d{4}(?: [a-z])?', row[2]):
            periods = {}
            for column, value in enumerate(row[2:], 2):
                m = re.fullmatch(r'([A-Z]{3}) (\d{4})(?: [a-z])?', value)
                if m and m[1] in MONTHS:
                    periods[column] = f'{int(m[2]):04d}-{MONTHS[m[1]]:02d}'
        elif row[1].lower() == 'current account balance':
            for column, period in periods.items():
                try:
                    year, month = map(int, period.split('-'))
                    end = date(year, month, calendar.monthrange(year, month)[1])
                    value = _number(row[column])
                except (ValueError, IndexError):
                    continue
                if 0 <= (today-end).days < 90:
                    observations[period] = value
    if not observations:
        raise ValueError('No completed current-account period within 90 days')
    period = max(observations)
    return {'period': period, 'value_m_usd': observations[period], 'unit': 'million_USD',
            'source': 'Bank of Thailand', 'series': 'EC_XT_047_S3', 'url': ACCOUNT_URL,
            'published': table.metadata.get('lblLastUpdateDate', '')}


def parse_bond_flow(payload, today=None):
    today = today or datetime.now(timezone.utc).date()
    if not isinstance(payload, list):
        raise ValueError('Unexpected ThaiBMA response')
    observations = {}
    for row in payload:
        try:
            stamp = date.fromisoformat(row['Asof'][:10])
            net = _number(row['NetFlow'])
        except (ValueError, KeyError, TypeError):
            continue
        if 0 <= (today-stamp).days < 10:
            observations[stamp] = net
    if not observations:
        raise ValueError('No fresh ThaiBMA net flow')
    stamp = max(observations)
    return {'date': stamp.isoformat(), 'net_m_thb': observations[stamp], 'unit': 'million_THB',
            'source': 'ThaiBMA', 'measure': 'NetFlow (trades less redemptions)',
            'url': 'https://www.thaibma.or.th/EN/Market/NR/NRDaily.aspx'}


def parse_dxy(payload, today=None):
    today = today or datetime.now(timezone.utc).date()
    weights = {'EUR': .576, 'JPY': .136, 'GBP': .119, 'CAD': .091, 'SEK': .042, 'CHF': .036}
    grouped = {}
    if not isinstance(payload, list):
        raise ValueError('Unexpected ECB FX response')
    for row in payload:
        try:
            stamp = date.fromisoformat(row['date'])
            rate = _number(row['rate'])
            currency = row['quote']
            if row['base'] != 'USD' or currency not in weights or rate <= 0 or stamp > today:
                continue
        except (ValueError, KeyError, TypeError):
            continue
        grouped.setdefault(stamp, {})[currency] = rate
    complete = sorted(stamp for stamp, rates in grouped.items() if all(key in rates for key in weights))
    if len(complete) < 2:
        raise ValueError('Synthetic DXY needs all six currencies on two dates')
    before, stamp = complete[-2:]
    if (today-stamp).days >= 10 or (stamp-before).days > 7:
        raise ValueError('Stale or discontinuous ECB FX pair')
    def index(on):
        value = 50.14348112
        for key, weight in weights.items():
            value *= grouped[on][key] ** weight
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid synthetic DXY')
        return value
    last, previous = index(stamp), index(before)
    return {'last': last, 'previous': previous, 'pct': (last/previous-1)*100,
            'date': stamp.isoformat(), 'previous_date': before.isoformat(),
            'source': 'ECB via Frankfurter', 'synthetic': True, 'url': 'https://frankfurter.dev/'}


def fetch_current_account():
    return parse_current_account(_get(ACCOUNT_URL))


def fetch_foreign_flow():
    # The public SET endpoint denied access (HTTP 403). Never fabricate a stock total.
    return {'stocks': None, 'bonds': parse_bond_flow(json.loads(_get(BOND_URL))),
            'stock_status': 'SET feed unavailable; bond market only'}


def fetch_dxy():
    today = datetime.now(timezone.utc).date()
    url = (FX_URL+'?base=USD&quotes=EUR,JPY,GBP,CAD,SEK,CHF'
           +'&from='+(today-timedelta(days=14)).isoformat()+'&to='+today.isoformat())
    return parse_dxy(json.loads(_get(url)), today)
