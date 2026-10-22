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

from wx.features import MINUTE
from wx.replay import HORIZON, History
from wx.risk import Account, Limits, check_buy, update_peak

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


# Fees on TMN markets (F3), and how long a limit buy waits to fill.
MAKER_FEE_PCT = 0.25
TAKER_FEE_PCT = 0.30
FILL_WINDOW = 3600


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


def trade(history: History, t: int, f: dict, stop_pct: float, orders: str) -> tuple[int, float, int, float] | None:
    """One buy at t: (entry time, entry price, exit time, net result % after costs), or None if never filled.

    "taker": buy now at the mid price, sell at the exit, pay round_trip_cost_pct.
    "limit": a limit buy at the bid fills only if the price trades below it
    within FILL_WINDOW, paying the maker fee. A sell after 24 hours is a limit
    sell at the price then (maker fee). A stop is a market sell (taker fee and
    half the spread).
    """
    if orders == "taker":
        move, exit_t = history.exit_after(t, f["price"], stop_pct)
        return t, f["price"], exit_t, move - (f["round_trip_cost_pct"] or 0.0)
    half_spread = f["spread_pct"] / 2
    bid = f["price"] * (1 - half_spread / 100)
    filled = history.first_below(t, t + FILL_WINDOW, bid)
    if filled is None:
        return None
    move, exit_t = history.exit_after(filled, bid, stop_pct)
    stopped = exit_t < filled + HORIZON
    exit_cost = TAKER_FEE_PCT + half_spread if stopped else MAKER_FEE_PCT
    return filled, bid, exit_t, move - MAKER_FEE_PCT - exit_cost


def run(rows: list[dict], histories: dict[str, History], policy: Policy, limits: Limits = Limits(),
        orders: str = "taker") -> Result:
    """Trade the policy over the scanned hours (see study.scan), with "taker" or "limit" orders."""
    hours = defaultdict(dict)
    for row in rows:
        hours[row["t"]][row["symbol"]] = row["features"]
    cash, peak, halted_since, day, day_start = float(START_TMN), float(START_TMN), None, None, float(START_TMN)
    open_, trades, curve, rejected = [], [], [], defaultdict(int)
    for t in sorted(hours):
        for p in [p for p in open_ if p.exit_t <= t]:
            cash += p.tmn * (1 + p.net_pct / 100)
            open_.remove(p)
            trades.append(p)
        equity = cash + sum(p.tmn * histories[p.symbol].close_at(t) / p.entry for p in open_ if p.entry_t <= t)
        equity += sum(p.tmn for p in open_ if p.entry_t > t)  # bought, but the limit order fills later
        peak, halted_since = update_peak(peak, equity, halted_since, t, limits)
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
            done = trade(histories[symbol], t, f, verdict.stop_pct, orders)
            if done is None:
                rejected["limit buy never filled"] += 1
                continue
            open_.append(Position(symbol, setup, verdict.tmn, *done))
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

def scenarios(rows: list[dict], histories: dict[str, History]) -> str:
    """Every policy, with taker and with limit orders, over all hours and over each half."""
    middle = sorted(r["t"] for r in rows)[len(rows) // 2]
    periods = {"all": rows, "1st half": [r for r in rows if r["t"] < middle],
               "2nd half": [r for r in rows if r["t"] >= middle]}
    lines = []
    for orders in ("taker", "limit"):
        lines.append(f"--- {orders} orders")
        for name, setups in POLICIES.items():
            for period, part in periods.items():
                result = run(part, histories, setups_policy(setups), orders=orders)
                lines.append(report(result, f"{name}, {period}"))
    return "\n".join(lines)
