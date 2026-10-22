"""Which markets the agent looks at: every allowed Toman market that is liquid enough, picked again each cycle.

Allowed (D3) and quoted in Toman, because we hold Toman (D34). Liquid: at least MIN_VOLUME_TMN traded in
the last 24 hours, by Wallex's own market stats; or at least BOOK_MIN_VOLUME_TMN traded and a live book that can
take our size: a spread of at most BOOK_MAX_SPREAD_PCT and BOOK_MIN_SIDE_TMN within 1% on both sides (D53).
Markets we hold stay in, so their exits keep working.
BTCTMN and USDTTMN always stay in: the agent reads the whole market's mood and the Toman's trend from them.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from wx.markets import allowed_markets, load_inactive, tmn_volume
from wx.wallex import fetch_markets, get_json

MIN_VOLUME_TMN = 5_000_000_000
BOOK_MIN_VOLUME_TMN = 1_000_000_000
BOOK_MAX_SPREAD_PCT = 0.6
BOOK_MIN_SIDE_TMN = 20_000_000  # our largest order is about 2 M TMN
ALWAYS = ("BTCTMN", "USDTTMN")


def tradable_tmn() -> dict[str, dict]:
    """Every allowed market quoted in Toman, with Wallex's info."""
    return {s: i for s, i in allowed_markets(fetch_markets(), load_inactive()).items() if s.endswith("TMN")}


def book_ok(symbol: str) -> bool:
    """True if the live book has a tight spread and enough Toman on both sides within 1%."""
    try:
        book = get_json("/v1/depth", {"symbol": symbol})
        asks = [(float(x["price"]), float(x["quantity"])) for x in book.get("ask", [])]
        bids = [(float(x["price"]), float(x["quantity"])) for x in book.get("bid", [])]
    except Exception:  # noqa: BLE001 - any failure: leave the market out this cycle
        return False
    if not asks or not bids:
        return False
    ask, bid = min(p for p, _ in asks), max(p for p, _ in bids)
    near_ask = sum(p * q for p, q in asks if p <= ask * 1.01)
    near_bid = sum(p * q for p, q in bids if p >= bid * 0.99)
    return (ask / bid - 1) * 100 <= BOOK_MAX_SPREAD_PCT and min(near_ask, near_bid) >= BOOK_MIN_SIDE_TMN


def liquid(markets: dict[str, dict], held=(), min_volume: float = MIN_VOLUME_TMN,
           book: Callable[[str], bool] | None = None) -> dict[str, dict]:
    """The markets to look at now, most traded first. With `book`, markets under min_volume but over
    BOOK_MIN_VOLUME_TMN get in when their live book passes it."""
    keep = {s for s, i in markets.items() if float(tmn_volume(i)) >= min_volume} | set(held) | set(ALWAYS)
    if book is not None:
        maybe = [s for s, i in markets.items() if s not in keep and float(tmn_volume(i)) >= BOOK_MIN_VOLUME_TMN]
        with ThreadPoolExecutor(8) as pool:
            keep |= {s for s, ok in zip(maybe, pool.map(book, maybe)) if ok}
    return {s: markets[s] for s in sorted(keep & set(markets), key=lambda s: -float(tmn_volume(markets[s])))}
