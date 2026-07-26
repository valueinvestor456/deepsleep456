#!/usr/bin/env python3
"""
US-equity leading-indicator scan for dashboard/index.html, run as a single-shot
batch job from GitHub Actions every 30 min during US market hours (see
.github/workflows/dashboard-scan.yml -- unlike scripts/dr_scan/scan_and_publish.py
this does NOT loop internally; the workflow's cron provides the cadence).

For every ticker in watchlist.json: fetches 1y daily price history (Yahoo
v8/chart, same endpoint/pattern as scripts/dr_scan/wave_analysis.py's
fetch_history) to compute price/52-wk range/SMA50/SMA200/RSI14, and fetches
quoteSummary (same cookie+crumb mechanics as scripts/dr_scan/
fundamentals_analysis.py's fetch_quotesummary/analyze_ticker, reused directly)
for fundamentals + analyst sentiment.

Deliberately does NOT attempt to generate the qualitative "hero" narrative
(what ARR/capex/growth story matters right now) -- same reasoning as
fundamentals_analysis.py's docstring: that requires reading actual earnings
calls/news, which a generic API cannot respond with, and a scripted attempt
would produce false-confidence prose. Instead narrative_overrides.json is a
manually-curated optional layer: tickers present there get a hero section +
story + extra sector-specific tiles; tickers without an entry get the auto
quantitative matrix only (technical + fundamentals + analyst sentiment), with
the page explicitly noting no curated narrative exists yet.

All badges (good/warn/serious/critical) are deterministic threshold labels on
raw numbers, not a judgment call -- same "not a rating" honesty as
fundamentals_analysis.py's peer-percentile bucket tag.
"""
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DR_SCAN_DIR = os.path.join(REPO_DIR, "scripts", "dr_scan")
sys.path.insert(0, DR_SCAN_DIR)
import json as _json
import urllib.error
import urllib.request

from scan_and_publish import fetch, HEADERS  # reuse existing HTTP helper + headers
from fundamentals_analysis import _get_crumb, _opener, _raw  # reuse cookie+crumb session

# Same modules as fundamentals_analysis.py's QUOTESUMMARY_MODULES, plus "price"
# for company name/exchange -- fetch_quotesummary() there is hardcoded to the
# narrower module list, so this is a local variant reusing its crumb/opener
# rather than modifying a file the live DR cron also depends on.
QUOTESUMMARY_MODULES_EXT = "financialData,defaultKeyStatistics,summaryDetail,price"


def fetch_quotesummary(ticker):
    for attempt in range(2):
        crumb = _get_crumb()
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules={QUOTESUMMARY_MODULES_EXT}&crumb={crumb}"
        try:
            resp = _opener.open(urllib.request.Request(url, headers=HEADERS), timeout=20)
            raw = resp.read().decode("utf-8", errors="replace")
            data = _json.loads(raw)
            result = data.get("quoteSummary", {}).get("result")
            return result[0] if result else None
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(5)
                continue
            if e.code == 401 and attempt == 0:
                import fundamentals_analysis
                fundamentals_analysis._crumb = None
                continue
            return None
        except Exception:
            return None
    return None

WATCHLIST_PATH = os.path.join(SCRIPT_DIR, "watchlist.json")
OVERRIDES_PATH = os.path.join(SCRIPT_DIR, "narrative_overrides.json")
TEMPLATE_PATH = os.path.join(REPO_DIR, "dashboard", "dashboard_template.html")
HTML_OUT = os.path.join(REPO_DIR, "dashboard", "index.html")
JSON_OUT = os.path.join(REPO_DIR, "dashboard", "dashboard-data.json")


def fetch_price_history(ticker, range_="1y", interval="1d"):
    """Returns (dates, closes) or None -- same v8/chart endpoint/shape as
    wave_analysis.py's fetch_history, but plain close (not adjclose): dividend/
    split adjustment matters for swing-pivot detection over years of history,
    much less for a 1y SMA/RSI/52-wk-range read, and plain close matches what
    quote sites show for "last price" without a separate reconciliation step."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_}&interval={interval}"
    try:
        raw = fetch(url, timeout=25)
        data = json.loads(raw)
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except Exception:
        return None
    rows = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
    if not rows:
        return None
    dates, vals = zip(*rows)
    return list(dates), list(vals)


def sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def rsi14(closes, period=14):
    """Wilder's RSI. Needs period+1 closes minimum (period diffs)."""
    if len(closes) < period + 1:
        return None
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in diffs]
    losses = [-d if d < 0 else 0.0 for d in diffs]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(diffs)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def analyze_technical(ticker):
    hist = fetch_price_history(ticker)
    if not hist:
        return None
    dates, closes = hist
    latest = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else latest
    delta_pct = ((latest - prev) / prev * 100.0) if prev else 0.0
    s50 = sma(closes, 50)
    s200 = sma(closes, 200)
    rsi = rsi14(closes)

    tiles = []
    if s50 is not None and s200 is not None:
        golden = s50 > s200
        tiles.append({
            "label": "50D vs 200D MA",
            "value": "Golden trend" if golden else "Death cross",
            "note": f"50D ${s50:,.2f} {'>' if golden else '<'} 200D ${s200:,.2f}",
            "badge": "good" if golden else "critical",
        })
    if rsi is not None:
        badge = "warn" if (rsi >= 70 or rsi <= 30) else "good"
        note = "Overbought" if rsi >= 70 else ("Oversold" if rsi <= 30 else "Neutral")
        tiles.append({"label": "RSI (14D)", "value": f"{rsi:.1f}", "note": note, "badge": badge})

    return {
        "price": latest,
        "delta_pct": delta_pct,
        "range_low": min(closes),
        "range_high": max(closes),
        "tiles": tiles,
    }


