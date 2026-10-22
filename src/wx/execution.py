"""Where approved decisions go: a fake book (shadow) or real Wallex orders (live.py).

Both have the same methods, so the agent graph (brain.py) does not care which
one it drives. Every method is called with the executor's lock held, because
the guard loop (stops, end of trading) runs in its own thread.
"""

import threading
from dataclasses import asdict
from pathlib import Path

from wx.risk import Account, Ledger, Verdict
from wx.shadow import Book
from wx.trades import History


class ShadowExecutor:
    """Fake orders on live data (shadow.py). Fills, stops and exits come from trade(), like the backtest."""

    kind = "shadow"

    def __init__(self, data_dir: Path, name: str = "brain"):
        self.data_dir = data_dir
        self.path = data_dir / "shadow" / f"{name}_book.json"
        self.log = data_dir / "shadow" / f"{name}_orders.jsonl"
        self.book = Book.load(self.path)
        self.lock = threading.RLock()
        self.unreported: list[dict] = []  # closed trades the reflect step has not seen yet

    def drain_closed(self) -> list[dict]:
        out, self.unreported = self.unreported, []
        return out

    def sync(self, table: dict[str, dict], now: int) -> list[dict]:
        """Settle fills, stops and exits up to now. Returns the trades that closed."""
        before = {id(o): o.status for o in self.book.orders}
        histories = {s: History.load(self.data_dir, s, now) for s in self.book.held()}
        self.book.update(histories, now, self.log)
        self.book.save(self.path)
        closed = [closed_view(o) for o in self.book.orders if before.get(id(o)) in ("waiting", "open")
                  and o.status == "closed"]
        self.unreported += closed
        return closed

    def account(self, table: dict[str, dict], now: int) -> Account:
        return self.book.account({s: f["price"] for s, f in table.items()}, now)

    def positions(self, table: dict[str, dict], now: int) -> dict[str, dict]:
        out = self.book.positions(table, now)
        for o in self.book.active():
            if o.symbol in out:
                out[o.symbol].update(stop_pct=round(o.stop_pct, 2), target_pct=o.target_pct, max_hours=o.max_hours,
                                     trend_exit=o.trend_exit)
            elif o.status == "waiting":
                out[o.symbol] = {"setup": o.setup, "status": "buy order waiting", "tmn": round(o.tmn)}
        return out

    def held(self) -> set[str]:
        return self.book.held()

    def ledger(self) -> Ledger:
        """Buys and exits so far, for the trade cap and cooldowns."""
        return Ledger([[o.t, o.symbol] for o in self.book.orders],
                      [[o.exit_t, o.symbol, o.net_pct, ""] for o in self.book.orders if o.status == "closed"])

    def buy(self, symbol: str, setup: str, f: dict, verdict: Verdict, now: int, exits: dict | None = None) -> dict:
        order = self.book.place(symbol, setup, f, verdict, now, self.log, exits)
        self.book.save(self.path)
        return {"placed": True, "tmn": round(order.tmn)}

    def sell(self, symbol: str, f: dict, now: int, reason: str) -> list[dict]:
        before = {id(o): o.status for o in self.book.orders}
        self.book.sell_now(symbol, f, now, self.log)
        for o in self.book.active():  # a buy that has not filled yet is cancelled
            if o.symbol == symbol and o.status == "waiting":
                o.status = "cancelled"
                self.book.cash += o.tmn
        self.book.save(self.path)
        closed = [closed_view(o, reason) for o in self.book.orders if before.get(id(o)) == "open"
                  and o.status == "closed"]
        self.unreported += closed
        return closed

    def flatten(self, table: dict[str, dict], now: int) -> list[dict]:
        closed = []
        for symbol in sorted(self.book.held()):
            if symbol in table:
                closed += self.sell(symbol, table[symbol], now, "end of trading")
        return closed

    def guard(self, now: int) -> list[dict]:
        """Shadow stops are settled from the candles in sync(), so there is nothing to do between cycles."""
        return []

    def report(self) -> dict:
        return {"cash": round(self.book.cash), "orders": len(self.book.orders),
                "active": [o.symbol + ":" + o.status for o in self.book.active()]}


def closed_view(o, reason: str = "") -> dict:
    """A closed shadow order, as the reflect step and the log see it."""
    d = asdict(o)
    return {"symbol": d["symbol"], "setup": d["setup"], "net_pct": d["net_pct"], "entry": d["entry"],
            "entry_t": d["entry_t"], "exit_t": d["exit_t"], "placed_t": d["t"], "reason": reason or "rule or stop"}
