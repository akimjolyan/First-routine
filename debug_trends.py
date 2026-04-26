"""
Run this locally to debug why no signals are firing.
  python debug_trends.py
"""
import yfinance as yf

PAIRS = [
    "EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF", "AUD/USD",
    "USD/CAD", "NZD/USD", "EUR/JPY", "GBP/JPY", "EUR/GBP",
    "EUR/CHF", "EUR/AUD", "EUR/CAD", "AUD/JPY", "GBP/CHF",
    "GBP/AUD", "GBP/CAD", "AUD/CHF", "AUD/CAD", "NZD/JPY",
]

TIMEFRAMES = [
    ("W",  "1wk", 200, "5y"),
    ("D",  "1d",  100, "2y"),
    ("4H", "4h",  100, "1y"),
]


def to_yf_symbol(pair):
    return pair.replace("/", "") + "=X"


def classify_trend(candles, pair, label):
    if len(candles) < 5:
        print(f"  [{pair} {label}] RANGING — not enough candles ({len(candles)})")
        return "RANGING"

    highs = [c["high"] for c in candles]
    lows  = [c["low"]  for c in candles]
    close = candles[-1]["close"]
    n = len(candles)

    swing_highs, swing_lows = [], []
    for i in range(2, n - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows.append(lows[i])

    candles = candles[-40:]
    highs = [c["high"] for c in candles]
    lows  = [c["low"]  for c in candles]
    n = len(candles)
    swing_highs2, swing_lows2 = [], []
    for i in range(2, n - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs2.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows2.append(lows[i])

    if len(swing_highs2) < 2 or len(swing_lows2) < 2:
        print(f"  [{pair} {label}] RANGING — not enough swings in last 40 candles")
        return "RANGING"

    hh = swing_highs2[-1] > swing_highs2[-2]
    hl = swing_lows2[-1]  > swing_lows2[-2]
    lh = swing_highs2[-1] < swing_highs2[-2]
    ll = swing_lows2[-1]  < swing_lows2[-2]

    if hh and hl:
        print(f"  [{pair} {label}] BULLISH  HH+HL in last 40 candles")
        return "BULLISH"
    if lh and ll:
        print(f"  [{pair} {label}] BEARISH  LH+LL in last 40 candles")
        return "BEARISH"

    print(f"  [{pair} {label}] RANGING")
    return "RANGING"


def fetch_timeframe(label, interval, outputsize, period):
    symbols = [to_yf_symbol(p) for p in PAIRS]
    print(f"\n=== Fetching {label} ({interval}, period={period}) ===")
    raw = yf.download(
        tickers=symbols,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
    )

    result = {}
    for pair in PAIRS:
        sym = to_yf_symbol(pair)
        try:
            df = raw[sym] if len(symbols) > 1 else raw
            df = df.dropna(subset=["Open", "High", "Low", "Close"])
            if df.empty:
                print(f"  [{pair} {label}] ERROR — empty dataframe")
                continue
            rows = df.tail(outputsize)
            result[pair] = [
                {"open": float(r["Open"]), "high": float(r["High"]),
                 "low":  float(r["Low"]),  "close": float(r["Close"])}
                for _, r in rows.iterrows()
            ]
            print(f"  [{pair} {label}] {len(result[pair])} candles, "
                  f"last close={result[pair][-1]['close']:.5f}")
        except Exception as exc:
            print(f"  [{pair} {label}] ERROR — {exc}")
    return result


def main():
    all_candles = {pair: {} for pair in PAIRS}

    for label, interval, outputsize, period in TIMEFRAMES:
        tf_data = fetch_timeframe(label, interval, outputsize, period)
        for pair, candles in tf_data.items():
            all_candles[pair][label] = candles

    print("\n\n=== TREND CLASSIFICATION ===")
    signals = []
    for pair in PAIRS:
        tf_data = all_candles[pair]
        if len(tf_data) < 3:
            print(f"\n{pair}: missing timeframes {set(['W','D','4H']) - set(tf_data.keys())}")
            continue
        print(f"\n{pair}:")
        results = {}
        for label, _, _, _ in TIMEFRAMES:
            results[label] = classify_trend(tf_data[label], pair, label)

        w, d, h4 = results["W"], results["D"], results["4H"]
        if w == d and w != "RANGING":
            tfs = "W+D+4H" if h4 == w else "W+D"
            signals.append(f"  {pair}: {w} on {tfs}")
        elif d == h4 and d != "RANGING":
            signals.append(f"  {pair}: {d} on D+4H (W={w})")

    print("\n\n=== SIGNALS ===")
    if signals:
        for s in signals:
            print(s)
    else:
        print("No signals fired.")


if __name__ == "__main__":
    main()
