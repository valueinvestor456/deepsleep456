#!/usr/bin/env python3
"""
Always-on fallback for the DR /dr command, for when the full Telegram bridge
(telegram-bot/bridge.py in the "investment with ai" project) isn't running
because the PC is off.

Runs as a genuine long-poll loop (getUpdates with a 25s timeout, replies
arrive within ~1-2s of being sent) inside a single GitHub Actions job, not
a brief check-and-exit -- hosted runners cap a job at 6h, so this exits
cleanly at 5.5h and the workflow's cron schedule + concurrency group starts
the next run to pick the loop back up, seamlessly. Offset is committed back
to the repo immediately after every reply, not just at exit, so a killed
run never re-answers a message it already handled.

Only handles /dr <keyword>. Everything else (/ingest, /dashboard, /query,
/publish) needs the full project and Claude CLI, which don't exist on this
runner, so those get a short "PC bot only" reply instead.

NOTE: if the PC bridge is ALSO running at the same time as this loop, both
are genuinely long-polling the same bot token, so /dr will very likely get
answered twice (once by each). Harmless, just noisy -- stop one of them if
that's annoying.

Reads dr/dr-data.json (published alongside dr/index.html by the project's
.tools/build_dr_page.py) -- this script never rescans live itself.

Env vars required (set as GitHub Actions secrets):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import calendar
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
STATE_PATH = os.path.join(SCRIPT_DIR, "telegram_dr_bot_state.json")
DATA_PATH = os.path.join(REPO_DIR, "dr", "dr-data.json")
MARKET_DATA_PATH = os.path.join(REPO_DIR, "usd", "market-data.json")
MANUAL_FUT_PATH = os.path.join(REPO_DIR, "usd", "manual-fut-price.json")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TOKEN or not ALLOWED_CHAT_ID:
    print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID env var, exiting.")
    sys.exit(0)

ALLOWED_CHAT_ID = int(ALLOWED_CHAT_ID)


def api_call(method, params=None, timeout=20):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8") if params is not None else None
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_message(chat_id, text, buttons=None, parse_mode=None):
    MAX = 3900
    if not text:
        text = "(no reply text)"
    chunks = [text[i:i + MAX] for i in range(0, len(text), MAX)]
    for i, chunk in enumerate(chunks):
        params = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true"}
        if parse_mode:
            params["parse_mode"] = parse_mode
        if buttons and i == len(chunks) - 1:
            keyboard = [[{"text": label, "url": url}] for label, url in buttons]
            params["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
        try:
            api_call("sendMessage", params)
        except urllib.error.URLError as e:
            print("send_message error:", e)


def load_offset():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("offset", 0)
        except Exception:
            return 0
    return 0


def save_offset(offset):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"offset": offset}, f)


TV_EXCH_TO_SA = {"HKEX": "hkg", "TSE": "tyo", "SGX": "sgx", "EURONEXT": "epa", "SIX": "swx", "SSE": "sha", "SZSE": "she"}


# Same override table as scripts/dr_scan/page_template.html's FUNDAMENTAL_OVERRIDE
# and telegram-bot/bridge.py's copy (kept in sync manually).
FUNDAMENTAL_OVERRIDE = {
    "FUEVFVND01": "https://www.dragoncapital.com.vn/individual/vi/product/a0eJ2000001XA0ZIAW/vndiamond#overview",
}


def fundamental_url(d):
    if d["sym"] in FUNDAMENTAL_OVERRIDE:
        return FUNDAMENTAL_OVERRIDE[d["sym"]]
    if d.get("market") == "US":
        return f"https://stockanalysis.com/stocks/{d['yahoo_u'].lower()}/"
    yahoo_u = d.get("yahoo_u") or ""
    if yahoo_u.endswith(".VN"):
        return f"https://finance.vietstock.vn/{yahoo_u[:-3]}-x.htm"
    tv = d.get("underlying_tv") or ""
    if ":" in tv:
        exch, ticker = tv.split(":", 1)
        sa = TV_EXCH_TO_SA.get(exch)
        if sa:
            return f"https://stockanalysis.com/quote/{sa}/{ticker.lower()}/"
    return None


def wave_line(d0):
    """Formats the Elliott Wave / support-resistance line for a Telegram
    reply. Only rendered when elliott_count() (wave_analysis.py) found a
    real motive (1-5) or corrective (A-B-C) fit -- the generic "Extending
    up-swing"/"Retracement from swing high" phrasing was cut per user
    feedback (not useful on its own). Returns "" otherwise."""
    w = d0.get("wave")
    elliott = w.get("elliott_label") if w else None
    if not w or not elliott:
        return ""
    status = ""
    if w.get("live_status") == "target_reached":
        status = " ⚠️ ถึง target แล้ว"
    elif w.get("live_status") == "stop_breached":
        status = " 🛑 ทะลุ stop แล้ว"
    elliott_str = html.escape(elliott)
    current = w.get("current_price")
    levels = [v for v in (w.get("target"), w.get("stop")) if v is not None]
    resistance = min((v for v in levels if current is not None and v >= current), default=None)
    support = max((v for v in levels if current is not None and v < current), default=None)
    parts = []
    if resistance is not None:
        parts.append(f"แนวต้าน +{(resistance - current) / current * 100:.2f}%")
    if support is not None:
        parts.append(f"แนวรับ {(support - current) / current * 100:.2f}%")
    level_str = " · " + " · ".join(parts) if parts else ""
    return f"🌊 {elliott_str}{level_str}{status}"


def cmd_dr(arg):
    if not arg:
        return "ใช้แบบ: /dr คำค้นหา เช่น /dr msft หรือ /dr CATL01"

    if not os.path.exists(DATA_PATH):
        return "[error] ยังไม่มีข้อมูล DR (dr/dr-data.json) บน repo นี้"

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            rows = json.load(f)
    except Exception as e:
        return f"[error] อ่านข้อมูล DR ไม่สำเร็จ: {e}"

    q = arg.strip().lower()
    matches = [
        r for r in rows
        if q in (r.get("sym") or "").lower()
        or q in (r.get("name") or "").lower()
        or q in (r.get("yahoo_u") or "").lower()
    ]
    if not matches:
        return f"ไม่พบ DR หรือหุ้นแม่ที่ตรงกับ \"{arg}\" — ลองดูรายชื่อทั้งหมดที่ deepsleep456.com/dr"

    groups = {}
    for r in matches:
        key = r.get("yahoo_u") or r["sym"]
        groups.setdefault(key, []).append(r)

    def group_score(items):
        return max((abs(r.get("premium_pct") or 0) for r in items), default=0)
    group_keys = sorted(groups.keys(), key=lambda k: group_score(groups[k]), reverse=True)

    latest_scan = max((r.get("set_market_datetime") or "" for r in rows), default="")
    scan_label = latest_scan.replace("T", " ").split(".")[0] if latest_scan else "ไม่ทราบ"
    lines = [f"ผลค้นหา \"{html.escape(arg)}\" ({len(matches)} DR, {len(groups)} หุ้นแม่) — ข้อมูล ณ {scan_label}",
             "(ตอบผ่าน GitHub Actions เพราะ PC หลักปิดอยู่ — /dr เท่านั้นที่ใช้ได้ตอนนี้)", ""]

    buttons = []
    shown_groups = group_keys[:8]
    for key in shown_groups:
        items = sorted(groups[key], key=lambda r: abs(r.get("premium_pct") or 0), reverse=True)
        d0 = items[0]
        u_price = d0.get("underlying_price")
        ccy = d0.get("ccy") or ""
        price_line = f"{u_price:,.2f} {ccy}" if u_price is not None else "n/a"
        name_esc = html.escape(d0.get('name', ''))
        key_esc = html.escape(key)
        fa_url = fundamental_url(d0)
        if fa_url:
            label = f'<a href="{fa_url}">{name_esc} ({key_esc})</a>'
        else:
            label = f"{name_esc} ({key_esc})"
        pe_line = ""
        if d0.get("pe_ratio") is not None or d0.get("forward_pe") is not None:
            pe_str = f"{d0['pe_ratio']:.1f}" if d0.get("pe_ratio") is not None else "n/a"
            fwd_str = f"{d0['forward_pe']:.1f}" if d0.get("forward_pe") is not None else "n/a"
            pe_line = f" — P/E {pe_str} · Fwd P/E {fwd_str}"
        lines.append(f"📍 {label} — ราคาล่าสุด {price_line}{pe_line}")
        wl = wave_line(d0)
        if wl:
            lines.append(wl)
        for r in items:
            actual = r.get("actual_price")
            fair = r.get("fair_price")
            prem = r.get("premium_pct")
            sym_esc = html.escape(r['sym'])
            if fair is None:
                lines.append(f"  {sym_esc} — ราคาจริง {actual} — [ไม่มี fair price]")
            else:
                direction = "premium" if (prem or 0) > 0 else ("discount" if (prem or 0) < 0 else "")
                sign = "+" if (prem or 0) > 0 else ""
                lines.append(f"  {sym_esc} — จริง {actual} vs Fair {fair} — {sign}{prem:.2f}% {direction}")
        lines.append("")
        symbol = d0.get("underlying_tv") or ("SET:" + d0["sym"])
        url = "https://www.tradingview.com/chart/?symbol=" + urllib.parse.quote(symbol)
        buttons.append((f"📈 กราฟหุ้นแม่ {key}", url))

    if len(group_keys) > len(shown_groups):
        lines.append(f"... และอีก {len(group_keys) - len(shown_groups)} หุ้นแม่")
    lines.append("")
    lines.append('🌐 <a href="https://deepsleep456.com/dr">ดูทั้งหมดที่ deepsleep456.com/dr</a>')
    return {"text": "\n".join(lines).rstrip(), "buttons": buttons or None, "parse_mode": "HTML"}


# TFEX USD futures list quarterly (Mar/Jun/Sep/Dec). Same month-code table as
# usd/index.html's TFEX_MONTH_CODES, inverted (0-indexed month -> letter).
TFEX_QUARTER_MONTHS = [3, 6, 9, 12]
MONTH_CODE_BY_IDX = {0: "F", 1: "G", 2: "H", 3: "J", 4: "K", 5: "M",
                      6: "N", 7: "Q", 8: "U", 9: "V", 10: "X", 11: "Z"}


def next_tfex_settlement(today=None):
    """Nearest unexpired quarterly TFEX settlement, approximated the same way
    as usd/index.html's updateSettlementFromSeries: last calendar day of the
    contract month minus 2 days (no Thai holiday calendar) -- off by ~1-2
    business days around weekends/holidays, treat as approximate."""
    today = today or date.today()
    y = today.year
    while True:
        for m in TFEX_QUARTER_MONTHS:
            if y == today.year and m < today.month:
                continue
            last_day = calendar.monthrange(y, m)[1]
            settlement = date(y, m, last_day) - timedelta(days=2)
            if settlement >= today:
                return settlement, y, m
        y += 1


def fetch_spot_usdthb():
    """Same sources/order as usd/index.html's fetchAll(): open.er-api.com
    first, api.frankfurter.dev as fallback."""
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=15) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        thb = (j.get("rates") or {}).get("THB")
        if thb:
            return float(thb)
    except Exception as e:
        print("fetch_spot_usdthb (open.er-api.com) error:", e)
    try:
        url = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=THB"
        with urllib.request.urlopen(url, timeout=15) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        thb = (j.get("rates") or {}).get("THB")
        if thb:
            return float(thb)
    except Exception as e:
        print("fetch_spot_usdthb (frankfurter.dev) error:", e)
    return None


def cmd_fut(arg=""):
    """CIP futures fair value, same formula as usd/index.html's recalcAnchors():
    cipFair = S * (1 + iTH/100*t) / (1 + iUS/100*t), t = days/365.
    Interest rates come from usd/market-data.json (hourly TE scrape); spot is
    fetched live. There's no free auto source for the actual traded futures
    price (same limitation as the dashboard's own #fut input -- ราคา futures
    จริง ไม่มี auto ฟรี), so "/fut" alone only reports the fair value estimate.
    Pass the actual price you're seeing (e.g. "/fut 33.45" from your own
    TradingView/broker) to get a basis + RICH/CHEAP/FAIR verdict too, same
    thresholds as the dashboard's CIP section (+/-0.03 THB)."""
    if not os.path.exists(MARKET_DATA_PATH):
        return "[error] ยังไม่มีข้อมูล market-data.json บน repo นี้"
    try:
        with open(MARKET_DATA_PATH, "r", encoding="utf-8") as f:
            md = json.load(f)
    except Exception as e:
        return f"[error] อ่าน market-data.json ไม่สำเร็จ: {e}"

    i_th = (md.get("th_rate") or {}).get("last")
    i_us = (md.get("us_rate") or {}).get("last")
    if i_th is None or i_us is None:
        return "[error] ไม่มีดอกเบี้ยไทย/สหรัฐใน market-data.json ตอนนี้"

    fut_price = None
    if arg.strip():
        try:
            fut_price = float(arg.strip())
        except ValueError:
            return f'[error] "{arg}" ไม่ใช่ตัวเลข — ใช้แบบ: /fut 33.45'

    spot = fetch_spot_usdthb()
    if spot is None:
        return "[error] ดึงราคา USD/THB spot ไม่สำเร็จ (open.er-api.com และ frankfurter.dev ล่มทั้งคู่)"

    settlement, y, m = next_tfex_settlement()
    days = max((settlement - date.today()).days, 1)
    t = days / 365.0
    cip_fair = spot * (1 + i_th / 100 * t) / (1 + i_us / 100 * t)
    series = f"USD{MONTH_CODE_BY_IDX[m - 1]}{y % 100:02d}"

    lines = [
        f"📐 Futures ยุติธรรม (CIP) — {series}",
        f"Spot USD/THB: {spot:.4f}",
        f"ดอกเบี้ยไทย {i_th:.2f}% / สหรัฐ {i_us:.2f}% · {days} วันถึง settlement (≈{settlement.strftime('%d %b %Y')})",
        f"Futures ยุติธรรม: {cip_fair:.4f}",
    ]
    if fut_price is not None:
        basis = fut_price - cip_fair
        if basis > 0.03:
            verdict = "🔴 RICH — futures แพงกว่ายุติธรรม"
        elif basis < -0.03:
            verdict = "🟢 CHEAP — futures ถูกกว่ายุติธรรม"
        else:
            verdict = "⚪ FAIR — อยู่ในกรอบต้นทุน"
        lines.append(f"ราคาจริง: {fut_price:.4f} · Basis: {basis:+.4f} THB ({basis/0.01:+.1f} ticks) · {verdict}")
        save_manual_fut_price(fut_price, series, cip_fair)
    else:
        lines.append("(ไม่มีราคา futures จริงแบบ auto ฟรี — ส่ง /fut <ราคา> เช่น /fut 33.45 เพื่อเทียบ basis)")

    return "\n".join(lines)


