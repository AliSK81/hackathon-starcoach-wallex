"""A market's saved history, and how one trade plays out over it.

trade() is the one place that decides fills, stops, exits and costs. The
backtest, the AI replay, the setup study and shadow trading all use it, so
they can't disagree.
"""

import bisect
import math
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from wx.candles import candle_path, load_candles
from wx.features import HOUR, HOURS_USED, MINUTE, build_features, closed_bars
from wx.setups import SETUPS

# Fees on TMN markets (F3), and how long a limit buy waits to fill.
MAKER_FEE_PCT = 0.25
TAKER_FEE_PCT = 0.30
FILL_WINDOW = HOUR

# The past order book is not saved, so tests on the past use a fixed spread per market, in %.
# Medians of the live spreads logged by `wx watch` over a full night and day (F40). Fixed values make
# every re-run give the same result.
TYPICAL_SPREAD_PCT = {"BTCTMN": 0.075, "ETHTMN": 0.12, "SOLTMN": 0.27, "XRPTMN": 0.22, "PEPETMN": 0.10,
                      "USDTTMN": 0.014}
OTHER_SPREAD_PCT = 0.3  # markets we have not measured


def typical_spreads(symbols) -> dict[str, float]:
    return {s: TYPICAL_SPREAD_PCT.get(s, OTHER_SPREAD_PCT) for s in symbols}


class History:
    """All saved candles for one market, as floats, oldest first."""

    def __init__(self, hours: list[list[float]], minutes: list[list[float]]):
        self.hours, self.minutes = hours, minutes
        self.hour_starts = [h[0] for h in hours]
        self.minute_starts = [m[0] for m in minutes]

    @classmethod
    def load(cls, data_dir: Path, symbol: str, now: int) -> "History":
        return cls(closed_bars(load_candles(candle_path(data_dir, symbol, "1h")), HOUR, now),
                   closed_bars(load_candles(candle_path(data_dir, symbol, "1m")), MINUTE, now))

    @property
    def end(self) -> int:
        """When the newest 1-minute candle ended."""
        return int(self.minutes[-1][0]) + MINUTE if self.minutes else 0

    def close_at(self, t: int) -> float | None:
        """Close of the last 1-minute candle that ended by t."""
        i = bisect.bisect_right(self.minute_starts, t - MINUTE)
        return self.minutes[i - 1][4] if i else None

    def hourly_closes(self, t: int, hours: int) -> list[float]:
        """Closes of the last `hours` 1-hour candles that ended by t, oldest first."""
        i = bisect.bisect_right(self.hour_starts, t - HOUR)
        return [h[4] for h in self.hours[max(0, i - hours) : i]]

    def candles(self, start: int, end: int) -> list[list[float]]:
        """1-minute candles that started in [start, end)."""
        return self.minutes[bisect.bisect_left(self.minute_starts, start) : bisect.bisect_left(self.minute_starts, end)]

    def first_below(self, start: int, end: int, price: float) -> int | None:
        """End of the first 1-minute candle in [start, end) that traded below price, or None."""
        return next((int(c[0]) + MINUTE for c in self.candles(start, end) if c[3] < price), None)

    def first_touch(self, start: int, end: int, stop: float) -> tuple[int, float] | None:
        """When and at what price a stop at `stop` is hit in [start, end), or None.

        If a candle opens below the stop, the exit is that open.
        """
        for c in self.candles(start, end):
            if c[1] <= stop:
                return int(c[0]), c[1]
            if c[3] <= stop:
                return int(c[0]) + MINUTE, stop
        return None

    def first_reach(self, start: int, end: int, price: float) -> int | None:
        """End of the first 1-minute candle in [start, end) that traded at or above price, or None."""
        return next((int(c[0]) + MINUTE for c in self.candles(start, end) if c[2] >= price), None)

    def features_at(self, t: int, spread_pct: float, taker_fee: float | None) -> dict:
        """The features as they were at t. Only candles that ended by t are used."""
        h = bisect.bisect_right(self.hour_starts, t - HOUR)
        m = bisect.bisect_right(self.minute_starts, t - MINUTE)
        hours, minutes = self.hours[max(0, h - HOURS_USED) : h], self.minutes[max(0, m - 5000) : m]
        if not minutes:
            raise ValueError("no 1-minute candles before this moment")
        last = Decimal(str(minutes[-1][4]))
        half = last * Decimal(str(spread_pct)) / 200
        return build_features(hours, minutes, last - half, last + half, t, taker_fee)


