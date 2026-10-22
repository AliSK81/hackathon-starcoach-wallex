"""Portfolio backtest: 5,000,000 TMN traded hour by hour over the saved history.

Every hour, in time order: positions that have exited are closed. Then the
policy names markets to buy, and the risk check sizes or rejects each buy.
Each buy plays out with trade(): its setup's exit, the stop, the costs. The
same risk check and trade() run in shadow trading.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import mean

from wx.features import add_context
from wx.replay import Lookup
from wx.risk import Account, Limits, check_buy, update_peak
from wx.setups import SETUPS, SHORT_SETUPS
from wx.study import lookup_from
from wx.trades import MAKER_FEE_PCT, TAKER_FEE_PCT, History, Trade, trade

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
    trade: Trade


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
        orders: str = "taker", lookup: Lookup | None = None, graded: bool = False) -> Result:
    """Trade the policy over the scanned hours (see study.scan), with "taker" or "limit" orders.

    lookup gives features for the exits. By default it covers the same rows. Give a wider
    one so that trades opened near the end of `rows` can still exit by their rule.
    """
    hours, lookup = defaultdict(dict), lookup or lookup_from(rows)
    for row in rows:
        hours[row["t"]][row["symbol"]] = row["features"]
    cash, peak, halted_since, day, day_start = float(START_TMN), float(START_TMN), None, None, float(START_TMN)
    open_, closed, curve, rejected = [], [], [], defaultdict(int)
    for t in sorted(hours):
        for p in [p for p in open_ if p.trade.exit_t <= t]:
            cash += p.tmn * (1 + p.trade.net_pct / 100)
            open_.remove(p)
            closed.append(p)
        equity = cash + sum(p.tmn * (histories[p.symbol].close_at(t) / p.trade.entry if p.trade.entry_t <= t else 1)
                            for p in open_)
        peak, halted_since = update_peak(peak, equity, halted_since, t, limits)
        if day != t // 86400:
            day, day_start = t // 86400, equity
        table = hours[t]
        for symbol, setup in policy(t, table, {p.symbol for p in open_}):
            f = table[symbol]
            scale = limits.grade_b_scale if graded and SETUPS[setup].grade == "B" else 1.0
            verdict = check_buy(f, Account(equity, cash, sum(p.tmn for p in open_), peak, day_start), limits=limits,
                                scale=scale)
            if not verdict.tmn:
                rejected[verdict.rule] += 1
                continue
            done = trade(histories[symbol], setup, t, f, verdict.stop_pct, orders, lambda h, s=symbol: lookup(s, h))
            if done is None:
                rejected["limit buy never filled"] += 1
                continue
            open_.append(Position(symbol, setup, verdict.tmn, done))
            cash -= verdict.tmn
        curve.append((t, equity))
    for p in open_:  # trade() closed these at the end of the data
        cash += p.tmn * (1 + p.trade.net_pct / 100)
        closed.append(p)
    return Result(cash, closed, curve, dict(rejected))


def report(result: Result, name: str) -> str:
    nets = [p.trade.net_pct for p in result.trades]
    days = (result.curve[-1][0] - result.curve[0][0]) / 86400 if result.curve else 0
    line = (f"{name:<26} return {result.return_pct:+6.2f}%  max drawdown {result.max_drawdown_pct:5.2f}%  "
            f"trades {len(nets):>4} ({len(nets) / max(days, 1):.1f}/day)")
    if nets:
        line += f"  win {sum(n > 0 for n in nets) / len(nets):.0%}  average trade {mean(nets):+.2f}%"
    return line


def windows(rows: list[dict], histories: dict[str, History], policy: Policy, orders: str, days: int = 3,
            lookup: Lookup | None = None) -> str:
    """A fresh 5,000,000 TMN book started every day and run for `days`: how often it ends up, and by how much.

    This is closer to the contest than one long run: a few days, starting at a moment nobody chose.
    Open positions at the end of a window count at their market value.
    """
    lookup = lookup or lookup_from(rows)
    hours = sorted({r["t"] for r in rows})
    returns = []
    for start in range(hours[0], hours[-1] - days * 86400, 86400):
        part = [r for r in rows if start <= r["t"] < start + days * 86400]
        result = run(part, histories, policy, orders=orders, lookup=lookup)
        returns.append(result.curve[-1][1] / START_TMN * 100 - 100 if result.curve else 0.0)
    if not returns:
        return "too little history for windows"
    returns.sort()
    return (f"{len(returns)} windows of {days} days: up in {sum(r > 0 for r in returns) / len(returns):.0%}, "
            f"average {mean(returns):+.2f}%, median {returns[len(returns) // 2]:+.2f}%, "
            f"worst {returns[0]:+.2f}%, best {returns[-1]:+.2f}%")


def with_context(rows: list[dict]) -> list[dict]:
    """Add the whole-market facts (the Toman's trend, BTC's day) to every row, hour by hour, as live trading does."""
    hours = defaultdict(dict)
    for row in rows:
        hours[row["t"]][row["symbol"]] = row["features"]
    for table in hours.values():
        add_context(table)
    return rows


def value_at(result: Result, histories: dict[str, History], end: int, spreads: dict[str, float]) -> float:
    """The book's Toman value at `end`, as if every open position were sold then (taker fee and half the spread)."""
    value = START_TMN
    for p in result.trades:
        if p.trade.exit_t is not None and p.trade.exit_t <= end:
            value += p.tmn * p.trade.net_pct / 100
        else:
            exit_cost = MAKER_FEE_PCT + TAKER_FEE_PCT + spreads.get(p.symbol, 0.3) / 2
            value += p.tmn * ((histories[p.symbol].close_at(end) / p.trade.entry - 1) * 100 - exit_cost) / 100
    return value


