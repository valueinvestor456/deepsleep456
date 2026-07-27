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


def range_position_tile(live_price, range_low, range_high):
    """% distance from the 52-wk high/low -- turns two raw numbers into the
    question an investor actually asks ("how close to the top/bottom of its
    range is this?") instead of making them do the arithmetic."""
    if not (live_price and range_low and range_high):
        return None
    from_high = (live_price - range_high) / range_high * 100.0
    from_low = (live_price - range_low) / range_low * 100.0
    return {
        "label": "Position in 52-wk range",
        "value": f"{from_high:+.1f}% จากจุดสูงสุด",
        "note": f"{from_low:+.1f}% เหนือจุดต่ำสุด 52 สัปดาห์",
        "badge": "warn" if from_high > -5 else ("good" if from_low < 15 else "warn"),
    }


def tally_signals(*tile_lists):
    """Deterministic count of good/warn/serious/critical across every tile
    already shown on the card -- pure aggregation of badges the page already
    assigns, not a new judgment call layered on top."""
    counts = {"good": 0, "warn": 0, "serious": 0, "critical": 0}
    for tiles in tile_lists:
        for t in tiles or []:
            b = t.get("badge")
            if b in counts:
                counts[b] += 1
    return counts


# Yahoo's news tagging uses one canonical ticker per company regardless of
# share class -- e.g. Alphabet news is tagged "GOOG" even when the watchlist
# tracks "GOOGL" for price/fundamentals. Add an entry here if a newly-added
# dual-class ticker shows 0 news items (same manual-mapping pattern as
# dr_master_resolved.json for tickers Yahoo's automatic matching can't
# resolve on its own).
NEWS_TICKER_ALIASES = {"GOOGL": "GOOG"}


def fetch_news(ticker, limit=5):
    """Yahoo's search endpoint (same one yfinance's Ticker.news uses under
    the hood) tags each result with relatedTickers -- the raw result set is
    a fuzzy "market chatter mentioning this query" feed (peers, sector
    roundups, etc.), noisy if used unfiltered. Keeping only items where the
    canonical ticker is the FIRST related ticker (empirically the primary
    subject, not just a mention) trades recall for precision -- a handful of
    clearly-relevant headlines beats ten mostly-about-something-else ones on
    an investor-facing page. No API key needed."""
    news_ticker = NEWS_TICKER_ALIASES.get(ticker, ticker)
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={news_ticker}&newsCount=15&quotesCount=0"
    try:
        raw = fetch(url, timeout=20)
        items = json.loads(raw).get("news", [])
    except Exception:
        return []
    relevant = [n for n in items if (n.get("relatedTickers") or [None])[0] == news_ticker]
    relevant.sort(key=lambda n: n.get("providerPublishTime", 0), reverse=True)
    out = []
    for n in relevant[:limit]:
        ts = n.get("providerPublishTime")
        out.append({
            "title": n.get("title", ""),
            "publisher": n.get("publisher", ""),
            "link": n.get("link", ""),
            "published_at": time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else "",
        })
    return out


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

    # Valuation ratios -- classic first-look investor metrics, missing from
    # the original cut. Badges here are rough, disclosed heuristics (e.g.
    # "PE > 40" is a common growth-premium threshold, NOT a claim the stock
    # is overvalued -- high PE is normal for a fast grower) rather than a
    # peer-percentile rank like fundamentals_cache.json's bucket tag, since
    # there's no fixed peer universe for an arbitrary watchlist ticker.
    trailing_pe = _raw(sd, "trailingPE")
    forward_pe = _raw(sd, "forwardPE") or _raw(ks, "forwardPE")
    peg_ratio = _raw(ks, "pegRatio")
    price_to_sales = _raw(sd, "priceToSalesTrailing12Months")

    valuation_tiles = []
    if trailing_pe is not None:
        badge = "critical" if trailing_pe <= 0 else ("warn" if trailing_pe > 40 else "good")
        note = "ขาดทุน (PE ติดลบ)" if trailing_pe <= 0 else ("PE > 40 มักสะท้อน growth premium ไม่ใช่แพงเกินไปเสมอไป" if trailing_pe > 40 else "")
        valuation_tiles.append({"label": "Trailing P/E", "value": f"{trailing_pe:.1f}x", "note": note, "badge": badge})
    if forward_pe is not None:
        valuation_tiles.append({"label": "Forward P/E", "value": f"{forward_pe:.1f}x", "note": "ประมาณการกำไรปีหน้า", "badge": "good" if forward_pe > 0 else "critical"})
    if peg_ratio is not None:
        badge = "good" if peg_ratio < 1 else ("warn" if peg_ratio <= 2 else "critical")
        valuation_tiles.append({"label": "PEG Ratio", "value": f"{peg_ratio:.2f}", "note": "PE เทียบกับอัตราการเติบโต — <1 มักถูกกว่าที่โต", "badge": badge})
    if price_to_sales is not None:
        valuation_tiles.append({"label": "Price/Sales", "value": f"{price_to_sales:.1f}x", "note": "", "badge": "warn"})

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
        range_note = f"ช่วง ${target_low:,.0f}–${target_high:,.0f}" if (target_low and target_high) else ""
        upside_note = ""
        if live_price:
            upside_pct = (target_mean - live_price) / live_price * 100.0
            upside_note = f" · {upside_pct:+.1f}% จากราคาปัจจุบัน"
        sentiment_tiles.append({
            "label": "Avg. price target", "value": f"${target_mean:,.2f}", "note": (range_note + upside_note).strip(" ·"),
            "badge": "good" if (live_price and target_mean > live_price) else "warn",
        })

    return {
        "company": company,
        "live_price": live_price,
        "delta_pct": delta_pct,
        "range_low": range_low,
        "range_high": range_high,
        "fund_tiles": fund_tiles,
        "valuation_tiles": valuation_tiles,
        "sentiment_tiles": sentiment_tiles,
    }


def scan_one(ticker, overrides):
    base = analyze_ticker(ticker)
    if base is None:
        return None  # total failure this cycle -- caller falls back to last-known-good
    tech_tiles = analyze_technical_tiles(ticker)
    range_tile = range_position_tile(base["live_price"], base["range_low"], base["range_high"])
    if range_tile:
        tech_tiles = tech_tiles + [range_tile]

    override = overrides.get(ticker)
    sections = []
    if base["fund_tiles"]:
        sections.append({"title": "Fundamentals (auto)", "desc": "คำนวณอัตโนมัติจาก Yahoo Finance ทุกรอบ scan", "tiles": base["fund_tiles"]})
    if base["valuation_tiles"]:
        sections.append({"title": "Valuation (auto)", "desc": "เกณฑ์ badge เป็น heuristic คร่าวๆ ไม่ใช่คำตัดสินว่าแพง/ถูก", "tiles": base["valuation_tiles"]})
    if override:
        sections = override.get("sections", []) + sections

    override_tiles = []
    for s in (override.get("sections", []) if override else []):
        override_tiles.extend(s.get("tiles", []))

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
        "signal_summary": tally_signals(base["fund_tiles"], base["valuation_tiles"], base["sentiment_tiles"], tech_tiles, override_tiles),
        "news": fetch_news(ticker),
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
