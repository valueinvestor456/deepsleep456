"""Monthly Thai gold trade proxy; this is not observed dealer FX/hedging flow."""
from __future__ import annotations

import calendar
import math
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib.request import Request, urlopen

EXPORT_URL = "https://app.bot.or.th/BTWS_STAT/statistics/BOTWEBSTAT.aspx?language=eng&reportID=978"
IMPORT_URL = "https://app.bot.or.th/BTWS_STAT/statistics/BOTWEBSTAT.aspx?language=eng&reportID=50"
MONTHS = {name: i+1 for i, name in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}


class _BotTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None
        self.metadata, self.meta_key, self.meta_text = {}, None, []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "span" and dict(attrs).get("id") in ("lblUOQ", "lblLastUpdateDate"):
            self.meta_key, self.meta_text = dict(attrs)["id"], []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        if self.meta_key:
            self.meta_text.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            if self.row is not None:
                self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr":
            if self.row:
                self.rows.append(self.row)
            self.row, self.cell = None, None
        elif tag == "span" and self.meta_key:
            self.metadata[self.meta_key] = " ".join("".join(self.meta_text).split())
            self.meta_key, self.meta_text = None, []


def _monthly_gold(text: str, exports: bool) -> tuple[dict, str]:
    parser = _BotTable()
    parser.feed(text)
    if "Millions of Baht" not in parser.metadata.get("lblUOQ", ""):
        raise ValueError("Unexpected BOT gold trade units")
    periods, observations, section = {}, {}, None
    for row in parser.rows:
        if len(row) < 3:
            continue
        if re.fullmatch(r"[A-Z]{3} \d{4}(?: [a-z])?", row[2]):
            periods = {}
            for column, label in enumerate(row[2:], 2):
                match = re.fullmatch(r"([A-Z]{3}) (\d{4})(?: [a-z])?", label)
                if match and match[1] in MONTHS:
                    periods[column] = f"{int(match[2]):04d}-{MONTHS[match[1]]:02d}"
            continue
        label = row[1].lower()
        if label in ("exports", "imports"):
            section = label
        wanted = label == "non-monetary gold (excl. articles of goldsmiths)" if exports else label == "gold" and section == "imports"
        if not wanted:
            continue
        for column, period in periods.items():
            if column >= len(row):
                continue
            try:
                value = float(row[column].replace(",", ""))
            except ValueError:
                continue
            if math.isfinite(value) and value >= 0:
                observations[period] = value
    if not observations:
        raise ValueError("BOT gold row has no valid monthly observations")
    return observations, parser.metadata.get("lblLastUpdateDate", "")


def parse_gold_trade(exports_html: str, imports_html: str, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    exports, exports_updated = _monthly_gold(exports_html, True)
    imports, imports_updated = _monthly_gold(imports_html, False)
    eligible = []
    for period in exports.keys() & imports.keys():
        year, month = map(int, period.split("-"))
        period_end = date(year, month, calendar.monthrange(year, month)[1])
        if 0 <= (today - period_end).days <= 90:
            eligible.append(period)
    if not eligible:
        raise ValueError("Gold trade needs a shared, completed monthly period no more than 90 days old")
    period = max(eligible)
    return {"period": period, "exports_m_thb": exports[period], "imports_m_thb": imports[period],
            "net_exports_m_thb": round(exports[period]-imports[period], 2), "unit": "million_THB",
            "source": "Thai Customs / Bank of Thailand", "proxy": True,
            "exports_updated": exports_updated, "imports_updated": imports_updated,
            "export_url": EXPORT_URL, "import_url": IMPORT_URL}


def fetch_gold_trade() -> dict:
    pages = []
    for url in (EXPORT_URL, IMPORT_URL):
        request = Request(url, headers={"User-Agent": "deepsleep456-market-data/1.0"})
        with urlopen(request, timeout=30) as response:
            pages.append(response.read().decode("utf-8-sig"))
    quote = parse_gold_trade(*pages)
    quote["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return quote