def analyze_fundamentals_and_sentiment(ticker):
    """Returns (company_name, fundamentals_tiles, sentiment_tiles) using the
    same quoteSummary fetch fundamentals_analysis.py already uses -- extended
    to request the price module (company name) too, since financialData
    already carries analyst target/recommendation fields at no extra cost."""
    result = fetch_quotesummary(ticker)
    if not result:
        return None, [], []

    fd = result.get("financialData") or {}
    ks = result.get("defaultKeyStatistics") or {}
    price_mod = result.get("price") or {}
    company = price_mod.get("longName") or price_mod.get("shortName") or ticker

    revenue_growth = _raw(fd, "revenueGrowth")
    gross_margin = _raw(fd, "grossMargins")
    roe = _raw(fd, "returnOnEquity")
    fcf = _raw(fd, "freeCashflow") or _raw(fd, "operatingCashflow")
    ev = _raw(ks, "enterpriseValue")
    fcf_yield = (fcf / ev) if (fcf is not None and ev) else None

    fund_tiles = []
    if revenue_growth is not None:
        fund_tiles.append({
            "label": "Revenue Growth (YoY)",
            "value": f"{revenue_growth * 100:+.1f}%",
            "note": "จาก Yahoo Finance quoteSummary",
            "badge": "good" if revenue_growth > 0 else "critical",
        })
    if gross_margin is not None:
        fund_tiles.append({"label": "Gross Margin", "value": f"{gross_margin * 100:.1f}%", "note": "", "badge": "good"})
    if roe is not None:
        fund_tiles.append({
            "label": "Return on Equity", "value": f"{roe * 100:.1f}%", "note": "",
            "badge": "good" if roe > 0 else "warn",
        })
    if fcf_yield is not None:
        fund_tiles.append({
            "label": "FCF Yield", "value": f"{fcf_yield * 100:.1f}%",
            "note": "FCF / Enterprise Value", "badge": "good" if fcf_yield > 0 else "warn",
        })

    target_mean = _raw(fd, "targetMeanPrice")
    target_low = _raw(fd, "targetLowPrice")
    target_high = _raw(fd, "targetHighPrice")
    rec_key = fd.get("recommendationKey")
    num_analysts = _raw(fd, "numberOfAnalystOpinions")

    sentiment_tiles = []
    if rec_key:
        rec_badge = {
            "strong_buy": "good", "buy": "good", "hold": "warn",
            "underperform": "serious", "sell": "critical",
        }.get(rec_key, "warn")
        sentiment_tiles.append({
            "label": "Consensus rating", "value": rec_key.replace("_", " ").title(),
            "note": f"{num_analysts:.0f} analysts" if num_analysts else "",
            "badge": rec_badge,
        })
    if target_mean is not None:
        note = f"ช่วง ${target_low:,.0f}–${target_high:,.0f}" if (target_low and target_high) else ""
        sentiment_tiles.append({
            "label": "Avg. price target", "value": f"${target_mean:,.2f}", "note": note, "badge": "good",
        })

    return company, fund_tiles, sentiment_tiles


def scan_one(ticker, overrides):
    tech = analyze_technical(ticker)
    company, fund_tiles, sentiment_tiles = analyze_fundamentals_and_sentiment(ticker)
    if tech is None and company is None:
        return None  # total failure for this ticker -- skip rather than publish a blank card

    override = overrides.get(ticker)
    sections = []
    if fund_tiles:
        sections.append({"title": "Fundamentals (auto)", "desc": "คำนวณอัตโนมัติจาก Yahoo Finance ทุกรอบ scan", "tiles": fund_tiles})
    if override:
        sections = override.get("sections", []) + sections

    entry = {
        "company": company or ticker,
        "exchange": "US",
        "price": f"${tech['price']:,.2f}" if tech else "n/a",
        "delta": f"{tech['delta_pct']:+.2f}%" if tech else "",
        "deltaDir": "up" if (tech and tech["delta_pct"] >= 0) else "down",
        "range": (f"52-wk range ${tech['range_low']:,.2f} – ${tech['range_high']:,.2f}" if tech else ""),
        "sections": sections,
        "technical": tech["tiles"] if tech else [],
        "sentiment": sentiment_tiles,
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if override:
        entry["narrative"] = override.get("narrative")
        entry["hero"] = override.get("hero")
        entry["narrative_as_of"] = override.get("as_of")
        entry["narrative_sources"] = override.get("sources")
    return entry


def build_page(data):
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()
    data_json = json.dumps(data, ensure_ascii=False)
    html_out = template.replace("__DATA_JSON__", data_json)
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html_out)
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        f.write(data_json)


def main():
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        watchlist = json.load(f)
    overrides = {}
    if os.path.exists(OVERRIDES_PATH):
        with open(OVERRIDES_PATH, encoding="utf-8") as f:
            overrides = json.load(f)

    data = {}
    for ticker in watchlist:
        print(f"Scanning {ticker}...")
        try:
            entry = scan_one(ticker, overrides)
            if entry:
                data[ticker] = entry
            else:
                print(f"  {ticker}: no data, skipping")
        except Exception as e:
            print(f"  {ticker}: ERROR {e}")
        time.sleep(0.3)  # spread requests, same courtesy as fundamentals_analysis.py

    build_page(data)
    print(f"Done: {len(data)}/{len(watchlist)} tickers scanned. Written to {HTML_OUT}")


if __name__ == "__main__":
    main()
