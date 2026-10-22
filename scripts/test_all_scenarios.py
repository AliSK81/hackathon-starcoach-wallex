"""Every rule-level test from this project, on the current agent rules. Behind DECISIONS F49.

Systems: the agent's setups with the agent's limits (what trades now), the same setups with the old
limits, and the old trend rule. Baseline: holding every market (equal parts).
Tests: the whole history with limit and taker orders, each half, and fresh books started on a fixed
step and sold into Toman at the end: 3-day, 1-day and 12-hour windows.
Market sets: our 6 TMN markets, 12 TMN markets not used to pick rules, and 6 USDT markets (no Toman
drift; TMN fees are used, which is harsher than the real 0.10% / 0.13%).

Run from the repo root:  uv run python scripts/test_all_scenarios.py 6|12|usdt
"""

import pickle
import sys
import time
from pathlib import Path
from statistics import mean

from wx.backtest import run, setups_policy, short_windows, with_context
from wx.candles import DEFAULT_SYMBOLS
from wx.risk import AGENT_LIMITS, Limits
from wx.setups import SHORT_SETUPS
from wx.study import lookup_from, scan
from wx.trades import MAKER_FEE_PCT, History, typical_spreads

SETS = {
    "6": list(DEFAULT_SYMBOLS),
    "12": ["PUMPTMN", "ARBTMN", "BNBTMN", "DOGETMN", "TRXTMN", "STMN", "APETMN", "SUITMN", "LTCTMN", "UNITMN",
           "ADATMN", "SANDTMN"],
    "usdt": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "PEPEUSDT", "DOGEUSDT"],
}
SYSTEMS = {
    "agent (setups + agent limits)": (SHORT_SETUPS, True, AGENT_LIMITS),
    "agent setups, old limits": (SHORT_SETUPS, True, Limits()),
    "old trend rule": (("trend",), False, Limits()),
}
WINDOWS = ((72, 24), (24, 6), (12, 6))  # (hours, step hours)

name = sys.argv[1] if len(sys.argv) > 1 else "6"
symbols = SETS[name]
data, now = Path("data"), int(time.time())
histories = {s: History.load(data, s, now) for s in symbols}
spreads = typical_spreads(symbols)
cache = data / f"rows_set_{name}.pkl"
if cache.is_file() and cache.stat().st_mtime > now - 6 * 3600:
    rows = pickle.loads(cache.read_bytes())
else:
    rows = with_context(scan(histories, spreads, {s: 0.003 for s in symbols}))
    cache.write_bytes(pickle.dumps(rows))
lookup = lookup_from(rows)
times = sorted({r["t"] for r in rows})
middle = times[len(times) // 2]
halves = {"1st half": [r for r in rows if r["t"] < middle], "2nd half": [r for r in rows if r["t"] >= middle]}
days = (times[-1] - times[0]) / 86400


def hold_windows(hours: int, step: int) -> list[float]:
    """Buy every market in equal parts at the start (maker), sell at the end (taker and half the spread)."""
    out = []
    for start in range(times[0], times[-1] - hours * 3600, step * 3600):
        end = start + hours * 3600
        moves = []
        for s, h in histories.items():
            a, b = h.close_at(start), h.close_at(end)
            if a and b:
                moves.append((b / a - 1) * 100 - MAKER_FEE_PCT - 0.30 - spreads[s] / 2)
        out.append(mean(moves) if moves else 0.0)
    return out


def describe(r: list[float]) -> str:
    up, flat = sum(x > 0 for x in r) / len(r), sum(x == 0 for x in r) / len(r)
    return (f"avg {mean(r):+6.2f}%  up {up:4.0%}  flat {flat:4.0%}"
            f"  worst {min(r):+6.2f}%  best {max(r):+6.2f}%  (n={len(r)})")


print(f"Market set {name}: {' '.join(symbols)}. {days:.0f} days of hours, {len(rows)} rows.")
for system, (setups, graded, limits) in SYSTEMS.items():
    print(f"\n=== {system}")
    for orders in ("limit", "taker"):
        r = run(rows, histories, setups_policy(setups), limits, orders, lookup, graded)
        nets = [p.trade.net_pct for p in r.trades]
        win = sum(n > 0 for n in nets) / len(nets) if nets else 0
        print(f"whole history, {orders:<5}: return {r.return_pct:+7.2f}%  max drawdown {r.max_drawdown_pct:5.2f}%  "
              f"trades {len(nets)} ({len(nets) / days:.1f}/day)  win {win:.0%}"
              + (f"  avg trade {mean(nets):+.2f}%" if nets else ""))
    for half, part in halves.items():
        r = run(part, histories, setups_policy(setups), limits, "limit", lookup, graded)
        print(f"{half}, limit    : return {r.return_pct:+7.2f}%  max drawdown {r.max_drawdown_pct:5.2f}%  "
              f"trades {len(r.trades)}")
    for hours, step in WINDOWS:
        _, w = short_windows(rows, histories, setups, spreads, hours, step, graded, limits, lookup)
        print(f"{hours:>2} h windows   : {describe(w)}")
print("\n=== baseline: hold every market in equal parts")
for hours, step in WINDOWS:
    print(f"{hours:>2} h windows   : {describe(hold_windows(hours, step))}")
