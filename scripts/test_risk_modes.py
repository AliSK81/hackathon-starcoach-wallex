"""Risk modes the agent can choose, tested on every window length and market set. Behind DECISIONS F53.

Run after scripts/test_all_scenarios.py (reuses its cached rows):  uv run python scripts/test_risk_modes.py
"""
import pickle
import time
from dataclasses import replace
from pathlib import Path
from statistics import mean

from wx.backtest import run, setups_policy, short_windows
from wx.risk import AGENT_LIMITS, Limits
from wx.setups import SHORT_SETUPS
from wx.study import lookup_from
from wx.trades import History, typical_spreads

WIDE = SHORT_SETUPS + ("trend",)
MODES = {
    "defensive (current)": (SHORT_SETUPS, True, AGENT_LIMITS),
    "normal": (SHORT_SETUPS, True, replace(Limits(), cost_in_size=True, max_trades_day=24)),
    "active": (WIDE, True, replace(Limits(), cost_in_size=True, max_trades_day=24)),
    "aggressive": (WIDE, False, replace(Limits(), cost_in_size=True, max_trades_day=48, risk_per_trade=0.015,
                                        max_position=0.35, max_exposure=0.80)),
    "max (35%/coin, 90%)": (WIDE, False, replace(Limits(), cost_in_size=True, max_trades_day=48, risk_per_trade=0.03,
                                                 max_position=0.35, max_exposure=0.90, daily_loss=0.05,
                                                 max_drawdown=0.10)),
}
data, now = Path("data"), int(time.time())
for name in ("6", "12", "usdt"):
    rows = pickle.loads((data / f"rows_set_{name}.pkl").read_bytes())
    symbols = sorted({r["symbol"] for r in rows})
    histories = {s: History.load(data, s, now) for s in symbols}
    spreads, lookup = typical_spreads(symbols), lookup_from(rows)
    print(f"\n=== market set {name}")
    for mode, (setups, graded, limits) in MODES.items():
        r = run(rows, histories, setups_policy(setups), limits, "limit", lookup, graded)
        out = [f"89d {r.return_pct:+6.1f}% dd {r.max_drawdown_pct:4.1f}%"]
        for hours, step in ((12, 6), (24, 6), (72, 24)):
            _, w = short_windows(rows, histories, setups, spreads, hours, step, graded, limits, lookup)
            out.append(f"{hours}h avg {mean(w):+.2f} up {sum(x > 0 for x in w) / len(w):.0%} "
                       f">=5% {sum(x >= 5 for x in w) / len(w):.0%} worst {min(w):+.1f} best {max(w):+.1f}")
        print(f"{mode:<20} " + " | ".join(out))
