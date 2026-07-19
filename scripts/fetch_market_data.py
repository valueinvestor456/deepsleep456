"""Scrape US10Y / TH10Y / BDI / PMI (CN/TH/IN/US) / BDRY from TradingEconomics
+ Yahoo Finance and write usd/market-data.json same-origin, so the dashboard
(static GitHub Pages, no backend) can auto-fill those fields without hitting
CORS blocks (TE sends no CORS header at all; Yahoo's chart API sends `vary:
Origin` but no Access-Control-Allow-Origin, so browsers block it too).

Every TE indicator page ships a reliable server-rendered <meta id="metaDesc">
summary sentence (e.g. "Manufacturing PMI in China decreased to 51.70 points
in June...", "Baltic Dry rose to 2,944 Index Points ... up 1.17% from the
previous day", "... was last recorded at 3.75 percent") — parsing that one
sentence with two small regexes is far more robust across page TYPES (bond
yield / commodity / PMI / interest-rate all render differently in the body)
than chasing each page's HTML widget structure individually.

BDRY (Breakwave Dry Bulk Shipping ETF, NYSE Arca) is a market-traded proxy
for the same freight-rate signal as BDI, but updates intraday during US
market hours instead of once/day — fetched via yfinance (already proven
reliable for DXY/Gold/US10Y/USDTHB tickers in the macro-telegram-bot project).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
import yfinance as yf
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
    "th_rate": "https://tradingeconomics.com/thailand/interest-rate",
    "us_rate": "https://tradingeconomics.com/united-states/interest-rate",  # Fed Funds Rate, proxy for SOFR
    "th_cpi": "https://tradingeconomics.com/thailand/consumer-price-index-cpi",
    "us_cpi": "https://tradingeconomics.com/united-states/consumer-price-index-cpi",
}

# "... decreased to 51.70 points ..." / "... eased to 1.95% ..." / "... was last recorded at 3.75 percent"
LEVEL_RE = re.compile(r"(?:to|at)\s+([\d,]+(?:\.\d+)?)\s*(?:%|percent|points|Index Points)", re.IGNORECASE)
# "... up 1.17% from the previous day" / "... down 0.4% ..."
CHANGE_RE = re.compile(r"\b(up|down)\s+([\d.]+)%", re.IGNORECASE)
# monthly indicators (PMI/CPI): "... to 51.70 points in June from 51.80 points in May of 2026."
MOM_RE = re.compile(r"in (\w+) from ([\d,]+(?:\.\d+)?)\s*(?:points|percent)?\s+in (\w+)", re.IGNORECASE)
VERB_RE = re.compile(r"\b(increased|decreased|rose|fell|eased|climbed|dropped|edged up|edged down)\b", re.IGNORECASE)


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

    out = {"last": last, "pct": pct}

    # month-over-month, when the source sentence has it (PMI/CPI-style pages)
    mom_m = MOM_RE.search(desc)
    verb_m = VERB_RE.search(desc)
    if mom_m is not None:
        prev = float(mom_m.group(2).replace(",", ""))
        out["mom"] = {
            "prev": prev,
            "delta": round(last - prev, 4),
            "cur_month": mom_m.group(1),
            "prev_month": mom_m.group(3),
            "direction": "up" if (verb_m and verb_m.group(1).lower() in
                ("increased", "rose", "climbed", "edged up")) else "down",
        }
    return out


def fetch_bdry() -> dict:
    hist = yf.Ticker("BDRY").history(period="5d")
    if len(hist) < 2:
        raise ValueError(f"BDRY: got {len(hist)} rows, need >= 2")
    last = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2])
    return {"last": last, "pct": (last / prev - 1.0) * 100.0}


def fetch_usdthb_trend() -> dict:
    """EMA(20)/EMA(50) trend filter used as a USD1! (TFEX USD futures
    continuous contract) proxy on the dashboard -- there's no free API for
    TFEX futures themselves, but the price tracks USD/THB spot closely via
    CIP arbitrage, so this uses THB=X daily closes instead. Trend direction
    is the EMA20-vs-EMA50 crossover (the two numbers alone tell the story --
    EMA20 above EMA50 means the shorter-term average is pulling up = uptrend)."""
    hist = yf.Ticker("THB=X").history(period="6mo")
    if len(hist) < 55:
        raise ValueError(f"THB=X: got {len(hist)} rows, need >= 55 for EMA50")
    closes = hist["Close"]
    ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
    return {
        "close": float(closes.iloc[-1]),
        "ema20": ema20,
        "ema50": ema50,
        "direction": "up" if ema20 > ema50 else "down",
    }


def main():
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    for key, url in SOURCES.items():
        try:
            out[key] = scrape_meta(url)
            print(f"[ok] {key}: {out[key]}")
        except Exception as e:
            out[key] = None
            print(f"[FAIL -> null] {key}: {type(e).__name__}: {e}")

    try:
        out["bdry"] = fetch_bdry()
        print(f"[ok] bdry: {out['bdry']}")
    except Exception as e:
        out["bdry"] = None
        print(f"[FAIL -> null] bdry: {type(e).__name__}: {e}")

    try:
        out["usdthb_trend"] = fetch_usdthb_trend()
        print(f"[ok] usdthb_trend: {out['usdthb_trend']}")
    except Exception as e:
        out["usdthb_trend"] = None
        print(f"[FAIL -> null] usdthb_trend: {type(e).__name__}: {e}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out), encoding="utf-8")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
