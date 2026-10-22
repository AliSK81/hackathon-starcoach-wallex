"""Tools the AI may call while it reviews buys.

Each tool only sees data up to the moment being decided, so a replay of a
past moment can't leak the future. Every call is logged with the decision.
"""

from typing import Callable

from wx.llm import Tool

MAX_HOURS = 72


def review_tools(table: dict[str, dict], closes: Callable[[str, int], list[float]],
                 setup_record: Callable[[], dict] | None = None) -> dict[str, Tool]:
    """Tools over this moment's features, hourly closes, and (if given) each setup's past record."""
    market = {"type": "string", "enum": list(table)}
    tools = {
        "get_market": Tool(
            "All features of one market right now, with the same names as in the prompt.",
            {"type": "object", "properties": {"symbol": market}, "required": ["symbol"]},
            lambda symbol: table[symbol],
        ),
        "get_hourly_closes": Tool(
            f"The last N hourly closes of one market (N at most {MAX_HOURS}), oldest first, "
            "as % change from the first one. Use it to see the shape of a move.",
            {"type": "object", "properties": {"symbol": market, "hours": {"type": "integer"}},
             "required": ["symbol"]},
            lambda symbol, hours=24: as_changes(closes(symbol, max(2, min(int(hours), MAX_HOURS)))),
        ),
    }
    if setup_record:
        tools["get_setup_record"] = Tool(
            "Past results of each buy setup on our markets, using only data from before now: entries, "
            "average net result % after costs and the stop, and the share that made money.",
            {"type": "object", "properties": {}},
            setup_record,
        )
    return tools


def as_changes(closes: list[float]) -> list[float]:
    """Each close as % change from the first."""
    return [round((c / closes[0] - 1) * 100, 2) for c in closes] if closes else []
