import os
import sys
from datetime import datetime, timezone

import requests

TWELVE_DATA_API_KEY = "5591c559bec9447c8a07718de65c18df"
TELEGRAM_BOT_TOKEN = "8693759554:AAEtJHjHsuv7P_lU1zy55m_g5G4xxDlszcU"
TELEGRAM_CHAT_ID = "5349585326"

TIMEFRAMES = [
    ("W", "1week"),
    ("D", "1day"),
    ("4H", "4h"),
]


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    print(f"[Telegram] sending to chat_id={TELEGRAM_CHAT_ID!r}")
    try:
        resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        print(f"[Telegram] status={resp.status_code} body={resp.text[:300]}")
        resp.raise_for_status()
        print("[Telegram] sent OK")
    except requests.RequestException as exc:
        print(f"[Telegram] failed: {exc}", file=sys.stderr)

def fetch_candles(label, interval):
    url = (
        "https://api.twelvedata.com/time_series"
        f"?symbol=EUR/USD&interval={interval}&outputsize=50&apikey={TWELVE_DATA_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=15)
    except requests.RequestException as exc:
        return None, f"{label} request failed: {exc}"

    if resp.status_code != 200:
        return None, f"{label} HTTP {resp.status_code}"

    data = resp.json()
    if data.get("status") == "error":
        msg = data.get("message", "unknown error")
        return None, f"{label} API error: {msg}"

    values = data.get("values")
    if not values:
        return None, f"{label} returned no candle data"

    # Twelve Data returns newest-first; reverse to oldest-first for BOS math
    candles = [
        {
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
        }
        for c in reversed(values)
    ]
    return candles, None


def classify_trend(candles):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    close = candles[-1]["close"]
    n = len(candles)

    swing_highs = []
    swing_lows = []

    # Valid swing window: need 2 bars on each side
    for i in range(2, n - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
            swing_highs.append(highs[i])
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
            swing_lows.append(lows[i])

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "RANGING"

    latest_sh = swing_highs[-1]
    latest_sl = swing_lows[-1]

    # Higher highs + higher lows sequence
    hh = swing_highs[-1] > swing_highs[-2]
    hl = swing_lows[-1] > swing_lows[-2]
    # Lower highs + lower lows sequence
    lh = swing_highs[-1] < swing_highs[-2]
    ll = swing_lows[-1] < swing_lows[-2]

    if close > latest_sh and hh and hl:
        return "BULLISH"
    if close < latest_sl and lh and ll:
        return "BEARISH"
    return "RANGING"


def main():
    # missing = [v for v in ("TWELVE_DATA_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(v)]
    # if missing:
    #     print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
    #     sys.exit(1)

    candle_data = {}
    for label, interval in TIMEFRAMES:
        candles, err = fetch_candles(label, interval)
        if err:
            send_telegram(f"⚠️ EURUSD Alert Error — {err}\n{utc_now()} UTC")
            sys.exit(1)
        candle_data[label] = candles

    results = {label: classify_trend(candle_data[label]) for label, _ in TIMEFRAMES}

    bullish_tfs = [tf for tf, d in results.items() if d == "BULLISH"]
    bearish_tfs = [tf for tf, d in results.items() if d == "BEARISH"]

    ts = utc_now()
    if len(bullish_tfs) >= 2:
        send_telegram(f"🟢 EURUSD BULLISH — {'/'.join(bullish_tfs)}\n{ts} UTC")
    elif len(bearish_tfs) >= 2:

        send_telegram(f"🔴 EURUSD BEARISH — {'/'.join(bearish_tfs)}\n{ts} UTC")

    send_telegram(f"test")

if __name__ == "__main__":
    main()
