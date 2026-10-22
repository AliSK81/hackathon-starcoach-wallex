"""Checked vetoes: the AI may stop a buy only with a reason the data supports.

In the replay, a free veto stopped 70% of trend buys, and the ones it stopped
did better than the ones it let through (F27). So in the veto roles, code buys
every market where an allowed setup is active. The AI can stop a buy only by
naming one of these vetoes, and code checks the claim against the features.
A veto the data does not support is overruled, and the log says so.
"""

from collections.abc import Callable

# Code -> (what it means, the check on (features of the market, features of all markets)).
VETOES: dict[str, tuple[str, Callable[[dict, dict], bool]]] = {
    "illiquid": (
        "8 or more of the last 24 hours had no trades, or the spread is 1% or more",
        lambda f, table: f["zero_volume_hours_24"] >= 8 or f["spread_pct"] >= 1.0,
    ),
    "stale_data": (
        "the newest 1-minute candle started more than 5 minutes ago",
        lambda f, table: f["data_age_min"] > 5,
    ),
    "market_crash": (
        "BTCTMN fell 5% or more in the last 24 hours",
        lambda f, table: ((table.get("BTCTMN") or {}).get("ret_24h_pct") or 0) <= -5,
    ),
    "sell_pressure": (
        "sellers dominate the live market: buy_share under 0.35 and imbalance_1pct under -0.3 (from the order book "
        "and the latest trades; only known when the agent read them)",
        lambda f, table: f.get("buy_share") is not None and f["buy_share"] < 0.35
        and (f.get("imbalance_1pct") or 0) < -0.3,
    ),
}


def apply(decisions: list[dict], table: dict[str, dict], allowed: tuple[str, ...], held=()) -> list[dict]:
    """Turn every market with an allowed active setup into a BUY, unless the AI gave a supported veto.

    A SELL is left alone. So is a market we already hold (HOLD means keep it), and
    a market with no allowed active setup.
    """
    for d in decisions:
        usable = [s for s in table[d["symbol"]]["setups"] if s in allowed]
        if not usable or d["action"] in ("BUY", "SELL") or d["symbol"] in held:
            continue
        code = d.get("veto", "")
        if code in VETOES and VETOES[code][1](table[d["symbol"]], table):
            continue
        d["problems"].append(f"veto {code!r} overruled: the features do not support it" if code
                             else "HOLD without a veto: the buy goes ahead")
        d.update(action="BUY", setup=usable[0], veto="")
    return decisions
