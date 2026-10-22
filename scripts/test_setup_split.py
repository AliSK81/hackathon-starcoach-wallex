"""The agent's setups split: dips only, trend_strong only, both. Every period and market set. Behind F50.

Run after scripts/test_all_scenarios.py (it reuses its cached rows):  uv run python scripts/test_setup_split.py
"""

import pickle
import time
from pathlib import Path
from statistics import mean

from wx.backtest import run, setups_policy, short_windows
from wx.risk import AGENT_LIMITS
from wx.study import lookup_from
from wx.trades import History, typical_spreads

DIPS = ("capitulation", "stretched_dip", "dip_toman_weak")
CHOICES = {"dips only": DIPS, "trend_strong only": ("trend_strong",), "both (current)": DIPS + ("trend_strong",)}
data, now = Path("data"), int(time.time())
for name in ("6", "12", "usdt"):
    rows = pickle.loads((data / f"rows_set_{name}.pkl").read_bytes())
    symbols = sorted({r["symbol"] for r in rows})
    histories = {s: History.load(data, s, now) for s in symbols}
    spreads, lookup = typical_spreads(symbols), lookup_from(rows)
    times = sorted({r["t"] for r in rows})
    periods = {"all": rows, "1st half": [r for r in rows if r["t"] < times[len(times) // 2]],
               "2nd half": [r for r in rows if r["t"] >= times[len(times) // 2]],
               "last 30 days": [r for r in rows if r["t"] >= times[-1] - 30 * 86400]}
    print(f"\n=== market set {name}")
    for choice, setups in CHOICES.items():
        parts = []
        for period, part in periods.items():
            r = run(part, histories, setups_policy(setups), AGENT_LIMITS, "limit", lookup, True)
            nets = [p.trade.net_pct for p in r.trades]
            parts.append(f"{period} {r.return_pct:+6.2f}% (dd {r.max_drawdown_pct:4.1f}%, {len(nets)} tr)")
        _, w12 = short_windows(rows, histories, setups, spreads, 12, 6, True, AGENT_LIMITS, lookup)
        _, w72 = short_windows(rows, histories, setups, spreads, 72, 24, True, AGENT_LIMITS, lookup)
        print(f"{choice:<18} " + " | ".join(parts) + f" | 12h avg {mean(w12):+.3f}% worst {min(w12):+.2f}%"
              f" | 3d avg {mean(w72):+.3f}% worst {min(w72):+.2f}%")
