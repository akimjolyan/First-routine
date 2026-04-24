import os
import sys
import time
from datetime import datetime, timezone

import requests

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

PAIRS = ["EUR/USD", "GBP/USD", "EUR/GBP"]

TIMEFRAMES = [
    ("W", "1week"),
    ("D", "1day"),
    ("4H", "4h"),
]

_RETRY_DELAYS = [2, 4, 8]

_OUTPUTSIZES = {"W": 200, "D": 100, "4H": 100}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for attempt, delay in enumerate(_RETRY_DELAYS, 1):
        try:
            resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
            print(f"[Telegram] status={resp.status_code} body={resp.text[:200]}")
            resp.raise_for_status()
            return
        except requests.RequestException as exc:
            print(f"[Telegram] attempt {attempt} failed: {exc}", file=sys.stderr)
            if attempt == len(_RETRY_DELAYS):
                print(f"[Telegram] giving up after {attempt} attempts", file=sys.stderr)
            else:
                time.sleep(delay)


def fetch_candles(pair, label, interval, outputsize):
    symbol = pair.replace("/", "%2F")
    url = (
        "https://api.twelvedata.com/time_series"
        f"?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={TWELVE_DATA_API_KEY}"
    )
    last_err = None
    for attempt, delay in enumerate(_RETRY_DELAYS, 1):
        try:
            resp = requests.get(url, timeout=15)
        except requests.RequestException as exc:
            last_err = f"{pair} {label} request failed: {exc}"
            if attempt < len(_RETRY_DELAYS):
                time.sleep(delay)
            continue

        if resp.status_code != 200:
            return None, f"{pair} {label} HTTP {resp.status_code}"

        data = resp.json()
        if data.get("status") == "error":
            return None, f"{pair} {label} API error: {data.get('message', 'unknown error')}"

        values = data.get("values")
        if not values:
            return None, f"{pair} {label} returned no candle data"

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


def analyze_pair(pair):
    errors = []
    candle_data = {}
    for label, interval in TIMEFRAMES:
        candles, err = fetch_candles(pair, label, interval, outputsize=_OUTPUTSIZES[label])
        if err:
            errors.append(err)
        else:
            candle_data[label] = candles

    if errors:
        return None, errors

    results = {label: classify_trend(candle_data[label]) for label, _ in TIMEFRAMES}
    return results, []


def format_pair_message(pair, results, ts):
    bullish_tfs = [tf for tf, d in results.items() if d == "BULLISH"]
    bearish_tfs = [tf for tf, d in results.items() if d == "BEARISH"]
    tag = pair.replace("/", "")

    if len(bullish_tfs) >= 2:
        return f"🟢 {tag} BULLISH — {'/'.join(bullish_tfs)}\n{ts} UTC"
    if len(bearish_tfs) >= 2:
        return f"🔴 {tag} BEARISH — {'/'.join(bearish_tfs)}\n{ts} UTC"
    tf_summary = " | ".join(f"{tf}: {results[tf]}" for tf, _ in TIMEFRAMES)
    return f"⚪ {tag} NO SIGNAL — {tf_summary}\n{ts} UTC"


def main():
    missing = [v for v in ("TWELVE_DATA_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(v)]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    ts = utc_now()
    send_telegram(f"🔍 Routine Started — EUR/USD · GBP/USD · EUR/GBP\n{ts} UTC")

    had_error = False
    for pair in PAIRS:
        results, errors = analyze_pair(pair)
        ts = utc_now()
        if errors:
            send_telegram(f"⚠️ {pair} Error\n" + "\n".join(errors) + f"\n{ts} UTC")
            had_error = True
        else:
            send_telegram(format_pair_message(pair, results, ts))

    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
