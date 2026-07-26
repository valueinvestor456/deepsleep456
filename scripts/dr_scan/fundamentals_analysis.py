#!/usr/bin/env python3
"""
Fundamental screen for DR underlyings, run as a separate monthly batch job
(NOT part of the live 30s scan_and_publish.py loop, and separate from the
weekly wave_analysis.py job -- fundamentals change on a quarterly-earnings
cadence, far slower than either). Writes fundamentals_cache.json, which
scan_and_publish.py reads once per cycle and joins onto each row by
underlying ticker (yahoo_u), same pattern as wave_cache.json.

Deliberately does NOT attempt to score the qualitative 7-Powers/moat
framework -- that requires competitive-landscape judgment a script can't
responsibly fake. What's computed instead is a small set of metrics
readable directly off Yahoo's quoteSummary endpoint (FCF yield/margin,
revenue growth, gross margin, ROE, debt/equity), plus one deterministic
"bucket" tag (cheap+good / cheap only / good only / blank) based on how
each underlying's FCF yield and revenue growth rank among the OTHER
underlyings actually tracked here -- a peer percentile, not an absolute
valuation call, and never presented as a moat/quality rating. See
wiki/concepts/dr-fair-price-monitoring.md in the "investment with ai"
project for the design discussion.

Reverse-DCF is explicitly out of scope: it needs a WACC + terminal-growth
assumption per underlying, and a blanket default across wildly different
sectors would produce a false-precision number -- worse than nothing.
"""
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from scan_and_publish import HEADERS  # reuse existing User-Agent

MASTER_PATH = os.path.join(SCRIPT_DIR, "dr_master_resolved.json")
CACHE_PATH = os.path.join(SCRIPT_DIR, "fundamentals_cache.json")

QUOTESUMMARY_MODULES = "financialData,defaultKeyStatistics,summaryDetail"
TOP_TERTILE_PCTL = 2.0 / 3.0  # FCF yield must rank in the top third among tracked peers

# Unlike v8/chart (used by get_yahoo_price) and the stockanalysis.com scrapes,
# quoteSummary now 401s without a valid cookie+crumb pair -- Yahoo locked
# this endpoint down at some point after the rest of this codebase's Yahoo
# calls were written. Fetch once per batch run and reuse for every ticker;
# a session-scoped opener carries the cookie automatically.
_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))
_crumb = None


def _get_crumb():
    global _crumb
    if _crumb is not None:
        return _crumb
    try:
        _opener.open(urllib.request.Request("https://fc.yahoo.com", headers=HEADERS), timeout=20)
    except Exception:
        pass  # this call 404s but still sets the cookie we need
    resp = _opener.open(urllib.request.Request("https://query1.finance.yahoo.com/v1/test/getcrumb", headers=HEADERS), timeout=20)
    _crumb = resp.read().decode("utf-8", errors="replace")
    return _crumb


def _raw(d, key):
    """quoteSummary numeric fields are usually {"raw": ..., "fmt": "..."} but
    occasionally a bare number or missing -- normalize to a plain float/None."""
    if not d:
        return None
    v = d.get(key)
    if isinstance(v, dict):
        return v.get("raw")
    return v


def fetch_quotesummary(ticker):
    """Returns the raw quoteSummary result dict, or None on failure. This is
    the first endpoint in this codebase that needs real 429/401 handling --
    query1/v8/chart and the stockanalysis.com scrapes have never needed it,
    but quoteSummary requires the cookie+crumb pair (401s without it, see
    _get_crumb) and is more rate-limit-sensitive besides. One retry after a
    longer backoff (or a crumb refresh on 401), then give up on this ticker
    (never let one bad ticker abort the batch)."""
    for attempt in range(2):
        crumb = _get_crumb()
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules={QUOTESUMMARY_MODULES}&crumb={crumb}"
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
                global _crumb
                _crumb = None  # crumb expired mid-run -- refresh once and retry
                continue
            return None
        except Exception:
            return None
    return None


