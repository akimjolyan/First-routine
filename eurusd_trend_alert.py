import os
import sys
import time
from datetime import datetime, timezone

import requests

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TIMEFRAMES = [
    ("W", "1week"),
    ("D", "1day"),
    ("4H", "4h"),
]

_RETRY_DELAYS = [2, 4, 8]

# More candles for weekly to guarantee enough swing points
_OUTPUTSIZES = {"W": 200, "D": 100, "4H": 100}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for attempt, delay in enumerate(_RETRY_DELAYS, 1):
        try:
            resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
            resp.raise_for_status()
            return
        except requests.RequestException as exc:
            if attempt == len(_RETRY_DELAYS):
                print(f"Telegram send failed after {attempt} attempts: {exc}", file=sys.stderr)
            else:
                time.sleep(delay)


def fetch_candles(label, interval, outputsize):
    url = (
        "https://api.twelvedata.com/time_series"
        f"?symbol=EUR/USD&interval={interval}&outputsize={outputsize}&apikey={TWELVE_DATA_API_KEY}"
    )
    last_err = None
    for attempt, delay in enumerate(_RETRY_DELAYS, 1):
        try:
            resp = requests.get(url, timeout=15)
        except requests.RequestException as exc:
            last_err = f"{label} request failed: {exc}"
            if attempt < len(_RETRY_DELAYS):
                time.sleep(delay)
            continue

        if resp.status_code != 200:
            return None, f"{label} HTTP {resp.status_code}"

        data = resp.json()
        if data.get("status") == "error":
            return None, f"{label} API error: {data.get('message', 'unknown error')}"

        values = data.get("values")
        if not values:
            return None, f"{label} returned no candle data"

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

    return None, last_err


def classify_trend(candles):
    if len(candles) < 5:
        return "RANGING"

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    close = candles[-1]["close"]
    n = len(candles)

    swing_highs = []
    swing_lows = []

    for i in range(2, n - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
            swing_highs.append(highs[i])
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
            swing_lows.append(lows[i])

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "RANGING"

    hh = swing_highs[-1] > swing_highs[-2]
    hl = swing_lows[-1] > swing_lows[-2]
    lh = swing_highs[-1] < swing_highs[-2]
    ll = swing_lows[-1] < swing_lows[-2]

    if close > swing_highs[-1] and hh and hl:
        return "BULLISH"
    if close < swing_lows[-1] and lh and ll:
        return "BEARISH"
    return "RANGING"


def main():
    missing = [v for v in ("TWELVE_DATA_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(v)]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    ts = utc_now()
    send_telegram(f"🔍 EURUSD Routine Started — {ts} UTC")

    errors = []
    candle_data = {}
    for label, interval in TIMEFRAMES:
        candles, err = fetch_candles(label, interval, outputsize=_OUTPUTSIZES[label])
        if err:
            errors.append(err)
        else:
            candle_data[label] = candles

    if errors:
        send_telegram(f"⚠️ EURUSD Alert Error\n" + "\n".join(errors) + f"\n{ts} UTC")
        sys.exit(1)

    results = {label: classify_trend(candle_data[label]) for label, _ in TIMEFRAMES}

    bullish_tfs = [tf for tf, d in results.items() if d == "BULLISH"]
    bearish_tfs = [tf for tf, d in results.items() if d == "BEARISH"]

    ts = utc_now()

    if len(bullish_tfs) >= 2:
        send_telegram(f"🟢 EURUSD BULLISH — {'/'.join(bullish_tfs)}\n{ts} UTC")
    elif len(bearish_tfs) >= 2:
        send_telegram(f"🔴 EURUSD BEARISH — {'/'.join(bearish_tfs)}\n{ts} UTC")
    else:
        tf_summary = " | ".join(f"{tf}: {results[tf]}" for tf, _ in TIMEFRAMES)
        send_telegram(f"⚪ EURUSD NO SIGNAL — {tf_summary}\n{ts} UTC")


if __name__ == "__main__":
    main()
