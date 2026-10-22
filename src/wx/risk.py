"""The risk check: normal code, outside the AI (ROADMAP rule 7).

It turns a BUY into an order size in Toman, shrinks it to fit the limits,
or rejects it. The AI can never skip it. Limits come from DECISIONS D6.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Limits:
    risk_per_trade: float = 0.0075  # share of equity lost if the stop is hit
    max_position: float = 0.25  # most of equity in one coin
    max_exposure: float = 0.60  # most of equity in all coins together
    stop_atr: float = 4.0  # stop-loss, in 1h ATRs below the entry (D23)
    daily_loss: float = 0.02  # no new buys after losing this share of equity today
    max_drawdown: float = 0.06  # no new buys while equity is this far below its peak
    halt_hours: float = 24  # after this long in a drawdown halt, the peak resets and buying may start again
    max_data_age_min: float = 5.0  # no buys on stale data
    min_order_tmn: float = 50_000  # Wallex minimum order (F8)
    grade_b_scale: float = 0.5  # a grade B setup (mixed evidence, setups.py) risks half as much
    no_entry_hours: float = 3.0  # no new buys this close to the end: a 12-hour setup needs time to work
    flatten_minutes: float = 30.0  # this close to the end, sell everything into Toman
    # Rules from research file 03, each tested in `wx backtest --hours 12` before it was switched on (F48).
    cost_in_size: bool = False  # size = risk / (stop + round-trip cost), so a stop loses the risk budget with costs
    dd_soft: float = 0.0  # from this far below the peak, buys are smaller (0 = off)
    dd_soft_scale: float = 0.5
    cooldown_exit_min: float = 0.0  # no re-buy of a market this long after any exit
    cooldown_stop_min: float = 0.0  # ... or this long after a stop
    max_trades_day: int = 0  # most buys in 24 hours (0 = no cap)
    loss_streak: int = 0  # after this many losses in a row: pause and smaller buys (0 = off)
    loss_streak_pause_min: float = 45.0
    loss_streak_scale: float = 0.5
    take_profit_pct: float = 0.0  # sell at this gain over the entry, as a resting limit order (0 = off)
    min_edge: float = 0.0  # the usual 12-hour move must be this many times the round-trip cost (0 = off)


# The agent's limits (D38). Over 12-hour windows, these rules halved the average loss and cut the worst
# window on both market sets and in both halves (F48). Take-profit, the soft drawdown, cooldowns and
# losing-streak pauses did not help on both sets, so they stay off. `wx backtest` without --hours keeps Limits().
AGENT_LIMITS = Limits(cost_in_size=True, min_edge=1.5, max_trades_day=12)


@dataclass(frozen=True)
class Account:
    equity: float  # cash plus coins at today's prices, in TMN
    cash: float  # free TMN
    exposure: float  # TMN in coins, at cost
    peak: float  # highest equity so far
    day_start: float  # equity at the start of the UTC day


@dataclass(frozen=True)
class Verdict:
    tmn: float  # order size in TMN. 0 means rejected
    stop_pct: float  # stop-loss distance below the entry, %
    rule: str  # the rule that decided: "approved", or the limit that shrank or rejected the buy
    reason: str


@dataclass
class Ledger:
    """Our recent buys and exits, for cooldowns, the trade cap and losing streaks."""
    entries: list = field(default_factory=list)  # [t, symbol]
    exits: list = field(default_factory=list)  # [t, symbol, net_pct, reason]

    def streak(self) -> int:
        """Losses in a row, counting back from the newest exit."""
        n = 0
        for _, _, net, _ in sorted(self.exits, key=lambda e: e[0], reverse=True):
            if net is None or net >= 0:
                break
            n += 1
        return n


def pause(symbol: str, now: int, ledger: Ledger, limits: Limits) -> tuple[str, str] | None:
    """(rule, reason) if a new buy of this market must wait, else None."""
    for t, s, _, reason in ledger.exits:
        wait = limits.cooldown_stop_min if reason == "stop" else limits.cooldown_exit_min
        if s == symbol and wait and now - t < wait * 60:
            return "cooldown", f"rejected: {symbol} exited ({reason}) {round((now - t) / 60)} min ago, wait {wait:g}"
    if limits.max_trades_day and sum(now - t < 86400 for t, _ in ledger.entries) >= limits.max_trades_day:
        return "trade cap", f"rejected: {limits.max_trades_day} buys in the last 24 hours"
    if limits.loss_streak and ledger.streak() >= limits.loss_streak:
        last = max(t for t, *_ in ledger.exits)
        if now - last < limits.loss_streak_pause_min * 60:
            n, wait = ledger.streak(), limits.loss_streak_pause_min
            return "loss streak", f"rejected: {n} losses in a row, pause {wait:g} min"
    return None


def size_scale(account: Account, ledger: Ledger | None, limits: Limits) -> float:
    """How much the risk per trade shrinks after losses: the soft drawdown and a losing streak. 1 = no change."""
    scale = 1.0
    if limits.dd_soft and account.equity < account.peak * (1 - limits.dd_soft):
        scale *= limits.dd_soft_scale
    if ledger and limits.loss_streak and ledger.streak() >= limits.loss_streak:
        scale *= limits.loss_streak_scale
    return scale


def round_trip_pct(features: dict) -> float:
    """The cost of a buy then a sell, %: from the features, or maker in, taker out and the spread."""
    return features.get("round_trip_cost_pct") or 0.55 + (features.get("spread_pct") or 0.3)


def edge_problem(features: dict, limits: Limits) -> str | None:
    """Why the usual 12-hour move is too small for the cost (limits.min_edge), or None."""
    typical, cost = features.get("typical_24h_move_pct"), round_trip_pct(features)
    if limits.min_edge and typical and typical / math.sqrt(2) < limits.min_edge * cost:
        move = typical / math.sqrt(2)
        return f"rejected: a usual 12-hour move ({move:.2f}%) is under {limits.min_edge:g}x the cost ({cost:.2f}%)"
    return None


def check_buy(features: dict, account: Account, held_tmn: float = 0.0, limits: Limits = Limits(),
              scale: float = 1.0, hours_left: float | None = None, ledger: Ledger | None = None,
              now: int | None = None, symbol: str = "") -> Verdict:
    """Size a BUY for one market, or reject it. held_tmn is what we already hold in this market.

    scale (0 to 1) lowers the risk per trade: for a grade B setup, and for the AI's conviction.
    It can only make an order smaller. hours_left is the time to the end of trading, if known.
    With a ledger, cooldowns, the trade cap and losing streaks apply too.
    """
    stop_pct = limits.stop_atr * features["atr14_pct"]
    cost = round_trip_pct(features)
    if hours_left is not None and hours_left < limits.no_entry_hours:
        reason = f"rejected: {hours_left:.1f} hours left, a new buy needs at least {limits.no_entry_hours:g}"
        return Verdict(0, stop_pct, "near the end", reason)
    if ledger is not None and now is not None and (paused := pause(symbol, now, ledger, limits)):
        return Verdict(0, stop_pct, *paused)
    if (short := edge_problem(features, limits)):
        return Verdict(0, stop_pct, "edge", short)
    scale *= size_scale(account, ledger, limits)
    if account.equity < account.day_start * (1 - limits.daily_loss):
        return Verdict(0, stop_pct, "daily loss", f"rejected: lost more than {limits.daily_loss:.0%} today")
    if account.equity < account.peak * (1 - limits.max_drawdown):
        reason = f"rejected: equity is more than {limits.max_drawdown:.0%} below its peak"
        return Verdict(0, stop_pct, "drawdown", reason)
    if features["data_age_min"] > limits.max_data_age_min:
        return Verdict(0, stop_pct, "stale data", f"rejected: data is {features['data_age_min']} minutes old")
    caps = {
        "risk per trade": limits.risk_per_trade * max(0.0, min(scale, 1.0)) * account.equity
        / ((stop_pct + (cost if limits.cost_in_size else 0.0)) / 100),
        "max per coin": limits.max_position * account.equity - held_tmn,
        "max in coins": limits.max_exposure * account.equity - account.exposure,
        "free cash": account.cash,
    }
    name, tmn = min(caps.items(), key=lambda kv: kv[1])
    if tmn < limits.min_order_tmn:
        reason = f"rejected: the {name} limit leaves {max(tmn, 0):,.0f} TMN, below the minimum order"
        return Verdict(0, stop_pct, name, reason)
    if name == "risk per trade":
        return Verdict(round(tmn), stop_pct, "approved", "approved")
    return Verdict(round(tmn), stop_pct, name, f"shrunk to the {name} limit")


def update_peak(peak: float, equity: float, halted_since: int | None, t: int,
                limits: Limits = Limits()) -> tuple[float, int | None]:
    """The peak to measure drawdown from, and when the drawdown halt began (None if not halted).

    A halt that has lasted halt_hours ends: the peak resets to today's equity.
    Without this, one bad week would stop trading for good.
    """
    if equity >= peak * (1 - limits.max_drawdown):
        return max(peak, equity), None
    halted_since = halted_since if halted_since is not None else t
    if t - halted_since >= limits.halt_hours * 3600:
        return equity, None
    return peak, halted_since
