"""Markets Wallex will close, for example USDTTMN for maintenance, from data/market_closes.json.

The file maps a market to the UTC time it closes: {"USDTTMN": "2026-10-22T20:15"}. It is read again on every
use, so it can be changed while the bot runs. Code then refuses new buys in that market NO_BUY_MINUTES before
the close, and sells what we hold in it SELL_MINUTES before, like the end of trading. A coin left in a closed
market could not be sold into Toman, by the stop or at the end.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

NO_BUY_MINUTES = 45
SELL_MINUTES = 30


def market_closes(data_dir: Path) -> dict[str, int]:
    """Market -> Unix time it closes. An unreadable file counts as empty: it must never stop the bot."""
    path = data_dir / "market_closes.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for symbol, text in raw.items():
        try:
            t = datetime.fromisoformat(str(text))
        except ValueError:
            continue
        out[symbol.upper()] = int((t if t.tzinfo else t.replace(tzinfo=UTC)).timestamp())
    return out


def closing(closes: dict[str, int], symbol: str, now: int, minutes: float) -> bool:
    """True if the market closes within `minutes` from now (or closed already)."""
    t = closes.get(symbol)
    return t is not None and t - now <= minutes * 60