def short_windows(rows: list[dict], histories: dict[str, History], names: tuple[str, ...], spreads: dict[str, float],
                  hours: int = 12, step_hours: int = 6, graded: bool = True, limits: Limits = Limits(),
                  lookup: Lookup | None = None) -> tuple[str, list[float]]:
    """A fresh book every `step_hours`, trading for `hours`, then sold into Toman: what the contest measures.

    No new buys in the last limits.no_entry_hours of a window, as in live trading.
    """
    lookup = lookup or lookup_from(rows)
    times = sorted({r["t"] for r in rows})
    returns, trades = [], 0
    for start in range(times[0], times[-1] - hours * 3600, step_hours * 3600):
        end = start + hours * 3600
        part = [r for r in rows if start <= r["t"] < end - limits.no_entry_hours * 3600]
        result = run(part, histories, setups_policy(names), limits, "limit", lookup, graded)
        returns.append((value_at(result, histories, end, spreads) / START_TMN - 1) * 100)
        trades += len(result.trades)
    if not returns:
        return "too little history", []
    r = sorted(returns)
    line = (f"{len(r)} windows of {hours} h: up in {sum(x > 0 for x in r) / len(r):.0%}, flat (no trade) in "
            f"{sum(x == 0 for x in r) / len(r):.0%}, average {mean(r):+.2f}%, median {r[len(r) // 2]:+.2f}%, "
            f"worst {r[0]:+.2f}%, best {r[-1]:+.2f}%, {trades / len(r):.1f} trades a window")
    return line, returns


def short_scenarios(rows: list[dict], histories: dict[str, History], spreads: dict[str, float],
                    hours: int = 12) -> str:
    """The agent's setups (and the old trend rule) over short windows, all history and each half."""
    rows = with_context(rows)
    lookup = lookup_from(rows)
    middle = sorted(r["t"] for r in rows)[len(rows) // 2]
    periods = {"all": rows, "1st half": [r for r in rows if r["t"] < middle],
               "2nd half": [r for r in rows if r["t"] >= middle]}
    lines = [f"--- {hours}-hour windows, limit orders, sold into Toman at the end of each window"]
    for name, setups, graded in (("agent setups (graded)", SHORT_SETUPS, True),
                                 ("dip setups only", ("capitulation", "stretched_dip", "dip_toman_weak"), True),
                                 ("trend (old rule)", ("trend",), False)):
        for period, part in periods.items():
            line, _ = short_windows(part, histories, setups, spreads, hours, graded=graded, lookup=lookup)
            lines.append(f"{name}, {period}: {line}")
    return "\n".join(lines)


# Rules-only policies to compare.
POLICIES = {
    "all setups": ("trend", "sharp_drop", "oversold"),
    "trend": ("trend",),
    "mean reversion": ("sharp_drop", "oversold"),
}


def scenarios(rows: list[dict], histories: dict[str, History]) -> str:
    """Every policy, with taker and with limit orders, over all hours and over each half."""
    middle = sorted(r["t"] for r in rows)[len(rows) // 2]
    periods = {"all": rows, "1st half": [r for r in rows if r["t"] < middle],
               "2nd half": [r for r in rows if r["t"] >= middle]}
    lines, lookup = [], lookup_from(rows)
    for orders in ("taker", "limit"):
        lines.append(f"--- {orders} orders")
        for name, setups in POLICIES.items():
            for period, part in periods.items():
                result = run(part, histories, setups_policy(setups), orders=orders, lookup=lookup)
                lines.append(report(result, f"{name}, {period}"))
            lines.append(f"{name}, " + windows(rows, histories, setups_policy(setups), orders, lookup=lookup))
    return "\n".join(lines)
