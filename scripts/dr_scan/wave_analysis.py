#!/usr/bin/env python3
"""
Swing/Fibonacci structure + reward-risk analysis for DR underlyings, run as a
separate weekly batch job (NOT part of the live 30s scan_and_publish.py loop
-- this is much heavier: ~1yr daily history per underlying across ~200-250
unique underlyings after dedup by yahoo_u). Writes wave_cache.json, which
scan_and_publish.py reads once per cycle and joins onto each row by
underlying ticker.

Deliberately NOT called "Elliott Wave" anywhere user-facing: wave counts are
genuinely ambiguous even among professional analysts, and a threshold-based
pivot detector mislabels routinely, not as a rare edge case -- a bare
"Wave 3" label would claim analytical authority this doesn't have. The
mechanism (ZigZag swing pivots -> Fibonacci retracement/extension) is
legitimate, disclosed, deterministic technical analysis; only the branding
changed. See wiki/concepts/dr-fair-price-monitoring.md in the "investment
with ai" project for the full design discussion.
"""
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from scan_and_publish import fetch  # reuse existing fetch mechanics/headers

MASTER_PATH = os.path.join(SCRIPT_DIR, "dr_master_resolved.json")
CACHE_PATH = os.path.join(SCRIPT_DIR, "wave_cache.json")

MIN_TRADING_DAYS = 120  # minimum bars with nonzero volume required to attempt labeling


