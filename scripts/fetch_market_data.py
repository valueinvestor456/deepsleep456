"""Scrape US10Y / TH10Y / BDI / PMI (CN/TH/IN/US) from TradingEconomics and
write usd/market-data.json same-origin, so the dashboard (static GitHub
Pages, no backend) can auto-fill those fields without hitting TE's browser
CORS block.

Every TE indicator page ships a reliable server-rendered <meta id="metaDesc">
summary sentence (e.g. "Manufacturing PMI in China decreased to 51.70 points
in June...", "Baltic Dry rose to 2,944 Index Points ... up 1.17% from the
previous day", "... was last recorded at 3.75 percent") — parsing that one
sentence with two small regexes is far more robust across page TYPES (bond
yield / commodity / PMI / interest-rate all render differently in the body)
than chasing each page's HTML widget structure individually.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUT_PATH = Path(__file__).resolve().parent.parent / "usd" / "market-data.json"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

SOURCES = {
    "us10y": "https://tradingeconomics.com/united-states/government-bond-yield",
    "th10y": "https://tradingeconomics.com/thailand/government-bond-yield",
    "bdi": "https://tradingeconomics.com/commodity/baltic",
    "pmi_cn": "https://tradingeconomics.com/china/manufacturing-pmi",
    "pmi_th": "https://tradingeconomics.com/thailand/manufacturing-pmi",
    "pmi_in": "https://tradingeconomics.com/india/manufacturing-pmi",
    "pmi_us": "https://tradingeconomics.com/united-states/manufacturing-pmi",
}

# "... decreased to 51.70 points ..." / "... eased to 1.95% ..." / "... was last recorded at 3.75 percent"
LEVEL_RE = re.compile(r"(?:to|at)\s+([\d,]+(?:\.\d+)?)\s*(?:%|percent|points|Index Points)", re.IGNORECASE)
# "... up 1.17% from the previous day" / "... down 0.4% ..."
CHANGE_RE = re.compile(r"\b(up|down)\s+([\d.]+)%", re.IGNORECASE)


def scrape_meta(url: str) -> dict:
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    meta = soup.find("meta", id="metaDesc") or soup.find("meta", attrs={"name": "description"})
    if meta is None or not meta.get("content"):
        raise ValueError(f"no meta description found on {url}")
    desc = meta["content"]

    level_m = LEVEL_RE.search(desc)
    if level_m is None:
        raise ValueError(f"could not parse level from description: {desc!r}")
    last = float(level_m.group(1).replace(",", ""))

    pct = None
    change_m = CHANGE_RE.search(desc)
    if change_m is not None:
        sign = 1 if change_m.group(1).lower() == "up" else -1
        pct = sign * float(change_m.group(2))

    return {"last": last, "pct": pct}


def main():
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    for key, url in SOURCES.items():
        try:
            out[key] = scrape_meta(url)
            print(f"[ok] {key}: {out[key]}")
        except Exception as e:
            out[key] = None
            print(f"[FAIL -> null] {key}: {type(e).__name__}: {e}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out), encoding="utf-8")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
