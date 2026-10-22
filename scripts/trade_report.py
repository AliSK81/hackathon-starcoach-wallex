"""A full trade report for every rule set: each trade, statistics per market and setup, and per window length.

Writes results/trade_report_<set>.md. Run after scripts/test_all_scenarios.py (reuses its cached rows):
    uv run python scripts/trade_report.py 6|12
"""
import json
import pickle
import sys
import time
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

from wx.backtest import START_TMN, run, setups_policy, value_at
from wx.risk import AGENT_LIMITS, Limits
from wx.setups import SHORT_SETUPS
from wx.study import lookup_from
from wx.trades import History, typical_spreads

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
WINDOWS = [("12h", 12, 6), ("24h", 24, 6), ("3d", 72, 24), ("7d", 168, 24), ("14d", 336, 48), ("30d", 720, 72),
           ("60d", 1440, 168)]

name = sys.argv[1] if len(sys.argv) > 1 else "6"
data, now = Path("data"), int(time.time())
rows = pickle.loads((data / f"rows_set_{name}.pkl").read_bytes())
symbols = sorted({r["symbol"] for r in rows})
histories = {s: History.load(data, s, now) for s in symbols}
spreads, lookup = typical_spreads(symbols), lookup_from(rows)
times = sorted({r["t"] for r in rows})
out = []


def ts(t):
    return datetime.fromtimestamp(t, UTC).strftime("%m-%d %H:%M") if t else "-"


def stats(trades) -> dict:
    """Trades as (tmn, net_pct, hours, reason)."""
    if not trades:
        return {"n": 0}
    wins = [t for t in trades if t[1] > 0]
    losses = [t for t in trades if t[1] <= 0]
    gain = sum(t[0] * t[1] / 100 for t in wins)
    loss = -sum(t[0] * t[1] / 100 for t in losses)
    return {"n": len(trades), "win": len(wins) / len(trades), "avg": mean(t[1] for t in trades),
            "avg_win": mean(t[1] for t in wins) if wins else 0.0, "avg_loss": mean(t[1] for t in losses) if losses else 0.0,
            "best": max(t[1] for t in trades), "worst": min(t[1] for t in trades),
            "pf": gain / loss if loss else float("inf"), "pnl": gain - loss, "hours": median(t[2] for t in trades),
            "reasons": Counter(t[3] for t in trades)}


def row(label, s) -> str:
    if not s["n"]:
        return f"| {label} | 0 | | | | | | | | | |"
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    payoff = abs(s["avg_win"] / s["avg_loss"]) if s["avg_loss"] else float("inf")
    return (f"| {label} | {s['n']} | {s['win']:.0%} | {s['avg']:+.2f}% | {s['avg_win']:+.2f}% | {s['avg_loss']:+.2f}% "
            f"| {payoff:.2f} | {pf} | {s['pnl']:+,.0f} | {s['hours']:.0f} h | {s['best']:+.1f} / {s['worst']:+.1f} |")


HEAD = ("| | trades | win rate | avg trade | avg win | avg loss | win/loss size | profit factor | P&L TMN | "
        "median hold | best / worst |\n|---|---|---|---|---|---|---|---|---|---|---|")


def as_tuple(p, end):
    t = p.trade
    exit_t = t.exit_t or end
    return (p.tmn, t.net_pct, (exit_t - t.entry_t) / 3600, t.exit_reason or "open at end")


out.append(f"# Trade report: market set {name}\n")
out.append(f"Markets: {', '.join(symbols)}. History: {ts(times[0])} to {ts(times[-1])} UTC "
           f"({(times[-1] - times[0]) // 86400} days). Fresh 5,000,000 TMN, limit orders, costs included "
           "(maker 0.25%, taker 0.30%, half the spread on stops). Made by `scripts/trade_report.py`.\n")
out.append("Systems: careful = the 12-hour dip and strong-trend setups, only where the usual move is 1.5x the cost; "
           "normal = the same setups everywhere; active = plus the plain 1h trend rule; aggressive = all, 1.5% risk, "
           "35% a coin, 80% in coins; old trend = the trend rule with the first limits.\n")