def fetch_history(ticker, range_="1y", interval="1d"):
    """Returns (dates, adjcloses, volumes) or None on failure. Uses adjclose,
    not raw close -- an unadjusted split/bonus-share event (real risk for
    Vietnam names) would register as a huge fake swing and corrupt every
    downstream calculation."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_}&interval={interval}"
    try:
        raw = fetch(url, timeout=25)
        data = json.loads(raw)
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        adjclose = result["indicators"]["adjclose"][0]["adjclose"]
        volume = result["indicators"]["quote"][0]["volume"]
    except Exception:
        return None
    # drop any None bars (holidays/gaps Yahoo sometimes includes as null)
    rows = [(t, c, v) for t, c, v in zip(timestamps, adjclose, volume) if c is not None]
    if not rows:
        return None
    dates, closes, volumes = zip(*rows)
    return list(dates), list(closes), list(volumes)


def atr_stats(closes, period=14):
    """Close-to-close volatility proxy (we only have daily close from the
    chart API, not high/low, so this is a close-only proxy -- not a
    textbook ATR, adequate for a relative pivot threshold and a volatility-
    based stop distance). Returns (atr_abs, atr_frac) or (None, None).
    atr_frac keeps pivot "degree" comparable across very different
    volatility profiles in this ticker set (US megacaps down to thin
    HK-listed ETFs) -- a fixed % over-segments low-vol large caps and
    under-segments volatile thin small-caps."""
    if len(closes) < period + 1:
        return None, None
    tr = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    recent = tr[-period:]
    atr_abs = sum(recent) / len(recent)
    avg_price = sum(closes[-period:]) / period
    if avg_price == 0:
        return None, None
    return atr_abs, atr_abs / avg_price


def detect_pivots(closes, dates, threshold):
    """ZigZag pivot detector: confirms a new swing pivot when price reverses
    by more than `threshold` (fraction) from the running extreme since the
    last confirmed pivot. Returns a list of (index, date, price, 'H'|'L').
    The final entry is the current unconfirmed extreme (may still extend)."""
    if not closes or not threshold or threshold <= 0:
        return []
    pivots = []
    direction = None  # 'up' or 'down', once established
    last_pivot_price = closes[0]
    extreme_idx, extreme_price = 0, closes[0]
    for i in range(1, len(closes)):
        price = closes[i]
        if direction is None:
            change = (price - last_pivot_price) / last_pivot_price
            if abs(change) >= threshold:
                direction = 'up' if change > 0 else 'down'
                extreme_idx, extreme_price = i, price
            continue
        if direction == 'up':
            if price >= extreme_price:
                extreme_idx, extreme_price = i, price
            elif (extreme_price - price) / extreme_price >= threshold:
                pivots.append((extreme_idx, dates[extreme_idx], extreme_price, 'H'))
                direction = 'down'
                last_pivot_price = extreme_price
                extreme_idx, extreme_price = i, price
        else:
            if price <= extreme_price:
                extreme_idx, extreme_price = i, price
            elif (price - extreme_price) / extreme_price >= threshold:
                pivots.append((extreme_idx, dates[extreme_idx], extreme_price, 'L'))
                direction = 'up'
                last_pivot_price = extreme_price
                extreme_idx, extreme_price = i, price
    if direction is not None:
        pivots.append((extreme_idx, dates[extreme_idx], extreme_price, 'H' if direction == 'up' else 'L'))
    return pivots


STAGE_LABELS = {
    'extending_up': 'Extending up-swing',
    'retracing_from_high': 'Retracement from swing high',
    'extending_down': 'Extending down-swing',
    'retracing_from_low': 'Retracement from swing low',
}


def label_swing_structure(pivots, current_price):
    """Labels the current structure using the honest, non-Elliott-Wave
    vocabulary: whether price is still pushing toward/past the most recent
    confirmed swing extreme, or has pulled back from it. Needs at least two
    pivots (one full confirmed swing) to say anything."""
    if len(pivots) < 2:
        return None, None
    last = pivots[-1]
    if last[3] == 'H':
        if current_price >= last[2]:
            return 'extending_up', STAGE_LABELS['extending_up']
        return 'retracing_from_high', STAGE_LABELS['retracing_from_high']
    else:
        if current_price <= last[2]:
            return 'extending_down', STAGE_LABELS['extending_down']
        return 'retracing_from_low', STAGE_LABELS['retracing_from_low']


def elliott_count(pivots):
    """Best-effort Elliott Wave label ("Wave 2"/"Wave 3"/"Wave 4"/"Wave 5")
    for the swing sequence ENDING AT the most recent confirmed/running
    pivot extreme (pivots[-1]) -- i.e. "the recent structure looks like it
    just completed Wave N" -- checked against Elliott's structural rules
    for an impulse: wave 2 never fully retraces wave 1, wave 3 is never
    the shortest of 1/3/5, wave 4 doesn't overlap wave 1's price
    territory, each wave moves in the expected direction. Tries the
    longest (most specific) window first (6 points = 5 legs = just
    finished Wave 5) and falls back to shorter windows. Returns None --
    not a guess -- if no window satisfies its rules; per explicit user
    decision this is shown only when a fit is found, never forced. This
    is ONE possible reading via ONE specific rule-checking algorithm, not
    a verified analyst wave count -- real Elliott analysis routinely
    finds multiple valid counts for the same chart; this only ever
    reports the first internally-consistent one this heuristic finds.

    Deliberately uses pivots[-1] (the swing's structural extreme) rather
    than today's live price as the endpoint -- an earlier version swapped
    in current_price directly, which silently dropped pivots[-1] from the
    window entirely (since it replaced rather than appended), making the
    count describe stale, disconnected structure instead of the most
    recent real swing. This label is meant to combine with stage_label
    (already shown alongside it), which separately says whether price is
    now extending past that structural point or retracing from it -- e.g.
    "Wave 3" + "Retracement from swing high" together read as "recent
    structure looks like it just completed Wave 3, now pulling back",
    which is coherent Elliott framing, not a contradiction."""
    if len(pivots) < 3:
        return None
    pts = [p[2] for p in pivots]
    n = len(pts)

    if n >= 6:
        p0, p1, p2, p3, p4, p5 = pts[-6:]
        bullish = p1 > p0
        len1, len3, len5 = abs(p1 - p0), abs(p3 - p2), abs(p5 - p4)
        wave2_ok = (p2 > p0) if bullish else (p2 < p0)
        wave4_ok = (p4 > p1) if bullish else (p4 < p1)
        wave3_ok = len3 >= len1 or len3 >= len5
        wave5_dir_ok = (p5 > p4) if bullish else (p5 < p4)
        if wave2_ok and wave4_ok and wave3_ok and wave5_dir_ok:
            return "Wave 5 (ของคลื่นใหญ่" + ("ขาขึ้น" if bullish else "ขาลง") + ")"

    if n >= 5:
        p0, p1, p2, p3, p4 = pts[-5:]
        bullish = p1 > p0
        len1, len3 = abs(p1 - p0), abs(p3 - p2)
        wave2_ok = (p2 > p0) if bullish else (p2 < p0)
        wave3_ok = len3 >= len1
        wave3_dir_ok = (p3 > p1) if bullish else (p3 < p1)
        wave4_dir_ok = (p4 < p3) if bullish else (p4 > p3)
        if wave2_ok and wave3_ok and wave3_dir_ok and wave4_dir_ok:
            return "Wave 4 (ของคลื่นใหญ่" + ("ขาขึ้น" if bullish else "ขาลง") + ")"

    if n >= 4:
        p0, p1, p2, p3 = pts[-4:]
        bullish = p1 > p0
        wave2_ok = (p2 > p0) if bullish else (p2 < p0)
        wave3_dir_ok = (p3 > p2) if bullish else (p3 < p2)
        if wave2_ok and wave3_dir_ok:
            return "Wave 3 (ของคลื่นใหญ่" + ("ขาขึ้น" if bullish else "ขาลง") + ")"

    if n >= 3:
        p0, p1, p2 = pts[-3:]
        bullish = p1 > p0
        wave2_dir_ok = (p2 < p1) if bullish else (p2 > p1)
        wave2_not_full_retrace = (p2 > p0) if bullish else (p2 < p0)
        if wave2_dir_ok and wave2_not_full_retrace:
            return "Wave 2 (ของคลื่นใหญ่" + ("ขาขึ้น" if bullish else "ขาลง") + ")"

    return None


FIB_EXTENSION = 1.618
FIB_RETRACEMENT = 0.618


STOP_ATR_MULT = 2.0  # for 'extending' states, stop distance in ATRs from current price


def compute_fib_levels(pivots, stage_key, current_price, atr_abs):
    """Target/stop for the current structure.

    'extending' states (still pushing toward/past the last confirmed
    extreme): target is a Fibonacci extension of the swing just completed
    (a standard forward-projection technique). Stop is a volatility-based
    trailing stop (current_price +/- STOP_ATR_MULT*ATR), deliberately NOT
    derived from the same swing_range as the target -- an earlier version
    used the swing's own origin (`prev`) as the stop, which made reward and
    risk both scale off the identical distance with fixed Fibonacci
    multipliers, so their ratio collapsed to a constant (~0.618) for every
    single ticker in this state regardless of its actual price structure --
    a real bug caught during manual validation (AAPL/MSFT/NVDA/FPT.VN all
    showed exactly reward_risk_ratio=0.62). Using ATR for the stop instead
    decouples it from the target distance, so the ratio reflects this
    ticker's actual recent volatility vs. its projected move.

    'retracing' states (pulled back from the last confirmed extreme):
    target is a Fibonacci retracement level; stop is that extreme itself
    (the level whose breach invalidates "still retracing" and confirms a
    fresh push in the other direction) -- these don't have the same
    triviality problem since current_price is already meaningfully distant
    from `last` by construction of being in a retracement."""
    if len(pivots) < 2 or stage_key is None or not atr_abs:
        return None, None
    last, prev = pivots[-1], pivots[-2]
    swing_range = abs(last[2] - prev[2])
    if swing_range == 0:
        return None, None
    if stage_key == 'extending_up':
        return last[2] + swing_range * (FIB_EXTENSION - 1), current_price - STOP_ATR_MULT * atr_abs
    if stage_key == 'retracing_from_high':
        return last[2] - swing_range * FIB_RETRACEMENT, last[2]
    if stage_key == 'extending_down':
        return last[2] - swing_range * (FIB_EXTENSION - 1), current_price + STOP_ATR_MULT * atr_abs
    return last[2] + swing_range * FIB_RETRACEMENT, last[2]  # retracing_from_low


def compute_reward_risk(current_price, target, stop, stage_key):
    """reward_pct/risk_pct are both reported as positive magnitudes in the
    direction implied by stage_key (bullish states: upside to target,
    downside to stop; bearish states: downside to target, upside to stop)
    -- an earlier version always computed (target-current) and
    (current-stop) regardless of direction, which produced nonsensical
    negative risk percentages for bearish-oriented states (target/stop
    above current price), also caught during manual validation."""
    if not current_price or target is None or stop is None:
        return None, None, None
    bullish = stage_key in ('extending_up', 'retracing_from_low')
    if bullish:
        reward_pct = (target - current_price) / current_price * 100
        risk_pct = (current_price - stop) / current_price * 100
    else:
        reward_pct = (current_price - target) / current_price * 100
        risk_pct = (stop - current_price) / current_price * 100
    ratio = round(reward_pct / risk_pct, 2) if risk_pct and risk_pct > 0 else None
    return round(reward_pct, 2), round(risk_pct, 2), ratio


def analyze_ticker(ticker):
    hist = fetch_history(ticker)
    if hist is None:
        return {"quality": "fetch_failed", "data_through": None}
    dates, closes, volumes = hist
    trading_days = sum(1 for v in volumes if v)
    if trading_days < MIN_TRADING_DAYS:
        return {"quality": "insufficient_history", "data_through": None}
    atr_abs, atr_frac = atr_stats(closes)
    pivots = detect_pivots(closes, dates, atr_frac) if atr_frac else []
    current_price = closes[-1]
    stage_key, stage_label = label_swing_structure(pivots, current_price)
    if stage_key is None:
        return {"quality": "insufficient_history", "data_through": None}
    target, stop = compute_fib_levels(pivots, stage_key, current_price, atr_abs)
    reward_pct, risk_pct, ratio = compute_reward_risk(current_price, target, stop, stage_key)
    elliott_label = elliott_count(pivots)
    # A "retracing" target is a fixed Fibonacci level (last swing's 61.8%
    # retracement); if price has already moved past it before this batch
    # ran, reward_pct comes out <=0 -- that's not a coding error, it means
    # the setup as computed has already played out (or the stop side is
    # already breached). Surface as a distinct quality state rather than
    # showing a misleading negative reward or risk number as if it were a
    # live, actionable setup -- caught via TSLA during manual validation.
    quality = "ok"
    if reward_pct is not None and reward_pct <= 0:
        quality = "target_reached"
    elif risk_pct is not None and risk_pct <= 0:
        quality = "stop_breached"
    return {
        "quality": quality,
        "stage_key": stage_key,
        "stage_label": stage_label,
        "current_price": current_price,
        "target": round(target, 4) if target is not None else None,
        "stop": round(stop, 4) if stop is not None else None,
        "reward_pct": reward_pct,
        "risk_pct": risk_pct,
        "reward_risk_ratio": ratio if quality == "ok" else None,
        "elliott_label": elliott_label,
        "data_through": time.strftime("%Y-%m-%d", time.gmtime(dates[-1])),
    }


def build_wave_cache():
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
            cache[ticker] = result
            if result.get("quality") == "ok":
                ok += 1
        except Exception as e:
            print(f"  {ticker}: ERROR {e}")
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(underlyings)} done")
        time.sleep(0.3)  # spread requests -- shares Yahoo's host with the live scanner

    tmp_path = CACHE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp_path, CACHE_PATH)  # atomic write, scanner never sees a half-written file
    print(f"Done: {ok}/{len(underlyings)} resolved with a swing stage. Cache written to {CACHE_PATH}")


if __name__ == "__main__":
    build_wave_cache()
