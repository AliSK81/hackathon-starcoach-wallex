"""How big can 12 hours be? Behind DECISIONS F52.

For every 12-hour window (started every hour) and every market: the move from start to end, and the best
possible move (buy at the window's low, sell at its later high, perfect hindsight). Net of 0.55% round trip.
Run:  uv run --no-project --with pandas python scripts/how_big_12h.py
"""
import pandas as pd

D = "data/candles/"
SIX = ["BTCTMN", "ETHTMN", "SOLTMN", "XRPTMN", "PEPETMN", "USDTTMN"]
TWELVE = ["PUMPTMN", "ARBTMN", "BNBTMN", "DOGETMN", "TRXTMN", "STMN", "APETMN", "SUITMN", "LTCTMN", "UNITMN",
          "ADATMN", "SANDTMN"]
for name, mk in (("our 6", SIX), ("other 12", TWELVE)):
    ends, bests = [], []
    for s in mk:
        df = pd.read_csv(D + f"{s}_1h.csv")
        c, lo, hi = df.c.values, df.l.values, df.h.values
        for i in range(len(c) - 12):
            ends.append((c[i + 12] / c[i] - 1) * 100 - 0.55)
            best, low = 0.0, lo[i]
            for j in range(i, i + 12):
                low = min(low, lo[j])
                best = max(best, (hi[j] / low - 1) * 100)
            bests.append(best - 0.55)
    e, b = pd.Series(ends), pd.Series(bests)
    print(f"{name}: {len(e)} market-windows. Hold 12h: avg {e.mean():+.2f}%, >= +5% in {(e >= 5).mean():.1%}, "
          f">= +10% in {(e >= 10).mean():.2%}, >= +20% in {(e >= 20).mean():.2%}, <= -5% in {(e <= -5).mean():.1%}")
    print(f"   perfect hindsight (buy the low, sell the high): median {b.median():.2f}%, >= +10% in "
          f"{(b >= 10).mean():.1%}, >= +20% in {(b >= 20).mean():.2%}")