full = {}
for sys_name, (setups, graded, limits) in SYSTEMS.items():
    res = run(rows, histories, setups_policy(setups), limits, "limit", lookup, graded)
    full[sys_name] = res
    trades = [as_tuple(p, times[-1]) for p in res.trades]
    out.append(f"\n## {sys_name}: the whole history\n")
    out.append(f"Return {res.return_pct:+.2f}%, max drawdown {res.max_drawdown_pct:.2f}%, "
               f"{len(trades)} trades ({len(trades) / ((times[-1] - times[0]) / 86400):.1f} a day).\n")
    out.append(HEAD)
    out.append(row("all", stats(trades)))
    by_m, by_s = defaultdict(list), defaultdict(list)
    for p, t in zip(res.trades, trades):
        by_m[p.symbol].append(t)
        by_s[p.setup].append(t)
    for m in symbols:
        out.append(row(m, stats(by_m[m])))
    for s_name, ts_ in sorted(by_s.items()):
        out.append(row(f"setup {s_name}", stats(ts_)))
    reasons = stats(trades).get("reasons", {})
    out.append("\nHow trades ended: " + ", ".join(f"{k} {v}" for k, v in reasons.most_common()) + "\n")

out.append("\n## Per window length\n")
out.append("Each window starts a fresh account. Trades are those bought inside the window, with their full outcome. "
           "`per market` is the average number of trades per window in each market.\n")
for label, hours, step in WINDOWS:
    ws = [(s, s + hours * 3600) for s in range(times[0], times[-1] - hours * 3600 + 1, step * 3600)]
    out.append(f"\n### {label} windows ({len(ws)}, a new one every {step} h)\n")
    out.append("| system | windows up | avg return | trades / window | win rate | avg trade | profit factor | "
               + " | ".join(f"{m}" for m in symbols) + " |")
    out.append("|---|---|---|---|---|---|---|" + "---|" * len(symbols))
    for sys_name, (setups, graded, limits) in SYSTEMS.items():
        rets, all_trades, per_m = [], [], Counter()
        for start, end in ws:
            part = [r for r in rows if start <= r["t"] < end - limits.no_entry_hours * 3600]
            res = run(part, histories, setups_policy(setups), limits, "limit", lookup, graded)
            rets.append((value_at(res, histories, end, spreads) / START_TMN - 1) * 100)
            all_trades += [as_tuple(p, end) for p in res.trades]
            per_m.update(p.symbol for p in res.trades)
        s = stats(all_trades)
        pf = "-" if not s["n"] else ("inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}")
        out.append(f"| {sys_name} | {sum(r > 0 for r in rets) / len(rets):.0%} | {mean(rets):+.2f}% | "
                   f"{s['n'] / len(ws):.1f} | " + (f"{s['win']:.0%} | {s['avg']:+.2f}% | {pf} | " if s["n"] else "- | - | - | ")
                   + " | ".join(f"{per_m[m] / len(ws):.2f}" for m in symbols) + " |")

out.append("\n## Every trade over the whole history\n")
for sys_name, res in full.items():
    out.append(f"\n### {sys_name} ({len(res.trades)} trades)\n")
    out.append("| # | market | setup | size TMN | entry (UTC) | entry price | exit (UTC) | hours | how it ended | net | P&L TMN |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, p in enumerate(sorted(res.trades, key=lambda p: p.trade.entry_t), 1):
        t = p.trade
        hours = ((t.exit_t or times[-1]) - t.entry_t) / 3600
        out.append(f"| {i} | {p.symbol} | {p.setup} | {p.tmn:,.0f} | {ts(t.entry_t)} | {t.entry:,.6g} | {ts(t.exit_t)} | "
                   f"{hours:.0f} | {t.exit_reason or 'open'} | {t.net_pct:+.2f}% | {p.tmn * t.net_pct / 100:+,.0f} |")

Path(f"results/trade_report_{name}.md").write_text("\n".join(out) + "\n", encoding="utf-8")
summary = {k: {"return_pct": round(v.return_pct, 2), "max_dd_pct": round(v.max_drawdown_pct, 2),
               "trades": len(v.trades)} for k, v in full.items()}
print(json.dumps(summary))
