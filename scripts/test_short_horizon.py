"""Short-horizon strategies from the research, on Wallex TMN markets, by holding time (F81).

Every hour, each strategy picks coins; each pick is bought at that hour's close and sold H hours later
(H = 1, 3, 6). Result per trade after a 0.75% round trip (taker both ways plus half the spreads), and
after 0.55% (maker in). One position per coin per strategy at a time is not enforced: this measures the
signal, not a portfolio. 17 coins (USDT left out), about 120 days of hourly closes.

Strategies:
  reversal_24h  : the 3 coins with the lowest 24-hour return (short-term reversal; Zaremba 2021)
  reversal_vol  : the same among the 8 coins that move most (typical 24-hour move, past 7 days)
  momentum_24h  : the 3 coins with the highest 24-hour return (the opposite, as a check)
  reversal_1h   : the 3 coins with the lowest 1-hour return
  big_momentum  : BTC and ETH when both rose in the last hour (large coins keep momentum)
  shock_up      : any coin up more than 3% in the last hour (abnormal-move continuation)
  dip_rsi       : any coin with 14-hour RSI under 30 and 24-hour return under -5%
  all_coins     : every coin every hour (the market itself)

    uv run python scripts/test_short_horizon.py
"""
import csv
import statistics as st
from pathlib import Path

COINS = ["ADATMN", "APETMN", "ARBTMN", "BNBTMN", "BTCTMN", "DOGETMN", "ETHTMN", "LTCTMN", "PEPETMN", "PUMPTMN",
         "SANDTMN", "SOLTMN", "STMN", "SUITMN", "TRXTMN", "UNITMN", "XRPTMN"]


def load(symbol):
    rows = csv.DictReader(open(Path("data/candles") / f"{symbol}_1h.csv"))
    return {int(float(r["t"])): float(r["c"]) for r in rows}


def rsi(closes, n=14):
    gains = [max(b - a, 0) for a, b in zip(closes, closes[1:])][-n:]
    losses = [max(a - b, 0) for a, b in zip(closes, closes[1:])][-n:]
    g, lo = sum(gains) / n, sum(losses) / n
    return 100 if lo == 0 else 100 - 100 / (1 + g / lo)


def main():
    data = {s: load(s) for s in COINS}
    times = sorted(set.intersection(*[set(d) for d in data.values()]))
    hold = (1, 3, 6)
    trades = {}  # (strategy, H) -> [(t, gross %)]

    def add(name, s, i):
        for h in hold:
            if i + h < len(times):
                a, b = data[s][times[i]], data[s][times[i + h]]
                trades.setdefault((name, h), []).append((times[i], (b / a - 1) * 100))

    for i in range(24 * 7, len(times) - 6):
        t = times[i]
        r24 = {s: data[s][t] / data[s][times[i - 24]] - 1 for s in COINS}
        r1 = {s: data[s][t] / data[s][times[i - 1]] - 1 for s in COINS}
        move = {s: st.mean(abs(data[s][times[j]] / data[s][times[j - 24]] - 1) for j in range(i - 24 * 7, i, 24))
                for s in COINS}
        for s in sorted(COINS, key=lambda s: r24[s])[:3]:
            add("reversal_24h", s, i)
        lively = sorted(COINS, key=lambda s: -move[s])[:8]
        for s in sorted(lively, key=lambda s: r24[s])[:3]:
            add("reversal_vol", s, i)
        for s in sorted(COINS, key=lambda s: -r24[s])[:3]:
            add("momentum_24h", s, i)
        for s in sorted(COINS, key=lambda s: r1[s])[:3]:
            add("reversal_1h", s, i)
        if r1["BTCTMN"] > 0 and r1["ETHTMN"] > 0:
            add("big_momentum", "BTCTMN", i)
            add("big_momentum", "ETHTMN", i)
        for s in COINS:
            if r1[s] > 0.03:
                add("shock_up", s, i)
            closes = [data[s][times[j]] for j in range(i - 15, i + 1)]
            if rsi(closes) < 30 and r24[s] < -0.05:
                add("dip_rsi", s, i)
            add("all_coins", s, i)
    mid = times[len(times) // 2]
    print(f"{len(times)} hours, 17 coins. Average per trade after costs (taker 0.75% / maker-in 0.55%), "
          "1st and 2nd half (taker), share of trades up")
    for (name, h), rows in sorted(trades.items(), key=lambda kv: (kv[0][1], -st.mean(r for _, r in kv[1]))):
        g = [r for _, r in rows]
        a = [r - 0.75 for t, r in rows if t < mid]
        b = [r - 0.75 for t, r in rows if t >= mid]
        print(f"H={h}h {name:13} n={len(g):6}  taker {st.mean(g) - 0.75:+.2f}%  maker {st.mean(g) - 0.55:+.2f}%  "
              f"| 1st {st.mean(a):+.2f}% 2nd {st.mean(b):+.2f}%  up {sum(r > 0.75 for r in g) / len(g):.0%}")


if __name__ == "__main__":
    main()
