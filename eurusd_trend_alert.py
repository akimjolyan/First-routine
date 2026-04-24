import os
import sys
import time
from datetime import datetime, timezone

import requests

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

PAIRS = [
    "EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF", "AUD/USD",
    "USD/CAD", "NZD/USD", "EUR/JPY", "GBP/JPY", "EUR/GBP",
    "EUR/CHF", "EUR/AUD", "EUR/CAD", "AUD/JPY", "GBP/CHF",
    "GBP/AUD", "GBP/CAD", "AUD/CHF", "AUD/CAD", "NZD/JPY",
]

TIMEFRAMES = [
    ("W", "1week"),
    ("D", "1day"),
    ("4H", "4h"),
]

_RETRY_DELAYS = [2, 4, 8]

_OUTPUTSIZES = {"W": 200, "D": 100, "4H": 100}

# Free plan: 8 credits/min, each symbol = 1 credit
_BATCH_SIZE = 8
_RATE_LIMIT_WAIT = 61  # seconds between batches


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
                print(f"Telegram send failed: {exc}", file=sys.stderr)
            else:
                time.sleep(delay)


def fetch_batch(pairs, label, interval, outputsize):
    """Fetch a batch of pairs in one API call. Returns {pair: [candles]} and errors."""
    symbols = ",".join(pairs)
    url = (
        "https://api.twelvedata.com/time_series"
        f"?symbol={symbols}&interval={interval}&outputsize={outputsize}&apikey={TWELVE_DATA_API_KEY}"
    )
    last_err = None
    for attempt, delay in enumerate(_RETRY_DELAYS, 1):
        try:
            resp = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            last_err = f"{label} request failed: {exc}"
            if attempt < len(_RETRY_DELAYS):
                time.sleep(delay)
            continue

        if resp.status_code != 200:
            return {}, [f"{label} HTTP {resp.status_code}"]

        data = resp.json()

        if data.get("status") == "error":
            return {}, [f"{label} API error: {data.get('message', 'unknown')}"]

        # Single-symbol response has "values" at top level
        if "values" in data:
            data = {pairs[0]: data}

        # Build a lookup tolerant of key format differences (EUR/USD vs EURUSD etc.)
        normalized = {k.replace("/", "").upper(): v for k, v in data.items()}

        candles_by_pair = {}
        errors = []
        for pair in pairs:
            pair_data = data.get(pair) or normalized.get(pair.replace("/", "").upper(), {})
            if pair_data.get("status") == "error":
                errors.append(f"{pair} {label}: {pair_data.get('message', 'unknown')}")
                continue
            values = pair_data.get("values")
            if not values:
                errors.append(f"{pair} {label}: no candle data")
                continue
            candles_by_pair[pair] = [
                {
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                }
                for c in reversed(values)
            ]
        return candles_by_pair, errors

    return {}, [last_err]


def fetch_all(all_candles, all_errors):
    """Fetch all pairs across all timeframes, respecting the 8 credits/min rate limit."""
    call_number = 0
    batches = [PAIRS[i:i + _BATCH_SIZE] for i in range(0, len(PAIRS), _BATCH_SIZE)]

    for label, interval in TIMEFRAMES:
        for batch in batches:
            if call_number > 0:
                print(f"Rate limit pause {_RATE_LIMIT_WAIT}s before next batch...")
                time.sleep(_RATE_LIMIT_WAIT)
            candles_by_pair, errors = fetch_batch(batch, label, interval, _OUTPUTSIZES[label])
            all_errors.extend(errors)
            for pair, candles in candles_by_pair.items():
                all_candles[pair][label] = candles
            call_number += 1


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
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
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
    missing = [name for name, val in [
        ("TWELVE_DATA_API_KEY", TWELVE_DATA_API_KEY),
        ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
        ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
    ] if not val]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    ts = utc_now()
    send_telegram(f"🔍 Forex Routine Started — Top 20 Pairs\n{ts} UTC")

    all_candles = {pair: {} for pair in PAIRS}
    all_errors = []

    fetch_all(all_candles, all_errors)

    if all_errors:
        send_telegram("⚠️ Fetch errors:\n" + "\n".join(all_errors))

    bullish, bearish, ranging = [], [], []
    for pair in PAIRS:
        tf_data = all_candles[pair]
        if len(tf_data) < len(TIMEFRAMES):
            continue
        results = {label: classify_trend(tf_data[label]) for label, _ in TIMEFRAMES}
        bullish_tfs = [tf for tf, d in results.items() if d == "BULLISH"]
        bearish_tfs = [tf for tf, d in results.items() if d == "BEARISH"]
        tag = pair.replace("/", "")
        if len(bullish_tfs) >= 2:
            bullish.append(f"{tag} ({'/'.join(bullish_tfs)})")
        elif len(bearish_tfs) >= 2:
            bearish.append(f"{tag} ({'/'.join(bearish_tfs)})")
        else:
            ranging.append(tag)

    ts = utc_now()
    lines = [f"📊 Forex Scan — {ts} UTC"]
    if bullish:
        lines.append("\n🟢 BULLISH:\n" + " · ".join(bullish))
    if bearish:
        lines.append("\n🔴 BEARISH:\n" + " · ".join(bearish))
    if ranging:
        lines.append("\n⚪ NO SIGNAL:\n" + " · ".join(ranging))

    send_telegram("\n".join(lines))

    if all_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
