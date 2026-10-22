"""Buy setups, defined in code. The AI may only BUY through one of these.

Each setup has an entry rule and an exit rule on the features, with textbook
thresholds that were not tuned. Every position also has the stop-loss from
the risk check.

- trend: ride a 1h uptrend until it turns. In the saved history, trend-following
  made money in 13 of 14 market-halves, also on markets not used to pick it (F24).
- sharp_drop, oversold: buy a fall and give it a day to recover (F19, F22).
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Setup:
    meaning: str  # the AI sees this
    entry: Callable[[dict], bool]  # features -> buy?
    exit_meaning: str
    exit: Callable[[dict, float], bool]  # (features now, hours held) -> sell?


def after_a_day(f: dict, hours: float) -> bool:
    return hours >= 24


SETUPS: dict[str, Setup] = {
    "trend": Setup(
        "trend: the 1h EMA 20 is above the EMA 50 (ema20_vs_ema50_pct > 0)",
        lambda f: (f["ema20_vs_ema50_pct"] or 0) > 0,
        "sell when the 1h EMA 20 falls below the EMA 50",
        lambda f, hours: (f["ema20_vs_ema50_pct"] or 0) < 0,
    ),
    "sharp_drop": Setup(
        "mean reversion: the price fell at least two typical days in the last 24 hours "
        "(ret_24h_pct <= -2 x typical_24h_move_pct)",
        lambda f: f["ret_24h_pct"] is not None and f["ret_24h_pct"] < 0
        and f["ret_24h_pct"] <= -2 * f["typical_24h_move_pct"],
        "sell after 24 hours",
        after_a_day,
    ),
    "oversold": Setup(
        "mean reversion: 1h RSI 14 is below 30",
        lambda f: f["rsi14"] is not None and f["rsi14"] < 30,
        "sell after 24 hours",
        after_a_day,
    ),
}


def active(features: dict) -> list[str]:
    """Names of the setups whose entry rule holds for these features, in SETUPS order."""
    return [name for name, setup in SETUPS.items() if setup.entry(features)]
