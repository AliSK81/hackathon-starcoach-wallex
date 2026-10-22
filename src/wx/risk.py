"""The risk check: normal code, outside the AI (ROADMAP rule 7).

It turns a BUY into an order size in Toman, shrinks it to fit the limits,
or rejects it. The AI can never skip it. Limits come from DECISIONS D6.
"""

from dataclasses import dataclass


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


def check_buy(features: dict, account: Account, held_tmn: float = 0.0, limits: Limits = Limits(),
              scale: float = 1.0, hours_left: float | None = None) -> Verdict:
    """Size a BUY for one market, or reject it. held_tmn is what we already hold in this market.

    scale (0 to 1) lowers the risk per trade: for a grade B setup, and for the AI's conviction.
    It can only make an order smaller. hours_left is the time to the end of trading, if known.
    """
    stop_pct = limits.stop_atr * features["atr14_pct"]
    if hours_left is not None and hours_left < limits.no_entry_hours:
        reason = f"rejected: {hours_left:.1f} hours left, a new buy needs at least {limits.no_entry_hours:g}"
        return Verdict(0, stop_pct, "near the end", reason)
    if account.equity < account.day_start * (1 - limits.daily_loss):
        return Verdict(0, stop_pct, "daily loss", f"rejected: lost more than {limits.daily_loss:.0%} today")
    if account.equity < account.peak * (1 - limits.max_drawdown):
        reason = f"rejected: equity is more than {limits.max_drawdown:.0%} below its peak"
        return Verdict(0, stop_pct, "drawdown", reason)
    if features["data_age_min"] > limits.max_data_age_min:
        return Verdict(0, stop_pct, "stale data", f"rejected: data is {features['data_age_min']} minutes old")
    caps = {
        "risk per trade": limits.risk_per_trade * max(0.0, min(scale, 1.0)) * account.equity / (stop_pct / 100),
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
