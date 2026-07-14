#!/usr/bin/env python3
"""
Continuous DR fair-price scanner + publisher, run from GitHub Actions during
SET trading hours. Loops: scan all tickers (concurrently, ~6-8 workers) ->
rebuild dr/index.html + dr/dr-data.json -> commit + push -> repeat, until
the market closes or this job approaches GitHub's 6h runtime cap.

This is the repo-hosted counterpart to the local project's
.tools/scan_dr.py + .tools/build_dr_page.py (which still exist for manual
runs/development -- this script is the one that actually runs unattended).
Ratio is always pulled live from SET, never from a stored value -- see
wiki/concepts/dr-fair-price-monitoring.md in the "investment with ai"
project for why that matters (a stale ratio silently produces wildly wrong
premium/discount numbers).

dr_master_resolved.json here is a periodic manual copy from the project's
.tools/dr_master_resolved.json (the DR-ticker -> underlying mapping) --
update it by hand when new tickers get resolved there.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
MASTER_PATH = os.path.join(SCRIPT_DIR, "dr_master_resolved.json")
HTML_OUT = os.path.join(REPO_DIR, "dr", "index.html")
JSON_OUT = os.path.join(REPO_DIR, "dr", "dr-data.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
WORKERS = 7  # moderate concurrency -- see module docstring on why not higher

BKK = timezone(timedelta(hours=7))


def market_open_now():
    now = datetime.now(BKK)
    if now.weekday() >= 5:
        return False
    return (10, 0) <= (now.hour, now.minute) <= (16, 32)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def get_set_quote(sym):
    url = f"https://www.set.or.th/th/market/product/dr/quote/{sym}/company-profile"
    html_text = fetch(url)
    m = re.search(r'quote:\{info:\{symbol:"' + re.escape(sym) + r'".*?exerciseRatio:"([^"]*)"', html_text)
    if not m:
        return None
    block = m.group(0)

    def num(field):
        mm = re.search(field + r':(-?[\d.]+)', block)
        return float(mm.group(1)) if mm else None

    last = num('last') or num('prior') or num('open')
    if last is None:
        mm = re.search(r'offers:\[\{volume:-?[\d.]+,price:"(-?[\d.]+)"', block)
        if mm:
            last = float(mm.group(1))
    if last is None:
        mm = re.search(r'bids:\[\{volume:-?[\d.]+,price:"(-?[\d.]+)"', block)
        if mm:
            last = float(mm.group(1))
    status_m = re.search(r'marketStatus:"([^"]*)"', block)
    dt_m = re.search(r'marketDateTime:"([^"]*)"', block)
    ratio_m = re.search(r'exerciseRatio:"([^"]*)"', block)
    return {
        'last': last,
        'marketStatus': status_m.group(1) if status_m else None,
        'marketDateTime': dt_m.group(1) if dt_m else None,
        'exerciseRatio_raw': ratio_m.group(1) if ratio_m else None,
    }


def get_yahoo_price(ticker):
    try:
        raw = fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}")
        return json.loads(raw)['chart']['result'][0]['meta'].get('regularMarketPrice')
    except Exception:
        return None


TV_EXCH_TO_SA = {'HKEX': 'hkg', 'TSE': 'tyo', 'SGX': 'sgx', 'EURONEXT': 'epa', 'SIX': 'swx', 'SSE': 'sha', 'SZSE': 'she'}


def get_pe_vietstock(vn_ticker):
    """Vietstock (finance.vietstock.vn/<TICKER>-x.htm -- slug suffix after
    the ticker is ignored server-side) embeds a JSON blob with a "PE" field
    (trailing P/E, confirmed against known values for FPT/GAS/HPG/MSN/MWG/
    VCB/VHM/VNM). There's also an "FEPS" field that could numerically be a
    forward P/E but nothing on the page confirms its meaning -- not
    trusted, left as None. stockanalysis.com has no Vietnam/HOSE coverage."""
    try:
        html_text = fetch(f"https://finance.vietstock.vn/{vn_ticker}-x.htm")
        m = re.search(r'"PE":"([\d.\-]*)"', html_text)
        if m and m.group(1):
            return float(m.group(1)), None
    except Exception:
        pass
    return None, None


def get_pe_ratios(yahoo_ticker, underlying_tv=None):
    """Non-US markets use /quote/<exchange-code>/<raw-ticker>/; everything
    else (US, or an exchange TV_EXCH_TO_SA doesn't cover) falls back to
    /stocks/<yahoo-ticker>/ -- must be `if not url`, not `else`, since the
    underlying_tv branch can run and still fail to produce a url (exchange
    not in the map) without the string itself being colon-less."""
    if yahoo_ticker.endswith('.VN'):
        return get_pe_vietstock(yahoo_ticker[:-3])
    url = None
    if underlying_tv and ':' in underlying_tv:
        tv_exch, raw_ticker = underlying_tv.split(':', 1)
        sa_exch = TV_EXCH_TO_SA.get(tv_exch)
        if sa_exch:
            url = f"https://stockanalysis.com/quote/{sa_exch}/{raw_ticker.lower()}/"
    if not url:
        url = f"https://stockanalysis.com/stocks/{yahoo_ticker.lower()}/"
    try:
        html_text = fetch(url)
        pe = fwd_pe = None
        m = re.search(r'>PE Ratio</td><td[^>]*>([\d.\-]+|n/a)</td>', html_text)
        if m and m.group(1) != 'n/a':
            pe = float(m.group(1))
        m2 = re.search(r'>Forward PE</td><td[^>]*>([\d.\-]+|n/a)</td>', html_text)
        if m2 and m2.group(1) != 'n/a':
            fwd_pe = float(m2.group(1))
        return pe, fwd_pe
    except Exception:
        return None, None


WAVE_CACHE_PATH = os.path.join(SCRIPT_DIR, "wave_cache.json")
_wave_cache = None


def load_wave_cache():
    """Loaded once per process (not per scan_one call/thread) -- wave_cache.json
    is produced weekly by wave_analysis.py, a separate heavier batch job; the
    live 30s scanner only ever reads it, never recomputes it."""
    global _wave_cache
    if _wave_cache is None:
        try:
            with open(WAVE_CACHE_PATH, encoding="utf-8") as f:
                _wave_cache = json.load(f)
        except Exception:
            _wave_cache = {}
    return _wave_cache


def get_wave_info(yahoo_u, live_underlying_price):
    """Joins cached swing/reward-risk data onto a row by underlying ticker,
    plus a cheap live check: has the price already crossed the cached
    target or stop since last week's batch ran? This is nearly free (the
    live price is already fetched this cycle for the fair-price calc) and
    keeps the wave data meaningfully useful between weekly refreshes
    instead of silently going stale."""
    w = load_wave_cache().get(yahoo_u)
    if not w or w.get("quality") != "ok":
        return None
    info = dict(w)
    target, stop, stage = w.get("target"), w.get("stop"), w.get("stage_key")
    if live_underlying_price is not None and target is not None and stop is not None:
        bullish = stage in ("extending_up", "retracing_from_low")
        if (bullish and live_underlying_price <= stop) or (not bullish and live_underlying_price >= stop):
            info["live_status"] = "stop_breached"
        elif (bullish and live_underlying_price >= target) or (not bullish and live_underlying_price <= target):
            info["live_status"] = "target_reached"
        else:
            info["live_status"] = "active"
    return info


def scan_one(d):
    sym = d['sym']
    try:
        setq = get_set_quote(sym)
        u_price = get_yahoo_price(d['yahoo_u'])
        fx_rate = get_yahoo_price(d['yahoo_fx']) if d.get('yahoo_fx') else 1.0
        ratio_raw = setq['exerciseRatio_raw'] if setq else None
        live_ratio = None
        if ratio_raw:
            rm = re.match(r'([\d,.]+)\s*:\s*1', ratio_raw)
            if rm:
                live_ratio = float(rm.group(1).replace(',', ''))
        fair = (u_price * fx_rate / live_ratio) if (u_price and fx_rate and live_ratio) else None
        actual = setq['last'] if setq else None
        premium_pct = ((actual / fair - 1) * 100) if (actual and fair) else None
        pe, fwd_pe = get_pe_ratios(d['yahoo_u'], d.get('underlying_tv'))
        wave = get_wave_info(d['yahoo_u'], u_price)
        row = dict(d)
        row.update({
            'actual_price': actual, 'underlying_price': u_price, 'fx_rate': fx_rate,
            'ratio_used': live_ratio, 'fair_price': round(fair, 4) if fair else None,
            'premium_pct': round(premium_pct, 2) if premium_pct is not None else None,
            'pe_ratio': pe, 'forward_pe': fwd_pe, 'wave': wave,
            'set_market_status': setq['marketStatus'] if setq else None,
            'set_market_datetime': setq['marketDateTime'] if setq else None,
        })
        return row
    except Exception as e:
        row = dict(d)
        row['error'] = str(e)
        return row


def scan_all(master):
    results = [None] * len(master)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(scan_one, d): i for i, d in enumerate(master)}
        done = 0
        for fut in as_completed(futures):
            i = futures[fut]
            results[i] = fut.result()
            done += 1
            if done % 50 == 0:
                print(f"  scanned {done}/{len(master)}")
    return results


def build_page(results):
    """Mirrors .tools/build_dr_page.py -- kept as a single literal HTML
    template here (not imported) since this script must be self-contained
    for the Actions runner checkout."""
    with open(os.path.join(SCRIPT_DIR, "page_template.html"), encoding="utf-8") as f:
        template = f.read()
    data_json = json.dumps(results, ensure_ascii=False)
    html_out = template.replace('__DATA_JSON__', data_json)
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html_out)
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        f.write(data_json)


def git_publish(cycle_num):
    try:
        diff = subprocess.run(["git", "diff", "--quiet", "--", "dr/index.html", "dr/dr-data.json"], cwd=REPO_DIR)
        if diff.returncode == 0:
            print("  no change since last cycle, skipping commit")
            return
        subprocess.run(["git", "add", "dr/index.html", "dr/dr-data.json"], cwd=REPO_DIR, check=True)
        subprocess.run(["git", "commit", "-m", f"DR live scan cycle {cycle_num} [skip ci]"], cwd=REPO_DIR, check=True)
        push = subprocess.run(["git", "push"], cwd=REPO_DIR)
        if push.returncode != 0:
            subprocess.run(["git", "pull", "--rebase"], cwd=REPO_DIR, check=True)
            subprocess.run(["git", "push"], cwd=REPO_DIR, check=True)
    except Exception as e:
        print("git_publish error:", e)


def main():
    with open(MASTER_PATH, encoding="utf-8") as f:
        master = json.load(f)
    print(f"Loaded {len(master)} tickers, {WORKERS} concurrent workers")

    deadline = time.monotonic() + 5.5 * 3600
    cycle = 0
    while time.monotonic() < deadline:
        if not market_open_now():
            print("Market closed, exiting.")
            return
        cycle += 1
        t0 = time.monotonic()
        print(f"=== cycle {cycle} starting ===")
        results = scan_all(master)
        build_page(results)
        git_publish(cycle)
        elapsed = time.monotonic() - t0
        print(f"=== cycle {cycle} done in {elapsed:.0f}s ===")
        if elapsed < 30:
            time.sleep(30 - elapsed)  # floor so we're not hammering faster than ~every 30s even on a lucky fast pass

    print("Approaching runtime cap, exiting for the next scheduled run to take over.")


if __name__ == "__main__":
    main()
