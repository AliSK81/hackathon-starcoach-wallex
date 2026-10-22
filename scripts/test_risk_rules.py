"""Which research-file-03 rules help over 12-hour windows? Behind DECISIONS F48.

Each rule is switched on alone, then the ones that help together. Run from the repo root:
    uv run python scripts/test_risk_rules.py            (our 6 markets)
    uv run python scripts/test_risk_rules.py 12         (the 12 markets not used to pick rules)
"""

import pickle
import sys
import time
from dataclasses import replace
from pathlib import Path
from statistics import mean

from wx.backtest import run, setups_policy, short_windows, with_context
from wx.candles import DEFAULT_SYMBOLS
from wx.risk import Limits
from wx.setups import SHORT_SETUPS
from wx.study import lookup_from, scan
from wx.trades import History, typical_spreads

NEW_12 = ["PUMPTMN", "ARBTMN", "BNBTMN", "DOGETMN", "TRXTMN", "STMN", "APETMN", "SUITMN", "LTCTMN", "UNITMN",
          "ADATMN", "SANDTMN"]
symbols = NEW_12 if sys.argv[1:2] == ["12"] else list(DEFAULT_SYMBOLS)
data = Path("data")
now = int(time.time())
cache = data / f"rows_{len(symbols)}.pkl"
histories = {s: History.load(data, s, now) for s in symbols}
spreads = typical_spreads(symbols)
if cache.is_file() and cache.stat().st_mtime > now - 6 * 3600:
    rows = pickle.loads(cache.read_bytes())
else:
    rows = with_context(scan(histories, spreads, {s: 0.003 for s in symbols}))
    cache.write_bytes(pickle.dumps(rows))
lookup = lookup_from(rows)
middle = sorted(r["t"] for r in rows)[len(rows) // 2]
halves = {"1st": [r for r in rows if r["t"] < middle], "2nd": [r for r in rows if r["t"] >= middle]}

base = Limits()
variants = {
    "base": base,
    "cost in size": replace(base, cost_in_size=True),
    "soft drawdown 2.5%": replace(base, dd_soft=0.025),
    "cooldown 30/120 min": replace(base, cooldown_exit_min=30, cooldown_stop_min=120),
    "trade cap 12/day": replace(base, max_trades_day=12),
    "loss streak 3": replace(base, loss_streak=3),
    "take profit 1.5%": replace(base, take_profit_pct=1.5),
    "take profit 2%": replace(base, take_profit_pct=2.0),
    "take profit 3%": replace(base, take_profit_pct=3.0),
    "min edge 1.0x": replace(base, min_edge=1.0),
    "min edge 1.5x": replace(base, min_edge=1.5),
}
if len(sys.argv) > 2:  # a combination to test, e.g. "cost_in_size=True,take_profit_pct=2"
    kw = {k: eval(v) for k, v in (p.split("=") for p in sys.argv[2].split(","))}
    variants = {"base": base, "combined": replace(base, **kw)}

print(f"{len(symbols)} markets, {len(rows)} rows. 12-hour windows every 6 h, agent setups, graded, limit orders.")
for name, limits in variants.items():
    _, r = short_windows(rows, histories, SHORT_SETUPS, spreads, 12, 6, True, limits, lookup)
    h = [mean(short_windows(part, histories, SHORT_SETUPS, spreads, 12, 6, True, limits, lookup)[1])
         for part in halves.values()]
    long = run(rows, histories, setups_policy(SHORT_SETUPS), limits, "limit", lookup, True)
    print(f"{name:<22} 12h avg {mean(r):+.3f}%  up {sum(x > 0 for x in r) / len(r):4.0%}  worst {min(r):+.2f}%  "
          f"halves {h[0]:+.3f}/{h[1]:+.3f}  | whole period {long.return_pct:+6.2f}% dd {long.max_drawdown_pct:4.1f}% "
          f"trades {len(long.trades)}")
