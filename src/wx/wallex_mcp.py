"""The official Wallex MCP server, for the agent's market reads.

Wallex runs an MCP server at https://api.wallex.ir/mcp with 52 tools (research
file 05c). The agent reads the order book and the latest trades through it.
Only the read tools in READ_TOOLS can be called. We never send our API key to
it, so it can't place an order even by mistake. Orders go through orders.py,
after the risk check.

Raw MCP answers are long (a whole order book). The agent gets a short summary
instead: depth near the price, book imbalance, and who has been buying. If the
MCP server fails, the same numbers come from the REST API, and the summary says
which source was used.
"""

import asyncio
import json
import time
from datetime import datetime

from wx.wallex import WallexError, get_json

MCP_URL = "https://api.wallex.ir/mcp"
READ_TOOLS = ("wallex_basic_get_market_depth", "wallex_basic_get_latest_trades", "wallex_basic_candle_history")
NEAR_PCT = 1.0  # depth is summed within this % of the mid price
IMPACT_TMN = (500_000, 1_250_000)  # order sizes for the slippage estimate: a small order and the 25% cap


class WallexMCP:
    """Calls the allowed read tools of the Wallex MCP server. One short session per call."""

    def __init__(self, url: str = MCP_URL, timeout: float = 20):
        self.url, self.timeout, self._tools = url, timeout, None

    async def _call(self, name: str, args: dict):
        from langchain_mcp_adapters.client import MultiServerMCPClient
        if self._tools is None:
            client = MultiServerMCPClient({"wallex": {"url": self.url, "transport": "streamable_http"}})
            self._tools = {t.name: t for t in await client.get_tools() if t.name in READ_TOOLS}
        return await self._tools[name].ainvoke(args)

    def call(self, name: str, args: dict) -> dict:
        """The JSON result of one read tool."""
        if name not in READ_TOOLS:
            raise PermissionError(f"{name} is not an allowed Wallex MCP read tool")
        raw = asyncio.run(asyncio.wait_for(self._call(name, args), self.timeout))
        return unwrap(raw)


def unwrap(raw) -> dict:
    """MCP tools return content blocks with JSON text. Give back the `result` part."""
    if isinstance(raw, tuple):  # some adapter versions return (content, artifact)
        raw = raw[0]
    if isinstance(raw, list):
        raw = next((b.get("text") for b in raw if isinstance(b, dict) and b.get("text")), "{}")
    body = json.loads(raw) if isinstance(raw, str) else raw
    return body.get("result", body) if isinstance(body, dict) else {}


def book_summary(book: dict) -> dict:
    """Spread, money resting within NEAR_PCT of the mid on each side, and the imbalance between them."""
    bids = sorted(((float(b["price"]), float(b["quantity"])) for b in book.get("bid") or []), reverse=True)
    asks = sorted((float(a["price"]), float(a["quantity"])) for a in book.get("ask") or [])
    if not bids or not asks:
        return {"error": "the order book is empty on one side"}
    mid = (bids[0][0] + asks[0][0]) / 2
    bid_tmn = sum(p * q for p, q in bids if p >= mid * (1 - NEAR_PCT / 100))
    ask_tmn = sum(p * q for p, q in asks if p <= mid * (1 + NEAR_PCT / 100))
    impact = {}
    for tmn in IMPACT_TMN:
        impact[f"buy_{tmn // 1000}k_cost_pct"] = walk(asks, tmn, mid)
        impact[f"sell_{tmn // 1000}k_cost_pct"] = walk(bids, tmn, mid)
    return {
        **impact,
        "best_bid": bids[0][0], "best_ask": asks[0][0],
        "spread_pct": round((asks[0][0] - bids[0][0]) / mid * 100, 3),
        "bid_tmn_within_1pct": round(bid_tmn), "ask_tmn_within_1pct": round(ask_tmn),
        "imbalance_1pct": round((bid_tmn - ask_tmn) / (bid_tmn + ask_tmn), 2) if bid_tmn + ask_tmn else 0.0,
    }


def walk(levels: list[tuple[float, float]], tmn: float, mid: float) -> float | None:
    """How far from the mid an order of `tmn` Toman fills on average, walking these levels, %. None if too thin."""
    left, qty = tmn, 0.0
    for price, size in levels:
        take = min(size, left / price)
        qty, left = qty + take, left - take * price
        if left <= 1e-9:
            return round(abs(tmn / qty / mid - 1) * 100, 3)
    return None


def candle_bars(raw: dict, minutes: int, bars: int) -> list[dict]:
    """1-minute candles from Wallex ({t, o, h, l, c, v} lists) as the last `bars` bars of `minutes` each.
    Prices are % from the first bar's open."""
    rows = list(zip(raw.get("t") or [], *(raw.get(k) or [] for k in "ohlcv")))
    if not rows:
        return []
    groups: dict[int, list] = {}
    for t, o, h, l, c, v in rows:
        groups.setdefault(int(t) // (minutes * 60), []).append((float(o), float(h), float(l), float(c), float(v)))
    keys = sorted(groups)[-bars:]
    first = groups[keys[0]][0][0]

    def p(x: float) -> float:
        return round((x / first - 1) * 100, 2)
    return [{"t": time.strftime("%H:%M", time.gmtime(k * minutes * 60)), "o": p(g[0][0]), "h": p(max(x[1] for x in g)),
             "l": p(min(x[2] for x in g)), "c": p(g[-1][3]), "v": round(sum(x[4] for x in g), 6)}
            for k in keys for g in [groups[k]]]


def flow_summary(trades: list[dict], now: float | None = None) -> dict:
    """Who has been trading: the share of money in buyer-initiated trades, and how fast trades come."""
    now = now or time.time()
    rows = []
    for t in trades:
        try:
            when = datetime.fromisoformat(str(t["timestamp"]).replace("Z", "+00:00")).timestamp()
            rows.append((when, float(t["price"]), float(t["quantity"]), bool(t.get("isBuyOrder"))))
        except (KeyError, ValueError, TypeError):
            continue
    if not rows:
        return {"trades": 0, "error": "no recent trades"}
    value = sum(p * q for _, p, q, _ in rows)
    bought = sum(p * q for _, p, q, buy in rows if buy)
    span_min = max((now - min(w for w, *_ in rows)) / 60, 1e-9)
    return {
        "trades": len(rows), "minutes_covered": round(span_min, 1),
        "trades_per_min": round(len(rows) / span_min, 2), "tmn_traded": round(value),
        "buy_share": round(bought / value, 2) if value else None,
        "last_price": rows[0][1] if rows[0][0] >= rows[-1][0] else rows[-1][1],
    }


def microstructure(symbol: str, mcp: WallexMCP | None) -> dict:
    """Book and trade-flow summaries for one market. MCP first, then REST if MCP fails."""
    out = {"symbol": symbol, "source": "wallex_mcp"}
    try:
        if mcp is None:
            raise RuntimeError("no MCP client")
        book = mcp.call("wallex_basic_get_market_depth", {"symbol": symbol})
        trades = mcp.call("wallex_basic_get_latest_trades", {"symbol": symbol}).get("latestTrades") or []
    except Exception as error:  # MCP is a nice-to-have: fall back to the REST API
        out.update(source="wallex_rest", mcp_error=f"{type(error).__name__}: {error}"[:200])
        try:
            book = get_json("/v1/depth", {"symbol": symbol})
            trades = get_json("/v1/trades", {"symbol": symbol}).get("latestTrades") or []
        except WallexError as rest_error:
            return {**out, "error": str(rest_error)}
    return {**out, "book": book_summary(book), "flow": flow_summary(trades)}