def handle_command(text):
    text = text.strip()
    if not text.startswith("/"):
        return "พิมพ์ /dr คำค้นหา (เช่น /dr msft) หรือ /fut (futures fair value) — คำสั่งอื่นต้องรอ PC หลักเปิดอยู่"
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd == "/dr":
        return cmd_dr(arg)
    if cmd == "/fut":
        return cmd_fut(arg)
    if cmd in ("/help", "/start"):
        return ("ตอนนี้ PC หลักปิดอยู่ ใช้ได้แค่ /dr คำค้นหา (เช่น /dr nvda) และ /fut [ราคา] "
                "(USD/THB futures fair value, ใส่ราคาเช่น /fut 33.45 เพื่อเทียบ basis) "
                "— คำสั่งอื่น (/ingest /dashboard /query /publish) ต้องรอ PC เปิด")
    return f"คำสั่ง {cmd} ต้องรอ PC หลักเปิดอยู่ — ตอนนี้ใช้ได้แค่ /dr คำค้นหา หรือ /fut"


def git_commit_path(path, message):
    """Commit+push a single file immediately after it changes, not just at
    exit -- so a killed/cancelled run never loses or re-does work. Silently
    no-ops if nothing changed.

    Stages first, then diffs the *staged* tree against HEAD (`git diff
    --cached`) rather than the unstaged working tree -- `git diff --quiet`
    never flags a brand-new untracked file as changed, so a file's very
    first commit would otherwise silently never happen.

    This can run alongside other workflows (e.g. the hourly market-data
    refresh) pushing to main -- so a plain `git push` can get rejected as
    non-fast-forward. Rebase-and-retry once; if that still fails, log and
    move on, the next successful commit will carry this forward instead."""
    try:
        subprocess.run(["git", "add", path], cwd=REPO_DIR, check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet", "--", path], cwd=REPO_DIR)
        if diff.returncode == 0:
            return  # unchanged
        # Pathspec-scoped commit: commits only this path's staged change, even
        # if something else happens to be staged too (bit us once when other
        # unrelated files were sitting staged locally -- a plain `git commit
        # -m` with no pathspec swept them into this commit).
        subprocess.run(["git", "commit", "-m", message, "--", path], cwd=REPO_DIR, check=True)
        push = subprocess.run(["git", "push"], cwd=REPO_DIR)
        if push.returncode != 0:
            subprocess.run(["git", "pull", "--rebase"], cwd=REPO_DIR, check=True)
            subprocess.run(["git", "push"], cwd=REPO_DIR, check=True)
    except Exception as e:
        print(f"git_commit_path({path}) error (will retry next commit):", e)


def git_commit_state():
    git_commit_path(STATE_PATH, "Telegram DR bot: advance offset [skip ci]")


def save_manual_fut_price(price, series, cip_fair):
    """Persists the last /fut <price> submission (+ its basis vs CIP fair
    value at the time) so other consumers -- e.g. the macro-telegram-bot
    project's Macro Summary push -- can show the actual traded futures price
    too, since there's no free automated source for it (see cmd_fut)."""
    data = {
        "price": price,
        "series": series,
        "cip_fair": cip_fair,
        "basis": price - cip_fair,
        "asof": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    with open(MANUAL_FUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)
    git_commit_path(MANUAL_FUT_PATH, "Manual futures price update via /fut [skip ci]")


def main():
    # GitHub Actions hosted runners cap a single job at 6h; stop with margin
    # so this run can exit cleanly and the next scheduled run picks up the
    # poll loop again (see workflow's cron cadence + concurrency group).
    deadline = time.monotonic() + 5.5 * 3600
    offset = load_offset()
    print(f"Long-poll loop starting, offset={offset}")

    while time.monotonic() < deadline:
        try:
            resp = api_call("getUpdates", {"offset": offset, "timeout": 25}, timeout=35)
        except Exception as e:
            print("getUpdates error:", e)
            time.sleep(5)
            continue

        updates = resp.get("result", [])
        if not updates:
            continue  # long-poll timed out with nothing new; immediately re-poll

        replied = False
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message")
            if not msg:
                continue
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "")
            if chat_id != ALLOWED_CHAT_ID or not text:
                continue
            print(f"[{time.strftime('%H:%M:%S')}] > {text}")
            try:
                reply = handle_command(text)
            except Exception as e:
                reply = f"[error] {e}"
            if isinstance(reply, dict):
                send_message(chat_id, reply["text"], buttons=reply.get("buttons"), parse_mode=reply.get("parse_mode"))
            else:
                send_message(chat_id, reply)
            print(f"[{time.strftime('%H:%M:%S')}] < replied")
            replied = True

        save_offset(offset)
        if replied:
            git_commit_state()

    print("Approaching runtime cap, exiting cleanly for the next scheduled run to take over.")
    save_offset(offset)
    git_commit_state()


if __name__ == "__main__":
    main()