def analyze_ticker(ticker):
    """Returns a metrics dict (quality: "ok" or "insufficient_data") or
    raises on total fetch failure (caller handles per-ticker try/except)."""
    result = fetch_quotesummary(ticker)
    if not result:
        return {"quality": "insufficient_data"}

    fd = result.get("financialData") or {}
    ks = result.get("defaultKeyStatistics") or {}
    sd = result.get("summaryDetail") or {}

    operating_cashflow = _raw(fd, "operatingCashflow")
    fcf = _raw(fd, "freeCashflow")
    if fcf is None:
        # Fallback: operatingCashflow alone overstates true FCF (no capex
        # deduction) -- acceptable as a fallback only, never preferred.
        fcf = operating_cashflow
    ev = _raw(ks, "enterpriseValue")
    revenue = _raw(fd, "totalRevenue")
    market_cap = _raw(sd, "marketCap")

    fcf_yield = (fcf / ev) if (fcf is not None and ev) else None
    fcf_margin = (fcf / revenue) if (fcf is not None and revenue) else None
    revenue_growth = _raw(fd, "revenueGrowth")
    gross_margin = _raw(fd, "grossMargins")
    gross_profit = _raw(fd, "grossProfits")
    roe = _raw(fd, "returnOnEquity")
    debt_to_equity = _raw(fd, "debtToEquity")
    price_to_sales = (market_cap / revenue) if (market_cap and revenue) else None
    # Only defined when FCF/OCF is positive -- a negative-cashflow "multiple"
    # is not a meaningful ratio (e.g. -3.2x reads as cheap, means the
    # opposite), so leave it None rather than show a misleading number.
    mcap_to_fcf = (market_cap / fcf) if (market_cap and fcf and fcf > 0) else None
    mcap_to_ocf = (market_cap / operating_cashflow) if (market_cap and operating_cashflow and operating_cashflow > 0) else None

    quality = "ok" if fcf_yield is not None else "insufficient_data"
    return {
        "fcf_yield": fcf_yield,
        "fcf_margin": fcf_margin,
        "revenue_growth": revenue_growth,
        "gross_margin": gross_margin,
        "gross_profit": gross_profit,
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "price_to_sales": price_to_sales,
        "mcap_to_fcf": mcap_to_fcf,
        "mcap_to_ocf": mcap_to_ocf,
        "market_cap": market_cap,
        "enterprise_value": ev,
        "quality": quality,
    }


def _percentile(sorted_vals, pctl):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, int(round(pctl * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def assign_buckets(cache):
    """Bucket is relative to the OTHER underlyings actually tracked here, so
    it must be computed only after every ticker in this run has a value --
    not per-ticker as each fetch completes."""
    fcf_yields = sorted(v["fcf_yield"] for v in cache.values() if v.get("quality") == "ok" and v.get("fcf_yield") is not None)
    threshold = _percentile(fcf_yields, TOP_TERTILE_PCTL)
    for v in cache.values():
        if v.get("quality") != "ok":
            v["bucket"] = None
            continue
        cheap = threshold is not None and v.get("fcf_yield") is not None and v["fcf_yield"] >= threshold
        good = v.get("revenue_growth") is not None and v["revenue_growth"] > 0
        if cheap and good:
            v["bucket"] = "cheap+good"
        elif good:
            v["bucket"] = "good only"
        elif cheap:
            v["bucket"] = "cheap only"
        else:
            v["bucket"] = None


def build_fundamentals_cache():
    with open(MASTER_PATH, encoding="utf-8") as f:
        master = json.load(f)
    underlyings = sorted({d["yahoo_u"] for d in master if d.get("yahoo_u")})
    print(f"{len(underlyings)} unique underlyings to analyze")

    # Merge into the existing cache rather than overwrite wholesale, so a
    # partial-failure run degrades gracefully -- keep last-known-good values
    # for tickers that error this run instead of blanking them.
    cache = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ok = 0
    for i, ticker in enumerate(underlyings):
        try:
            result = analyze_ticker(ticker)
            result["computed_at"] = now_iso
            result["calculated_at"] = now_iso
            cache[ticker] = result
            if result.get("quality") == "ok":
                ok += 1
        except Exception as e:
            print(f"  {ticker}: ERROR {e}")
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(underlyings)} done")
        time.sleep(0.3)  # spread requests -- shares Yahoo's host with the live scanner and wave batch job

    assign_buckets(cache)

    tmp_path = CACHE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp_path, CACHE_PATH)  # atomic write, scanner never sees a half-written file
    print(f"Done: {ok}/{len(underlyings)} resolved with fundamentals. Cache written to {CACHE_PATH}")


if __name__ == "__main__":
    build_fundamentals_cache()
