import os
import sys
import time
from datetime import datetime, timezone

import requests
import yfinance as yf

TELEGRAM_BOT_TOKEN = "8693759554:AAEtJHjHsuv7P_lU1zy55m_g5G4xxDlszcU"
TELEGRAM_CHAT_ID = "5349585326"

PAIRS = [
    "EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF", "AUD/USD",
    "USD/CAD", "NZD/USD", "EUR/JPY", "GBP/JPY", "EUR/GBP",
    "EUR/CHF", "EUR/AUD", "EUR/CAD", "AUD/JPY", "GBP/CHF",
    "GBP/AUD", "GBP/CAD", "AUD/CHF", "AUD/CAD", "NZD/JPY",
]

# (label, yfinance interval, number of candles to keep)
TIMEFRAMES = [
    ("W",  "1wk", 200),
    ("D",  "1d",  100),
    ("4H", "4h",  100),
]

_RETRY_DELAYS = [2, 4, 8]


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def to_yf_symbol(pair):
    """Convert 'EUR/USD' to 'EURUSD=X' for yfinance."""
    return pair.replace("/", "") + "=X"


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


def fetch_timeframe(label, interval, outputsize):
    """Fetch OHLC candles for all pairs on one timeframe. Returns {pair: [candles]}, [errors]."""
    symbols = [to_yf_symbol(p) for p in PAIRS]
    period = "5y" if label == "W" else "2y" if label == "D" else "1y"

    for attempt, delay in enumerate(_RETRY_DELAYS, 1):
        try:
            raw = yf.download(
                tickers=symbols,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
            )
            break
        except Exception as exc:
            if attempt == len(_RETRY_DELAYS):
                return {}, [f"{label} download failed: {exc}"]
            time.sleep(delay)

    candles_by_pair = {}
    errors = []

    for pair in PAIRS:
        sym = to_yf_symbol(pair)
        try:
            if len(symbols) == 1:
                df = raw
            else:
                df = raw[sym]

            df = df.dropna(subset=["Open", "High", "Low", "Close"])
            if df.empty:
                errors.append(f"{pair} {label}: no candle data")
                continue

            rows = df.tail(outputsize)
            candles_by_pair[pair] = [
                {
                    "open":  float(row["Open"]),
                    "high":  float(row["High"]),
                    "low":   float(row["Low"]),
                    "close": float(row["Close"]),
                }
                for _, row in rows.iterrows()
            ]
        except Exception as exc:
            errors.append(f"{pair} {label}: {exc}")

    print(f"[Debug] {label} fetched {len(candles_by_pair)}/{len(PAIRS)} pairs")
    return candles_by_pair, errors


def fetch_all(all_candles, all_errors):
    for label, interval, outputsize in TIMEFRAMES:
        candles_by_pair, errors = fetch_timeframe(label, interval, outputsize)
        all_errors.extend(errors)
        for pair, candles in candles_by_pair.items():
            all_candles[pair][label] = candles


_TREND_WINDOW = 40  # only look at recent candles for trend structure


def classify_trend(candles):
    candles = candles[-_TREND_WINDOW:]
    if len(candles) < 5:
        return "RANGING"

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
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
    hl = swing_lows[-1]  > swing_lows[-2]
    lh = swing_highs[-1] < swing_highs[-2]
    ll = swing_lows[-1]  < swing_lows[-2]

    if hh and hl:
        return "BULLISH"
    if lh and ll:
        return "BEARISH"
    return "RANGING"


def main():
    missing = [name for name, val in [
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
        results = {label: classify_trend(tf_data[label]) for label, _, _ in TIMEFRAMES}
        w, d, h4 = results["W"], results["D"], results["4H"]
        tag = pair.replace("/", "")

        # Signal requires W+D aligned, or D+4H aligned
        if w == d and w != "RANGING":
            tfs = f"W+D+4H" if h4 == w else "W+D"
            if w == "BULLISH":
                bullish.append(f"{tag} ({tfs})")
            else:
                bearish.append(f"{tag} ({tfs})")
        elif d == h4 and d != "RANGING":
            if d == "BULLISH":
                bullish.append(f"{tag} (D+4H)")
            else:
                bearish.append(f"{tag} (D+4H)")
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
