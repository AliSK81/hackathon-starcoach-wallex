"""Buy setups, defined in code. The AI may only BUY through one of these.

Each setup is a fixed rule on the features, with textbook thresholds from
research file 06. None were tuned. These four had a result of at least 0
in the setup study (DECISIONS F17). Trend pullback and range dip lost, so
they are left out.
"""

from collections.abc import Callable

# Name -> (what it means, the rule). The AI sees the meanings.
SETUPS: dict[str, tuple[str, Callable[[dict], bool]]] = {
    "sharp_drop": (
        "mean reversion: the price fell at least two typical days in the last 24 hours "
        "(ret_24h_pct <= -2 x typical_24h_move_pct)",
        lambda f: f["ret_24h_pct"] is not None and f["ret_24h_pct"] < 0
        and f["ret_24h_pct"] <= -2 * f["typical_24h_move_pct"],
    ),
    "oversold": (
        "mean reversion: 1h RSI 14 is below 30",
        lambda f: f["rsi14"] is not None and f["rsi14"] < 30,
    ),
    "breakout": (
        "trend: the last 1h close broke above the previous 20 hours' high, on volume above 1.5 times "
        "normal, with ADX above 20",
        lambda f: f["breakout_up"] and (f["vol_ratio_20"] or 0) > 1.5 and (f["adx14"] or 0) > 20,
    ),
    "trend_momentum": (
        "trend: regime is trend_up, the MACD histogram is above 0, and RSI is between 50 and 70",
        lambda f: f["regime"] == "trend_up" and (f["macd_hist_pct"] or 0) > 0 and 50 <= (f["rsi14"] or 0) <= 70,
    ),
}


def active(features: dict) -> list[str]:
    """Names of the setups whose rule holds for these features, in SETUPS order."""
    return [name for name, (_, rule) in SETUPS.items() if rule(features)]
