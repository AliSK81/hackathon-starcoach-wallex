"""Every rule set on windows of 12 hours to the whole history, started on a fixed step. Behind DECISIONS F60.

For each window: a fresh 5,000,000 TMN book, limit orders, sold into Toman at the end. Per window: return, max
drawdown, trades. Reported per window length: average and median return, share up, worst and best, average
drawdown, trades. Run after scripts/test_all_scenarios.py (reuses its cached rows):
    uv run python scripts/test_windows.py 6|12
"""
import pickle
import sys
import time
from dataclasses import replace
from pathlib import Path
from statistics import mean, median

from wx.backtest import START_TMN, run, setups_policy, value_at
from wx.risk import AGENT_LIMITS, Limits
from wx.setups import SHORT_SETUPS
from wx.study import lookup_from
from wx.trades import MAKER_FEE_PCT, TAKER_FEE_PCT, History, typical_spreads

WIDE = SHORT_SETUPS + ("trend",)
BASE = replace(Limits(), cost_in_size=True, max_trades_day=24)
SYSTEMS = {
    "careful": (SHORT_SETUPS, True, AGENT_LIMITS),
    "normal": (SHORT_SETUPS, True, BASE),
    "active": (WIDE, True, BASE),
    "aggressive": (WIDE, False, replace(BASE, max_trades_day=48, risk_per_trade=0.015, max_position=0.35,
                                        max_exposure=0.80)),
    "old trend": (("trend",), False, Limits()),
}
# (label, hours, step hours)
WINDOWS = [("12h", 12, 6), ("24h", 24, 6), ("3d", 72, 24), ("7d", 168, 24), ("14d", 336, 48), ("30d", 720, 72),
           ("60d", 1440, 168), ("all", None, None)]

name = sys.argv[1] if len(sys.argv) > 1 else "6"
data, now = Path("data"), int(time.time())
rows = pickle.loads((data / f"rows_set_{name}.pkl").read_bytes())
symbols = sorted({r["symbol"] for r in rows})
histories = {s: History.load(data, s, now) for s in symbols}
spreads, lookup = typical_spreads(symbols), lookup_from(rows)
times = sorted({r["t"] for r in rows})
span_h = (times[-1] - times[0]) // 3600


def windows(hours, step):
    if hours is None:
        return [(times[0], times[-1])]
    return [(s, s + hours * 3600) for s in range(times[0], times[-1] - hours * 3600 + 1, step * 3600)]


def max_dd(curve):
    peak, worst = START_TMN, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        worst = max(worst, 1 - eq / peak)
    return worst * 100


def hold(start, end):
    moves = [(h.close_at(end) / h.close_at(start) - 1) * 100 - MAKER_FEE_PCT - TAKER_FEE_PCT - spreads[s] / 2
             for s, h in histories.items() if h.close_at(start) and h.close_at(end)]
    return mean(moves) if moves else 0.0


print(f"Market set {name} ({len(symbols)} markets), {span_h // 24} days of history. Limit orders, sold into Toman.")
print("ret = average return per window | med = median | up = share of windows that ended up | worst/best | "
      "dd = average max drawdown | tr = trades per window")
for label, hours, step in WINDOWS:
    ws = windows(hours, step)
    print(f"\n--- {label} windows: {len(ws)}" + (f" (a new one every {step} h)" if step else ""))
    for sys_name, (setups, graded, limits) in SYSTEMS.items():
        rets, dds, trs = [], [], []
        for start, end in ws:
            part = [r for r in rows if start <= r["t"] < end - limits.no_entry_hours * 3600]
            res = run(part, histories, setups_policy(setups), limits, "limit", lookup, graded)
            rets.append((value_at(res, histories, end, spreads) / START_TMN - 1) * 100)
            dds.append(max_dd(res.curve))
            trs.append(len(res.trades))
        print(f"  {sys_name:<11} ret {mean(rets):+7.2f}%  med {median(rets):+7.2f}%  up {sum(r > 0 for r in rets) / len(rets):4.0%}"
              f"  worst {min(rets):+7.2f}%  best {max(rets):+7.2f}%  dd {mean(dds):5.2f}%  tr {mean(trs):5.1f}")
    h = [hold(s, e) for s, e in ws]
    print(f"  {'hold all':<11} ret {mean(h):+7.2f}%  med {median(h):+7.2f}%  up {sum(r > 0 for r in h) / len(h):4.0%}"
          f"  worst {min(h):+7.2f}%  best {max(h):+7.2f}%")
