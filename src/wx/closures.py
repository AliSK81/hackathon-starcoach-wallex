"""Markets Wallex will close, for example USDTTMN for maintenance, from data/market_closes.json.

The file maps a market to the UTC time it closes, or to [close, reopen]:
{"USDTTMN": ["2026-10-22T20:00", "2026-10-23T08:00"]}. It is read again on every
use, so it can be changed while the bot runs. Code then refuses new buys in that market NO_BUY_MINUTES before
the close, and sells what we hold in it SELL_MINUTES before, like the end of trading. A coin left in a closed
market could not be sold into Toman, by the stop or at the end.
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

NO_BUY_MINUTES = 45
SELL_MINUTES = 30


def _unix(text) -> int:
    t = datetime.fromisoformat(str(text))
    return int((t if t.tzinfo else t.replace(tzinfo=UTC)).timestamp())


def market_closes(data_dir: Path, now: int | None = None) -> dict[str, int]:
    """Market -> Unix time it closes, for markets not reopened yet at `now`.

    An unreadable file counts as empty: it must never stop the bot."""
    path = data_dir / "market_closes.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    now = int(time.time()) if now is None else now
    out = {}
    for symbol, value in raw.items():
        close, reopen = (value + [None])[:2] if isinstance(value, list) else (value, None)
        try:
            if reopen is not None and now >= _unix(reopen):
                continue  # open again
            out[symbol.upper()] = _unix(close)
        except (ValueError, TypeError):
            continue
    return out


def closing(closes: dict[str, int], symbol: str, now: int, minutes: float) -> bool:
    """True if the market closes within `minutes` from now (or closed already)."""
    t = closes.get(symbol)
    return t is not None and t - now <= minutes * 60
