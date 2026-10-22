"""Short-term (intraday) strategies on 1-minute candles. Behind DECISIONS F62: the evidence for sprint mode.

Signals on closed 5-minute bars, checked every 5 minutes. Entry: a maker limit at the signal close, filled if the
price trades there within 10 minutes (or taker at the next minute's open). Exit, minute by minute: the stop
(taker, half the spread), the target (maker), or the time limit (taker). One position per market at a time.
Costs: maker 0.25%, taker 0.30%, and the spread. Last 60 days.

Run:  uv run --no-project --with pandas --with numpy python scripts/study_scalps.py
"""
import numpy as np
import pandas as pd

D = "data/candles/"
SETS = {"our 6": ["BTCTMN", "ETHTMN", "SOLTMN", "XRPTMN", "PEPETMN", "USDTTMN"],
        "other 12": ["PUMPTMN", "ARBTMN", "BNBTMN", "DOGETMN", "TRXTMN", "STMN", "APETMN", "SUITMN", "LTCTMN",
                     "UNITMN", "ADATMN", "SANDTMN"]}
SPREAD = {"BTCTMN": .075, "ETHTMN": .12, "SOLTMN": .27, "XRPTMN": .22, "PEPETMN": .10, "USDTTMN": .014}
MAKER, TAKER, FILL_MIN, DAYS = 0.25, 0.30, 10, 60


def load(s):
    df = pd.read_csv(D + f"{s}_1m.csv")
    df = df[df.t >= df.t.max() - DAYS * 86400].drop_duplicates("t").set_index("t").sort_index()
    full = np.arange(df.index.min(), df.index.max() + 60, 60)
    df = df.reindex(full)
    df["c"] = df.c.ffill()
    for k in ("o", "h", "l"):
        df[k] = df[k].fillna(df.c)
    df["v"] = df.v.fillna(0)
    return df


def signals(df):
    b = df.c.groupby(df.index // 300 * 300).last().to_frame("c")  # 5-minute closes
    b["v"] = df.v.groupby(df.index // 300 * 300).sum()
    b["h"] = df.h.groupby(df.index // 300 * 300).max()
    c = b.c
    e9, e21 = c.ewm(span=9, adjust=False).mean(), c.ewm(span=21, adjust=False).mean()
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn)
    z = (c - c.rolling(20).mean()) / c.rolling(20).std()
    volr = b.v / b.v.rolling(48).mean()
    ret15 = c.pct_change(3) * 100
    hi60 = b.h.rolling(12).max().shift(1)
    vwap = (c * b.v).rolling(48).sum() / b.v.rolling(48).sum()
    out = {
        "momentum (5m EMA9>21 cross, 15m +0.3%, volume x1.5)": (e9 > e21) & (e9.shift(1) <= e21.shift(1)) & (ret15 > 0.3) & (volr > 1.5),
        "breakout (above the 1h high, volume x2)": (c > hi60) & (volr > 2),
        "dip scalp (5m RSI<25, 2 sd under)": (rsi < 25) & (z < -2),
        "vwap reversion (1.5% under the 4h VWAP)": c < vwap * 0.985,
    }
    return {k: v.fillna(False) for k, v in out.items()}


def simulate(df, sig, target, stop, hold_min, spread, taker_entry=False):
    o, h, l, c = df.o.values, df.h.values, df.l.values, df.c.values
    idx = {t: i for i, t in enumerate(df.index.values)}
    nets, busy_until = [], -1
    for t in sig[sig].index.values:
        i = idx.get(t + 240)  # the last minute of the 5-minute bar
        if i is None or i <= busy_until or i + 1 >= len(c):
            continue
        price = c[i]
        if taker_entry:
            j, entry, fee_in = i + 1, o[i + 1] * (1 + spread / 200), TAKER
        else:
            k = next((j for j in range(i + 1, min(i + 1 + FILL_MIN, len(c))) if l[j] <= price), None)
            if k is None:
                continue
            j, entry, fee_in = k, price, MAKER
        tp, sl, end = entry * (1 + target / 100), entry * (1 - stop / 100), min(j + hold_min, len(c) - 1)
        exit_px, fee_out, k = c[end], TAKER + spread / 2, end
        for m in range(j + 1, end + 1):
            if l[m] <= sl:
                exit_px, fee_out, k = min(o[m], sl), TAKER + spread / 2, m
                break
            if h[m] >= tp:
                exit_px, fee_out, k = tp, MAKER, m
                break
        nets.append((exit_px / entry - 1) * 100 - fee_in - fee_out)
        busy_until = k
    return nets


EXITS = [(0.8, 0.6, 60), (1.2, 0.8, 120), (2.0, 1.0, 240), (3.0, 1.5, 480)]
for set_name, markets in SETS.items():
    data = {s: load(s) for s in markets}
    days = DAYS
    print(f"\n=== {set_name}, last {days} days. Per trade after costs; trades a day across the set.")
    print(f"{'strategy':<52} {'target/stop/hold':<16} {'trades/day':>10} {'avg':>7} {'win':>5} {'PF':>5}")
    for strat in signals(next(iter(data.values()))):
        for tp, sl, hold in EXITS:
            for taker in (False,):
                nets = []
                for s, df in data.items():
                    nets += simulate(df, signals(df)[strat], tp, sl, hold, SPREAD.get(s, 0.3), taker)
                if not nets:
                    continue
                a = np.array(nets)
                pf = a[a > 0].sum() / -a[a <= 0].sum() if (a <= 0).any() else float("inf")
                print(f"{strat:<52} {f'{tp}/{sl}/{hold}m':<16} {len(a) / days:>10.1f} {a.mean():>+6.2f}% "
                      f"{(a > 0).mean():>5.0%} {pf:>5.2f}")
