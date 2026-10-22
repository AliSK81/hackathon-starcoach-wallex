"""Buy setups, defined in code. The AI may only BUY through one of these.

Each setup has an entry rule and an exit rule on the features, with textbook
thresholds that were not tuned. Every position also has the stop-loss from
the risk check.

- trend: ride a 1h uptrend until it turns. In the saved history, trend-following
  made money in 13 of 14 market-halves, also on markets not used to pick it (F24).
- sharp_drop, oversold: buy a fall and give it a day to recover (F19, F22).
- capitulation, stretched_dip, dip_toman_weak: buy a deep dip and give it 12 hours.
  Over 12 hours, only dips like these beat the costs in both halves of the history,
  on both market sets (F41). They are rare.
- trend_strong: a confirmed trend while the Toman weakens and BTC is up. Over 12 hours
  it made money in the 1st half and lost in the 2nd (F41), so it gets half the risk.

Each setup has a grade from that evidence. The risk check sizes grade B at half the
risk of grade A (risk.py).
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Setup:
    meaning: str  # the AI sees this
    entry: Callable[[dict], bool]  # features -> buy?
    exit_meaning: str
    exit: Callable[[dict, float], bool]  # (features now, hours held) -> sell?
    grade: str = "B"  # A: beat the costs over 12 hours in both halves and on both market sets (F41). B: mixed


def after_a_day(f: dict, hours: float) -> bool:
    return hours >= 24


def after_12h(f: dict, hours: float) -> bool:
    return hours >= 12


def below(f: dict, name: str, limit: float) -> bool:
    return f.get(name) is not None and f[name] < limit


def toman_not_strong(f: dict) -> bool:
    """True unless we know the Toman is getting stronger.

    Unknown passes, so a market set without USDTTMN still works.
    """
    return f.get("usdt_trend_up") is not False


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
    "capitulation": Setup(
        "deep dip: 1h RSI 14 below 25 and the close more than 2 standard deviations under its 20-hour "
        "average (rsi14 < 25 and bb_z_20 < -2)",
        lambda f: below(f, "rsi14", 25) and below(f, "bb_z_20", -2),
        "sell after 12 hours",
        after_12h,
        "A",
    ),
    "stretched_dip": Setup(
        "deep dip: the close more than 2.5 standard deviations under its 20-hour average (bb_z_20 < -2.5)",
        lambda f: below(f, "bb_z_20", -2.5),
        "sell after 12 hours",
        after_12h,
        "A",
    ),
    "dip_toman_weak": Setup(
        "dip while the Toman weakens: bb_z_20 < -2, rsi14 < 30 and usdt_trend_up",
        lambda f: below(f, "bb_z_20", -2) and below(f, "rsi14", 30) and f.get("usdt_trend_up") is True,
        "sell after 12 hours",
        after_12h,
        "A",
    ),
    "trend_strong": Setup(
        "confirmed uptrend: EMA 20 above EMA 50, ADX above 25 with +DI above -DI, the Toman not getting "
        "stronger, and BTCTMN up over 24 hours",
        lambda f: (f["ema20_vs_ema50_pct"] or 0) > 0 and (f["adx14"] or 0) > 25
        and (f["plus_di14"] or 0) > (f["minus_di14"] or 0) and toman_not_strong(f)
        and (f.get("btc_ret_24h_pct") is None or f["btc_ret_24h_pct"] > 0),
        "sell when the 1h EMA 20 falls below the EMA 50",
        lambda f, hours: (f["ema20_vs_ema50_pct"] or 0) < 0,
        "B",
    ),
}

# The setups the agent may buy through (brain.py). Over 12 hours, plain trend lost more often than not (F41).
SHORT_SETUPS = ("capitulation", "stretched_dip", "dip_toman_weak", "trend_strong")


def active(features: dict) -> list[str]:
    """Names of the setups whose entry rule holds for these features, in SETUPS order."""
    return [name for name, setup in SETUPS.items() if setup.entry(features)]
