"""Exit rules for momentum buys like the live agent's on 2026-10-23 (F78).

Entry: at each hour, a coin up more than 2% in 24 hours, above its 1-hour EMA20 with EMA20 over EMA50, and up in
the last hour. Bought at that hour's close, one position per coin at a time. Exits on 1-minute bars:
  current : stop 6% under the entry, sold after 6 hours
  trail   : as current, and once the high is 2% over the entry, a stop 1.5% under the highest price since entry
  breakeven: as current, and once the high is 2% over the entry, the stop moves to the entry plus the costs
  target3 : as current, and sell at +3%
Costs: 0.75% a round trip (taker in and out plus half the spreads). 17 TMN markets, about 120 days.

    uv run --no-project --with pandas python scripts/test_trailing_exits.py
"""
import csv
import statistics as st
from pathlib import Path

MARKETS = ["ADATMN", "APETMN", "ARBTMN", "BNBTMN", "BTCTMN", "DOGETMN", "ETHTMN", "LTCTMN", "PEPETMN", "PUMPTMN",
           "SANDTMN", "SOLTMN", "STMN", "SUITMN", "TRXTMN", "UNITMN", "XRPTMN"]
COST = 0.75
HOLD = 6 * 3600


def ema(values, n):
    k, out, e = 2 / (n + 1), [], None
    for v in values:
        e = v if e is None else e + k * (v - e)
        out.append(e)
    return out


def load(symbol):
    rows = list(csv.DictReader(open(Path("data/candles") / f"{symbol}_1m.csv")))
    return [(int(float(r["t"])), float(r["h"]), float(r["l"]), float(r["c"])) for r in rows]


def hourly(minutes):
    hours = {}
    for t, h, low, c in minutes:
        hours[t - t % 3600] = c  # the last close of each hour
    ts = sorted(hours)
    return ts, [hours[t] for t in ts]


def simulate(path, entry, rule):
    high, stop = entry, entry * 0.94
    for _, h, low, c in path:
        if low <= stop:
            return (stop / entry - 1) * 100 - COST
        if rule == "target3" and h >= entry * 1.03:
            return 3.0 - COST
        high = max(high, h)
        if high >= entry * 1.02:
            if rule == "trail":
                stop = max(stop, high * 0.985, entry * (1 + COST / 100))
            elif rule == "breakeven":
                stop = max(stop, entry * (1 + COST / 100))
    return (path[-1][3] / entry - 1) * 100 - COST if path else 0.0


def main():
    results = {r: [] for r in ("current", "trail", "breakeven", "target3")}
    for symbol in MARKETS:
        minutes = load(symbol)
        ts, closes = hourly(minutes)
        e20, e50 = ema(closes, 20), ema(closes, 50)
        index = {t: i for i, (t, *_) in enumerate(minutes)}
        busy_until = 0
        for i in range(60, len(ts) - 7):
            t = ts[i] + 3600  # the hour has closed
            if t < busy_until:
                continue
            if not (closes[i] / closes[i - 24] > 1.02 and closes[i] > e20[i] > e50[i] and closes[i] > closes[i - 1]):
                continue
            start = index.get(t)
            if start is None:
                continue
            path = [m for m in minutes[start:start + 400] if m[0] < t + HOLD]
            if len(path) < 300:
                continue
            for rule in results:
                results[rule].append((t, simulate(path, closes[i], rule)))
            busy_until = t + HOLD
    mid = st.median(t for t, _ in results["current"])
    print(f"{len(results['current'])} entries, 17 markets, 6-hour hold, {COST}% costs")
    for rule, rows in results.items():
        x = [r for _, r in rows]
        a, b = [r for t, r in rows if t < mid], [r for t, r in rows if t >= mid]
        print(f"{rule:10} avg {st.mean(x):+.2f}%  win {sum(v > 0 for v in x) / len(x):.0%}  worst {min(x):+.2f}%  "
              f"best {max(x):+.2f}%  | 1st half {st.mean(a):+.2f}%  2nd half {st.mean(b):+.2f}%")


if __name__ == "__main__":
    main()
