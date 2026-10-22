"""Shadow trading: fake orders on live data, with the same rules as the backtest.

A fake order keeps what was known when it was placed. Every cycle, trade()
replays it over the candles saved so far: not filled yet, filled and open,
stopped, or closed by its setup's exit rule. The backtest uses the same
trade(), so shadow and backtest can't drift apart. The book is one JSON file, so a restart
loses nothing. Every placed, filled, cancelled and closed order is logged.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from wx.backtest import START_TMN
from wx.prices import append_log
from wx.risk import Account, Verdict, update_peak
from wx.trades import FILL_WINDOW, MAKER_FEE_PCT, TAKER_FEE_PCT, History, trade


@dataclass
class Order:
    symbol: str
    setup: str
    tmn: float
    t: int  # when it was placed
    price: float  # mid price then
    spread_pct: float
    stop_pct: float
    status: str = "waiting"  # waiting -> open -> closed, or waiting -> cancelled
    entry_t: int | None = None
    entry: float | None = None
    exit_t: int | None = None
    net_pct: float | None = None


@dataclass
class Book:
    cash: float = START_TMN
    peak: float = START_TMN
    halted_since: int | None = None
    day: int | None = None
    day_start: float = START_TMN
    orders: list[Order] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Book":
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{**data, "orders": [Order(**o) for o in data["orders"]]})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")
        tmp.replace(path)

    def active(self) -> list[Order]:
        return [o for o in self.orders if o.status in ("waiting", "open")]

    def held(self) -> set[str]:
        return {o.symbol for o in self.active()}

    def update(self, histories: dict[str, History], now: int, log: Path) -> None:
        """Replay every active order over the candles saved up to now, and settle what is done."""
        for o in self.active():
            h = histories[o.symbol]

            def features_at(hour: int, h=h, o=o) -> dict | None:
                try:
                    return h.features_at(hour, o.spread_pct, None)
                except ValueError:
                    return None

            f = {"price": o.price, "spread_pct": o.spread_pct}
            done = trade(h, o.setup, o.t, f, o.stop_pct, "limit", features_at, now)
            if done is None:
                if now >= o.t + FILL_WINDOW:
                    o.status = "cancelled"
                    self.cash += o.tmn
                    append_log(log, {"t": now, "event": "cancelled", **asdict(o)})
                continue
            o.entry_t, o.entry = done.entry_t, done.entry
            if o.status == "waiting":
                o.status = "open"
                append_log(log, {"t": now, "event": "filled", **asdict(o)})
            if done.exit_t is not None:
                o.status, o.exit_t, o.net_pct = "closed", done.exit_t, round(done.net_pct, 3)
                self.cash += o.tmn * (1 + done.net_pct / 100)
                append_log(log, {"t": now, "event": "closed", "reason": done.exit_reason, **asdict(o)})

    def account(self, prices: dict[str, float], now: int) -> Account:
        """Equity at these prices. Waiting orders count at their full size."""
        value = sum(o.tmn * (prices[o.symbol] / o.entry if o.status == "open" else 1) for o in self.active())
        equity = self.cash + value
        self.peak, self.halted_since = update_peak(self.peak, equity, self.halted_since, now)
        if self.day != now // 86400:
            self.day, self.day_start = now // 86400, equity
        return Account(equity, self.cash, sum(o.tmn for o in self.active()), self.peak, self.day_start)

    def place(self, symbol: str, setup: str, features: dict, verdict: Verdict, now: int, log: Path) -> Order:
        order = Order(symbol, setup, verdict.tmn, now, features["price"], features["spread_pct"], verdict.stop_pct)
        self.orders.append(order)
        self.cash -= verdict.tmn
        append_log(log, {"t": now, "event": "placed", "rule": verdict.rule, **asdict(order)})
        return order

    def positions(self, table: dict[str, dict], now: int) -> dict[str, dict]:
        """Open positions as the AI sees them: setup, entry, value now, result so far, hours held."""
        return {
            o.symbol: {"setup": o.setup, "entry": o.entry, "value_tmn": int(o.tmn * table[o.symbol]["price"] / o.entry),
                       "pnl_pct": round((table[o.symbol]["price"] / o.entry - 1) * 100, 2),
                       "hours_held": round((now - o.entry_t) / 3600, 1)}
            for o in self.active() if o.status == "open" and o.symbol in table
        }

    def sell_now(self, symbol: str, features: dict, now: int, log: Path) -> None:
        """Close an open position at the bid, as a market sell (maker fee in, taker fee out)."""
        for o in self.active():
            if o.symbol == symbol and o.status == "open":
                bid = features["price"] * (1 - features["spread_pct"] / 200)
                o.net_pct = round((bid / o.entry - 1) * 100 - MAKER_FEE_PCT - TAKER_FEE_PCT, 3)
                o.status, o.exit_t = "closed", now
                self.cash += o.tmn * (1 + o.net_pct / 100)
                append_log(log, {"t": now, "event": "sold", **asdict(o)})


def price(p: float) -> str:
    return f"{p:,.0f}" if p >= 1000 else f"{p:g}"


def report(book: Book) -> str:
    """The shadow book in a few lines: cash, active orders, and closed trades with their results."""
    closed = [o for o in book.orders if o.status == "closed"]
    realized = sum(o.tmn * o.net_pct / 100 for o in closed)
    lines = [f"Cash {book.cash:,.0f} TMN. Peak equity {book.peak:,.0f}. Realized result {realized:+,.0f} TMN "
             f"({realized / START_TMN * 100:+.2f}% of the start)."]
    for o in book.active():
        entry = f"entry {price(o.entry)}" if o.entry else f"limit buy, mid price then {price(o.price)}"
        lines.append(f"  {o.status:<8} {o.symbol:<9} {o.setup:<10} {o.tmn:>11,.0f} TMN  {entry}, "
                     f"stop -{o.stop_pct:.2f}%")
    for o in closed:
        lines.append(f"  closed   {o.symbol:<9} {o.setup:<10} {o.tmn:>11,.0f} TMN  net {o.net_pct:+.2f}%")
    cancelled = sum(o.status == "cancelled" for o in book.orders)
    if closed:
        wins = sum(o.net_pct > 0 for o in closed)
        lines.append(f"Closed trades: {len(closed)}, {wins} made money. Cancelled (never filled): {cancelled}.")
    elif cancelled:
        lines.append(f"Cancelled (never filled): {cancelled}.")
    return "\n".join(lines)
