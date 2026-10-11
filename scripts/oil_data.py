"""EIA daily Brent spot observations, distributed by FRED (USD/barrel)."""
from __future__ import annotations

import csv
import io
import math
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SERIES = "DCOILBRENTEU"
SOURCE_URL = "https://fred.stlouisfed.org/series/" + SERIES


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


def fetch_brent() -> dict:
    now = datetime.now(timezone.utc)
    query = urlencode({"id": SERIES, "cosd": (now.date() - timedelta(days=45)).isoformat()})
    request = Request("https://fred.stlouisfed.org/graph/fredgraph.csv?" + query,
                      headers={"User-Agent": "deepsleep456-market-data/1.0"})
    with urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8-sig")
    quote = parse_brent_csv(text, today=now.date())
    quote["fetched_at"] = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    return quote
