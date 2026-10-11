"""Daily US two-year Treasury par yield, in percent (not the ten-year yield)."""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from urllib.request import Request, urlopen

TREASURY_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
NS = {"m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
      "d": "http://schemas.microsoft.com/ado/2007/08/dataservices"}


def parse_us2(xmls: list[str], today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    observations = {}
    for text in xmls:
        for row in ET.fromstring(text).findall(".//m:properties", NS):
            try:
                observed = date.fromisoformat(row.findtext("d:NEW_DATE", "", NS)[:10])
                value = float(row.findtext("d:BC_2YEAR", "", NS))
            except (ValueError, TypeError):
                continue
            if observed <= today and math.isfinite(value):
                observations[observed] = value
    dates = sorted(observations)
    if len(dates) < 2:
        raise ValueError("US 2Y needs two daily observations")
    previous_date, current_date = dates[-2:]
    if (today - current_date).days > 10 or (current_date - previous_date).days > 7:
        raise ValueError("US 2Y observations are stale or too far apart")
    last, previous = observations[current_date], observations[previous_date]
    return {"last": last, "previous": previous, "change_bps": (last - previous) * 100,
            "date": current_date.isoformat(), "previous_date": previous_date.isoformat(),
            "source": "U.S. Treasury", "unit": "%", "series": "BC_2YEAR"}


def fetch_us2() -> dict:
    now = datetime.now(timezone.utc)
    xmls = []
    # Early January may have fewer than two observations in the current year.
    years = [now.year - 1, now.year] if now.month == 1 and now.day <= 10 else [now.year]
    for year in years:
        url = TREASURY_URL + f"?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
        request = Request(url, headers={"User-Agent": "deepsleep456-market-data/1.0"})
        with urlopen(request, timeout=30) as response:
            xmls.append(response.read().decode("utf-8-sig"))
    quote = parse_us2(xmls, today=now.date())
    quote.update(url=url, fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
    return quote
