"""Which markets the agent looks at: every allowed Toman market that is liquid enough, picked again each cycle.

Allowed (D3) and quoted in Toman, because we hold Toman (D34). Liquid: at least MIN_VOLUME_TMN traded in
the last 24 hours, by Wallex's own market stats. Markets we hold stay in, so their exits keep working.
BTCTMN and USDTTMN always stay in: the agent reads the whole market's mood and the Toman's trend from them.
"""

from wx.markets import allowed_markets, load_inactive, tmn_volume
from wx.wallex import fetch_markets

MIN_VOLUME_TMN = 5_000_000_000
ALWAYS = ("BTCTMN", "USDTTMN")


def tradable_tmn() -> dict[str, dict]:
    """Every allowed market quoted in Toman, with Wallex's info."""
    return {s: i for s, i in allowed_markets(fetch_markets(), load_inactive()).items() if s.endswith("TMN")}


def liquid(markets: dict[str, dict], held=(), min_volume: float = MIN_VOLUME_TMN) -> dict[str, dict]:
    """The markets to look at now, most traded first."""
    keep = {s for s, i in markets.items() if float(tmn_volume(i)) >= min_volume} | set(held) | set(ALWAYS)
    return {s: markets[s] for s in sorted(keep & set(markets), key=lambda s: -float(tmn_volume(markets[s])))}
