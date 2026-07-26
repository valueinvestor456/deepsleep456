#!/usr/bin/env python3
"""
US-equity leading-indicator scan for dashboard/index.html, run as a single-shot
batch job from GitHub Actions every 30 min during US market hours (see
.github/workflows/dashboard-scan.yml -- unlike scripts/dr_scan/scan_and_publish.py
this does NOT loop internally; the workflow's cron provides the cadence).

For every ticker in watchlist.json: fetches quoteSummary (same cookie+crumb
mechanics as scripts/dr_scan/fundamentals_analysis.py's fetch_quotesummary,
reused directly) for the authoritative current price via get_yahoo_price()
(scan_and_publish.py's regular/pre/post-market-aware picker -- NOT a stale
daily-bar close), previousClose/52-wk range from summaryDetail, fundamentals,
and analyst sentiment; separately fetches 1y daily history (same v8/chart
pattern as wave_analysis.py's fetch_history) only for SMA50/SMA200/RSI14,
which need a price series rather than a single point-in-time quote.

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

Resilience: merges into the existing dashboard-data.json rather than
overwriting wholesale, same reasoning as fundamentals_analysis.py's cache --
a ticker that fails this cycle (rate limit, transient network error) keeps
its last-known-good entry (flagged "stale": true) instead of vanishing from
search entirely until the next successful scan.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DR_SCAN_DIR = os.path.join(REPO_DIR, "scripts", "dr_scan")
sys.path.insert(0, DR_SCAN_DIR)

from scan_and_publish import fetch, get_yahoo_price, HEADERS  # reuse HTTP + extended-hours-aware price
from fundamentals_analysis import _get_crumb, _opener, _raw  # reuse cookie+crumb session

WATCHLIST_PATH = os.path.join(SCRIPT_DIR, "watchlist.json")
OVERRIDES_PATH = os.path.join(SCRIPT_DIR, "narrative_overrides.json")
TEMPLATE_PATH = os.path.join(REPO_DIR, "dashboard", "dashboard_template.html")
HTML_OUT = os.path.join(REPO_DIR, "dashboard", "index.html")
JSON_OUT = os.path.join(REPO_DIR, "dashboard", "dashboard-data.json")

WORKERS = 5  # moderate concurrency, same reasoning as scan_and_publish.py's WORKERS

# Same modules as fundamentals_analysis.py's QUOTESUMMARY_MODULES, plus "price"
# for company name -- fetch_quotesummary() there is hardcoded to the narrower
# module list, so this is a local variant reusing its crumb/opener rather than
# modifying a file the live DR cron also depends on.
QUOTESUMMARY_MODULES_EXT = "financialData,defaultKeyStatistics,summaryDetail,price"


def fetch_quotesummary(ticker):
    for attempt in range(2):
        crumb = _get_crumb()
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules={QUOTESUMMARY_MODULES_EXT}&crumb={crumb}"
        try:
            resp = _opener.open(urllib.request.Request(url, headers=HEADERS), timeout=20)
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
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


def fetch_price_history(ticker, range_="1y", interval="1d"):
    """Returns closes list or None -- same v8/chart endpoint/shape as
    wave_analysis.py's fetch_history. Used ONLY for SMA/RSI (needs a series);
    the current price/52-wk range/previousClose come from quoteSummary
    instead (see analyze_ticker), not from this history's last bar."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_}&interval={interval}"
    try:
        raw = fetch(url, timeout=25)
        data = json.loads(raw)
        result = data["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
    except Exception:
        return None
    vals = [c for c in closes if c is not None]
    return vals or None


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


def analyze_technical_tiles(ticker):
    closes = fetch_price_history(ticker)
    if not closes:
        return []
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
    return tiles


def analyze_ticker(ticker):
    """Returns a dict of everything derived from quoteSummary + the live
    price picker, or None if quoteSummary totally failed for this ticker."""
    result = fetch_quotesummary(ticker)
    if not result:
        return None

    fd = result.get("financialData") or {}
    ks = result.get("defaultKeyStatistics") or {}
    sd = result.get("summaryDetail") or {}
    price_mod = result.get("price") or {}
    company = price_mod.get("longName") or price_mod.get("shortName") or ticker

    live_price = get_yahoo_price(ticker)  # regular/pre/post-market-aware, not a stale daily-bar close
    prev_close = _raw(sd, "previousClose") or _raw(price_mod, "regularMarketPreviousClose")
    range_low = _raw(sd, "fiftyTwoWeekLow")
    range_high = _raw(sd, "fiftyTwoWeekHigh")
    delta_pct = ((live_price - prev_close) / prev_close * 100.0) if (live_price and prev_close) else None

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

    return {
        "company": company,
        "live_price": live_price,
        "delta_pct": delta_pct,
        "range_low": range_low,
        "range_high": range_high,
        "fund_tiles": fund_tiles,
        "sentiment_tiles": sentiment_tiles,
    }


def scan_one(ticker, overrides):
    base = analyze_ticker(ticker)
    if base is None:
        return None  # total failure this cycle -- caller falls back to last-known-good
    tech_tiles = analyze_technical_tiles(ticker)

    override = overrides.get(ticker)
    sections = []
    if base["fund_tiles"]:
        sections.append({"title": "Fundamentals (auto)", "desc": "คำนวณอัตโนมัติจาก Yahoo Finance ทุกรอบ scan", "tiles": base["fund_tiles"]})
    if override:
        sections = override.get("sections", []) + sections

    price = base["live_price"]
    entry = {
        "company": base["company"],
        "exchange": "US",
        "price": f"${price:,.2f}" if price else "n/a",
        "delta": f"{base['delta_pct']:+.2f}%" if base["delta_pct"] is not None else "",
        "deltaDir": "up" if (base["delta_pct"] is None or base["delta_pct"] >= 0) else "down",
        "range": (f"52-wk range ${base['range_low']:,.2f} – ${base['range_high']:,.2f}"
                  if (base["range_low"] and base["range_high"]) else ""),
        "sections": sections,
        "technical": tech_tiles,
        "sentiment": base["sentiment_tiles"],
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stale": False,
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

    # Merge into existing output rather than overwrite wholesale -- a ticker
    # that fails this cycle keeps its last-known-good entry (flagged stale)
    # instead of vanishing from search until the next successful scan.
    data = {}
    if os.path.exists(JSON_OUT):
        try:
            with open(JSON_OUT, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    ok = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(scan_one, t, overrides): t for t in watchlist}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                entry = fut.result()
            except Exception as e:
                entry = None
                print(f"  {ticker}: ERROR {e}")
            if entry:
                data[ticker] = entry
                ok += 1
                print(f"  {ticker}: ok")
            elif ticker in data:
                data[ticker]["stale"] = True
                print(f"  {ticker}: scan failed, keeping last-known-good (stale)")
            else:
                print(f"  {ticker}: scan failed, no prior data -- omitted this run")

    # Drop tickers that were removed from the watchlist entirely (rather than
    # keeping them forever as stale ghosts).
    for ticker in list(data.keys()):
        if ticker not in watchlist:
            del data[ticker]

    build_page(data)
    print(f"Done: {ok}/{len(watchlist)} tickers freshly scanned ({len(data)} total in output). Written to {HTML_OUT}")


if __name__ == "__main__":
    main()