def exit_rule(max_hours: float = 0.0, trend_exit: bool = False) -> Callable[[dict, float], bool]:
    """The agent's own exit plan as a rule on (features at an hour, hours held): a time limit, the trend turning."""
    def rule(g: dict, hours: float) -> bool:
        return bool((max_hours and hours >= max_hours) or (trend_exit and (g.get("ema20_vs_ema50_pct") or 0) < 0))
    return rule


@dataclass
class Trade:
    entry_t: int
    entry: float
    exit_t: int | None = None  # None while the trade is still open
    net_pct: float | None = None  # result after costs, once closed
    exit_reason: str = ""  # "stop", "rule" (the setup's exit), or "end of data"


def trade(history: History, setup: str, t: int, f: dict, stop_pct: float, orders: str,
          features_at: Callable[[int], dict | None], now: int | None = None, take_profit_pct: float = 0.0,
          rule: Callable[[dict, float], bool] | None = None) -> Trade | None:
    """How a buy at t through `setup` plays out, up to `now` (or to the end of the data).

    Entry. "taker": at the mid price now. "limit": at the bid, only if the price
    trades below it within FILL_WINDOW. None if it never fills (or not yet).
    Exit, checked in time order: the stop on every 1-minute low, and the setup's
    exit rule on the features at every hour. features_at(hour) gives them.
    Costs. "taker": round_trip_cost_pct. "limit": the maker fee in, the maker fee
    out on a rule exit, the taker fee plus half the spread out on a stop.
    With `now`, a trade that has not exited yet comes back open (exit_t None).
    take_profit_pct: a resting limit sell that far above the entry (maker fee). If the stop and
    the target fall in the same minute, the stop counts.
    """
    end = history.end if now is None else now
    if orders == "taker":
        entry_t, entry = t, f["price"]

        def cost(stopped: bool) -> float:
            return f["round_trip_cost_pct"] or 0.0
    else:
        half_spread = f["spread_pct"] / 2
        entry = f["price"] * (1 - half_spread / 100)
        entry_t = history.first_below(t, min(t + FILL_WINDOW, end), entry)
        if entry_t is None:
            return None

        def cost(stopped: bool) -> float:
            return MAKER_FEE_PCT + (TAKER_FEE_PCT + half_spread if stopped else MAKER_FEE_PCT)

    def closed(exit_t: int, price: float, reason: str) -> Trade:
        return Trade(entry_t, entry, exit_t, (price / entry - 1) * 100 - cost(reason == "stop"), reason)

    stop = entry * (1 - stop_pct / 100)
    rule = rule or (SETUPS[setup].exit if setup in SETUPS else exit_rule())
    target = entry * (1 + take_profit_pct / 100) if take_profit_pct else None
    start, hour = entry_t, math.ceil(entry_t / HOUR) * HOUR
    while True:
        hit = history.first_touch(start, min(hour, end), stop)
        reached = history.first_reach(start, min(hour, end), target) if target else None
        if reached and (not hit or reached < hit[0]):
            return closed(reached, target, "take profit")
        if hit:
            return closed(*hit, "stop")
        if hour > end:
            break
        g = features_at(hour)
        if g is not None and rule(g, (hour - entry_t) / HOUR):
            return closed(hour, g["price"], "rule")
        start, hour = hour, hour + HOUR
    if now is not None:
        return Trade(entry_t, entry)
    return closed(end, history.close_at(end), "end of data")
