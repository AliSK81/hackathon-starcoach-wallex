"""Portfolio backtest: 5,000,000 TMN traded hour by hour over the saved history.

Every hour, in time order: positions whose exit has come are closed. Then
the policy names markets to buy, and the risk check sizes or rejects each
buy. A buy is held 24 hours, or until its stop. Results are after costs.
The same risk check runs in shadow and live trading.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean
from typing import Callable

from wx.replay import History
from wx.risk import Account, Limits, check_buy

START_TMN = 5_000_000

# A policy gets the hour, the features of every market, and the markets we hold.
# It returns (market, setup) pairs to buy, best first.
Policy = Callable[[int, dict[str, dict], set[str]], list[tuple[str, str]]]


def setups_policy(names: tuple[str, ...]) -> Policy:
    """Buy every market where one of these setups is active, in the order the setups are named."""
    def policy(t: int, table: dict[str, dict], held: set[str]) -> list[tuple[str, str]]:
        return [(s, name) for name in names for s, f in table.items() if name in f["setups"] and s not in held]
    return policy


@dataclass
class Position:
    symbol: str
    setup: str
    tmn: float
    entry_t: int
    entry: float
    exit_t: int
    net_pct: float  # result after costs, known in advance from the history


@dataclass
class Result:
    final: float
    trades: list[Position]
    curve: list[tuple[int, float]]  # (hour, equity)
    rejected: dict[str, int] = field(default_factory=dict)

    @property
    def return_pct(self) -> float:
        return (self.final / START_TMN - 1) * 100

    @property
    def max_drawdown_pct(self) -> float:
        peak, worst = START_TMN, 0.0
        for _, equity in self.curve:
            peak = max(peak, equity)
            worst = max(worst, 1 - equity / peak)
        return worst * 100


def run(rows: list[dict], histories: dict[str, History], policy: Policy, limits: Limits = Limits(),
        cost_pct: float | None = None) -> Result:
    """Trade the policy over the scanned hours (see study.scan). cost_pct replaces each market's round-trip cost."""
    hours = defaultdict(dict)
    for row in rows:
        hours[row["t"]][row["symbol"]] = row["features"]
    cash, peak, day, day_start = float(START_TMN), float(START_TMN), None, float(START_TMN)
    open_, trades, curve, rejected = [], [], [], defaultdict(int)
    for t in sorted(hours):
        for p in [p for p in open_ if p.exit_t <= t]:
            cash += p.tmn * (1 + p.net_pct / 100)
            open_.remove(p)
            trades.append(p)
        equity = cash + sum(p.tmn * histories[p.symbol].close_at(t) / p.entry for p in open_)
        peak = max(peak, equity)
        if day != t // 86400:
            day, day_start = t // 86400, equity
        table = hours[t]
        for symbol, setup in policy(t, table, {p.symbol for p in open_}):
            f = table[symbol]
            account = Account(equity, cash, sum(p.tmn for p in open_), peak, day_start)
            verdict = check_buy(f, account, limits=limits)
            if not verdict.tmn:
                rejected[verdict.rule] += 1
                continue
            move, exit_t = histories[symbol].exit_after(t, f["price"], verdict.stop_pct)
            cost = cost_pct if cost_pct is not None else f["round_trip_cost_pct"] or 0.0
            open_.append(Position(symbol, setup, verdict.tmn, t, f["price"], exit_t, move - cost))
            cash -= verdict.tmn
        curve.append((t, equity))
    for p in open_:
        cash += p.tmn * (1 + p.net_pct / 100)
        trades.append(p)
    return Result(cash, trades, curve, dict(rejected))


def report(result: Result, name: str) -> str:
    trades = result.trades
    days = (result.curve[-1][0] - result.curve[0][0]) / 86400 if result.curve else 0
    line = (f"{name:<28} return {result.return_pct:+6.2f}%  max drawdown {result.max_drawdown_pct:5.2f}%  "
            f"trades {len(trades):>4} ({len(trades) / max(days, 1):.1f}/day)")
    if trades:
        line += (f"  win {sum(p.net_pct > 0 for p in trades) / len(trades):.0%}"
                 f"  average trade {mean(p.net_pct for p in trades):+.2f}%")
    return line


# Rules-only policies to compare. The AI policy is added when its answers are saved.
POLICIES = {
    "every setup": ("sharp_drop", "oversold", "breakout", "trend_momentum"),
    "mean reversion": ("sharp_drop", "oversold"),
    "trend": ("breakout", "trend_momentum"),
    "sharp_drop": ("sharp_drop",),
    "oversold": ("oversold",),
}

# Round-trip cost with limit orders on both sides: 2 x 0.25% maker fee (F3), no spread crossed.
MAKER_COST_PCT = 0.5


def scenarios(rows: list[dict], histories: dict[str, History]) -> str:
    """Every policy, at today's taker cost and at the maker cost, over all hours and over each half."""
    middle = sorted(r["t"] for r in rows)[len(rows) // 2]
    periods = {"all": rows, "1st half": [r for r in rows if r["t"] < middle],
               "2nd half": [r for r in rows if r["t"] >= middle]}
    lines = []
    for cost_name, cost in (("taker cost", None), (f"maker cost {MAKER_COST_PCT}%", MAKER_COST_PCT)):
        lines.append(f"--- {cost_name}")
        for name, setups in POLICIES.items():
            for period, part in periods.items():
                result = run(part, histories, setups_policy(setups), cost_pct=cost)
                lines.append(report(result, f"{name}, {period}"))
    return "\n".join(lines)
