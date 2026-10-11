"""Daily Brent spot observations from FRED or EIA (USD/barrel)."""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SERIES = "DCOILBRENTEU"
SOURCE_URL = "https://fred.stlouisfed.org/series/" + SERIES
EIA_URL = "https://www.eia.gov/dnav/pet/hist/RBRTED.htm"


def parse_brent_csv(text: str, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    observations = {}
    for row in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        try:
            observed = date.fromisoformat(row.get("observation_date") or row.get("DATE") or "")
            value = float(row.get(SERIES, ""))
        except (TypeError, ValueError):
            continue
        if observed <= today and math.isfinite(value) and value > 0:
            observations[observed] = value
    dates = sorted(observations)
    if len(dates) < 2:
        raise ValueError("Brent needs two valid daily observations")
    previous_date, current_date = dates[-2:]
    if (today - current_date).days > 10:
        raise ValueError("Brent observation is older than 10 days")
    if (current_date - previous_date).days > 7:
        raise ValueError("Brent observations are too far apart for a daily change")
    last, previous = observations[current_date], observations[previous_date]
    return {
        "last": last, "previous": previous,
        "pct": (last / previous - 1) * 100,
        "date": current_date.isoformat(),
        "previous_date": previous_date.isoformat(),
        "source": "EIA via FRED", "series": SERIES,
        "unit": "USD/barrel", "url": SOURCE_URL,
    }


class _TableRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            if self.row is not None:
                self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr":
            if self.row:
                self.rows.append(self.row)
            self.row, self.cell = None, None


def parse_brent_eia(text: str, today: date | None = None) -> dict:
    if "Europe Brent Spot Price FOB" not in text or "Dollars per Barrel" not in text:
        raise ValueError("EIA response is not the daily Brent spot table")
    table = _TableRows()
    table.feed(text)
    months = {name: i + 1 for i, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))}
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["observation_date", SERIES])
    for row in table.rows:
        if len(row) != 6:
            continue
        week = re.fullmatch(r"(\d{4})\s+([A-Z][a-z]{2})-\s*(\d{1,2})\s+to\s+([A-Z][a-z]{2})-\s*(\d{1,2})", row[0])
        if not week:
            continue
        year, month, day, end_month, end_day = week.groups()
        try:
            monday = date(int(year), months[month], int(day))
            friday = monday + timedelta(days=4)
            if monday.weekday() != 0 or (friday.month, friday.day) != (months[end_month], int(end_day)):
                continue
        except (KeyError, ValueError):
            continue
        for offset, value in enumerate(row[1:]):
            writer.writerow([(monday + timedelta(days=offset)).isoformat(), value])
    quote = parse_brent_csv(output.getvalue(), today=today)
    quote.update(source="EIA", series="RBRTE", url=EIA_URL)
    return quote


def fetch_brent() -> dict:
    now = datetime.now(timezone.utc)
    query = urlencode({"id": SERIES, "cosd": (now.date() - timedelta(days=45)).isoformat()})
    sources = [("FRED", "https://fred.stlouisfed.org/graph/fredgraph.csv?" + query, parse_brent_csv),
               ("EIA", EIA_URL, parse_brent_eia)]
    errors = []
    for name, url, parser in sources:
        try:
            request = Request(url, headers={"User-Agent": "deepsleep456-market-data/1.0"})
            with urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8-sig")
            quote = parser(text, today=now.date())
            quote["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            return quote
        except (OSError, ValueError) as error:
            errors.append(f"{name}: {type(error).__name__}: {error}")
    raise ValueError("; ".join(errors))
