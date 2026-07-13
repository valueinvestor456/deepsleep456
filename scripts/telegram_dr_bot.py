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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
STATE_PATH = os.path.join(SCRIPT_DIR, "telegram_dr_bot_state.json")
DATA_PATH = os.path.join(REPO_DIR, "dr", "dr-data.json")

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


def fundamental_url(d):
    if d.get("market") == "US":
        return f"https://stockanalysis.com/stocks/{d['yahoo_u'].lower()}/"
    tv = d.get("underlying_tv") or ""
    if ":" in tv:
        exch, ticker = tv.split(":", 1)
        sa = TV_EXCH_TO_SA.get(exch)
        if sa:
            return f"https://stockanalysis.com/quote/{sa}/{ticker.lower()}/"
    return None


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
        underlying_tv = d0.get("underlying_tv")
        if underlying_tv:
            url = "https://www.tradingview.com/chart/?symbol=" + urllib.parse.quote(underlying_tv)
            buttons.append((f"📈 ดูกราฟ {key}", url))

    if len(group_keys) > len(shown_groups):
        lines.append(f"... และอีก {len(group_keys) - len(shown_groups)} หุ้นแม่")
    lines.append("")
    lines.append('🌐 <a href="https://deepsleep456.com/dr">ดูทั้งหมดที่ deepsleep456.com/dr</a>')
    return {"text": "\n".join(lines).rstrip(), "buttons": buttons or None, "parse_mode": "HTML"}


def handle_command(text):
    text = text.strip()
    if not text.startswith("/"):
        return "พิมพ์ /dr คำค้นหา (เช่น /dr msft) — คำสั่งอื่นต้องรอ PC หลักเปิดอยู่"
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd == "/dr":
        return cmd_dr(arg)
    if cmd in ("/help", "/start"):
        return "ตอนนี้ PC หลักปิดอยู่ ใช้ได้แค่ /dr คำค้นหา (เช่น /dr nvda) — คำสั่งอื่น (/ingest /dashboard /query /publish) ต้องรอ PC เปิด"
    return f"คำสั่ง {cmd} ต้องรอ PC หลักเปิดอยู่ — ตอนนี้ใช้ได้แค่ /dr คำค้นหา"


def git_commit_state():
    """Persist the offset immediately after processing a message, not just at
    exit -- so a killed/cancelled run never re-answers something it already
    replied to. Silently no-ops if nothing changed.

    This runs mid-loop over a period of hours, during which other workflows
    (e.g. the hourly market-data refresh) can push to main -- so a plain
    `git push` can get rejected as non-fast-forward. Rebase-and-retry once;
    if that still fails, log and move on, the next successful commit in a
    later loop iteration will carry the offset forward instead."""
    try:
        diff = subprocess.run(["git", "diff", "--quiet", "--", STATE_PATH], cwd=REPO_DIR)
        if diff.returncode == 0:
            return  # unchanged
        subprocess.run(["git", "add", STATE_PATH], cwd=REPO_DIR, check=True)
        subprocess.run(["git", "commit", "-m", "Telegram DR bot: advance offset [skip ci]"], cwd=REPO_DIR, check=True)
        push = subprocess.run(["git", "push"], cwd=REPO_DIR)
        if push.returncode != 0:
            subprocess.run(["git", "pull", "--rebase"], cwd=REPO_DIR, check=True)
            subprocess.run(["git", "push"], cwd=REPO_DIR, check=True)
    except Exception as e:
        print("git_commit_state error (offset saved locally, will retry next commit):", e)


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
