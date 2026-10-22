"""Real orders on Wallex, with the same methods as the shadow book (execution.py).

- Buy: a LIMIT order at the live best bid, sized by the risk check. If it has not
  filled within FILL_WINDOW it is cancelled, and any part that filled is kept.
- Stop: the guard loop reads the live best bid every minute. At or below the stop,
  the position is sold at once.
- Sell: a LIMIT order a little under the best bid (SELL_SLIP), so it fills at once
  against the bids, like a market order, but never far below the price. Not all of
  our markets allow MARKET orders (F9).
- The book is data/live/book.json. Every order carries our client_id, so after a
  restart each one is read back from Wallex. Every event goes to data/live/orders.jsonl.
- kill(): cancel every open order and sell every position. The kill switch.

Only code calls this, after the risk check. The AI never places an order.
"""

import json
import threading
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from wx.closures import SELL_MINUTES, closing, market_closes
from wx.markets import load_inactive
from wx.orders import OrderState, Trader, new_client_id
from wx.prices import append_log
from wx.risk import Account, Ledger, Limits, Verdict, update_peak
from wx.rules import MarketRules
from wx.setups import SETUPS
from wx.trades import FILL_WINDOW, exit_rule
from wx.wallex import WallexError, fetch_balances, fetch_best_prices

EXCLUDED = load_inactive()  # the organizers' list of markets we may not trade
SELL_SLIP = Decimal("0.005")  # a sell is priced this far under the best bid, so it fills at once
RESELL_AFTER = 60  # seconds before an unfilled sell is cancelled and sent again lower


@dataclass
class Position:
    symbol: str
    setup: str
    tmn: float  # planned size
    stop_pct: float
    t: int  # when the buy was placed
    buy_id: str
    status: str = "buying"  # buying -> open -> selling -> closed, or buying -> cancelled
    qty: str = "0"  # coin we hold from this position (after fees taken in the coin)
    entry: float | None = None  # average fill price
    cost_tmn: float = 0.0  # Toman paid, fees included
    entry_t: int | None = None
    sell_id: str = ""
    sell_t: int | None = None
    sell_reason: str = ""
    proceeds_tmn: float = 0.0  # Toman received from sells, after fees
    exit_t: int | None = None
    net_pct: float | None = None
    note: str = ""
    target_pct: float = 0.0  # the agent's exit plan (0 / False = not used)
    max_hours: float = 0.0
    trend_exit: bool = False
    fill_minutes: int = FILL_WINDOW // 60  # how long the buy waits before it is cancelled
    trend_up_seen: bool = False  # the trend was up at some point while held: only then can it "turn" (trend_exit)

    @property
    def stop(self) -> float | None:
        return None if self.entry is None else self.entry * (1 - self.stop_pct / 100)


class LiveExecutor:
    kind = "live"

    def __init__(self, trader: Trader, api_key: str, rules: dict[str, MarketRules], data_dir: Path,
                 limits: Limits = Limits(), end_at: int | None = None):
        self.trader, self._key, self.rules, self.limits, self.end_at = trader, api_key, rules, limits, end_at
        self.data_dir = data_dir
        self.path = data_dir / "live" / "book.json"
        self.log = data_dir / "live" / "orders.jsonl"
        self.lock = threading.RLock()
        self.positions_: list[Position] = []
        self.peak: float | None = None
        self.halted_since: int | None = None
        self.day: int | None = None
        self.day_start: float | None = None
        self.unreported: list[dict] = []  # closed trades the reflect step has not seen yet
        self.load()

    def drain_closed(self) -> list[dict]:
        out, self.unreported = self.unreported, []
        return out

    # --- the book on disk ---
    def load(self) -> None:
        if not self.path.is_file():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.positions_ = [Position(**p) for p in data.get("positions", [])]
        self.peak, self.halted_since = data.get("peak"), data.get("halted_since")
        self.day, self.day_start = data.get("day"), data.get("day_start")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"positions": [asdict(p) for p in self.positions_], "peak": self.peak,
                                   "halted_since": self.halted_since, "day": self.day, "day_start": self.day_start},
                                  indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def event(self, now: int, name: str, p: Position | None = None, **extra) -> None:
        append_log(self.log, {"t": now, "event": name, **(asdict(p) if p else {}), **extra})

    def active(self) -> list[Position]:
        return [p for p in self.positions_ if p.status in ("buying", "open", "selling")]

    def held(self) -> set[str]:
        return {p.symbol for p in self.active()}

    def ledger(self) -> Ledger:
        """Buys and exits so far, for the trade cap and cooldowns."""
        return Ledger([[p.t, p.symbol] for p in self.positions_ if p.status != "cancelled"],
                      [[p.exit_t, p.symbol, p.net_pct, p.sell_reason] for p in self.positions_ if p.status == "closed"])

    # --- reading Wallex ---
    def balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        """asset -> (total, free)."""
        out = {}
        for asset, b in fetch_balances(self._key).items():
            total, locked = Decimal(str(b.get("value") or 0)), Decimal(str(b.get("locked") or 0))
            out[asset] = (total, total - locked)
        return out

    def account(self, table: dict[str, dict], now: int) -> Account:
        bal = self.balances()
        cash_total, cash_free = bal.get("TMN", (Decimal(0), Decimal(0)))
        coins = sum(float(bal.get(self.rules[s].base, (Decimal(0), 0))[0]) * f["price"]
                    for s, f in table.items() if s in self.rules and self.rules[s].base != "TMN")
        equity = float(cash_total) + coins
        self.peak, self.halted_since = update_peak(self.peak or equity, equity, self.halted_since, now, self.limits)
        if self.day != now // 86400 or self.day_start is None:
            self.day, self.day_start = now // 86400, equity
        self.save()
        exposure = sum(p.cost_tmn or p.tmn for p in self.active())
        return Account(equity, float(cash_free), exposure, self.peak, self.day_start)

    def positions(self, table: dict[str, dict], now: int) -> dict[str, dict]:
        out = {}
        for p in self.active():
            price = (table.get(p.symbol) or {}).get("price")
            if p.status == "open" and p.entry and price:
                out[p.symbol] = {"setup": p.setup, "entry": p.entry, "value_tmn": int(float(p.qty) * price),
                                 "pnl_pct": round((price / p.entry - 1) * 100, 2),
                                 "hours_held": round((now - (p.entry_t or p.t)) / 3600, 1),
                                 "stop_pct": round(p.stop_pct, 2), "target_pct": p.target_pct,
                                 "max_hours": p.max_hours, "trend_exit": p.trend_exit}
            else:
                out[p.symbol] = {"setup": p.setup, "status": p.status, "tmn": round(p.tmn)}
        return out

    # --- orders ---
    def buy(self, symbol: str, setup: str, f: dict, verdict: Verdict, now: int, exits: dict | None = None) -> dict:
        exits = exits or {}
        if symbol not in self.rules or symbol in EXCLUDED:  # a hard rule of the contest: allowed markets only (D3)
            self.event(now, "buy refused: not an allowed market", symbol=symbol)
            return {"placed": False, "error": f"{symbol} is not an allowed market"}
        rules = self.rules[symbol]
        try:
            bid, ask = fetch_best_prices(symbol)
        except WallexError as error:
            return {"placed": False, "error": str(error)}
        price = rules.round_price(ask if exits.get("order") == "taker" else bid, "BUY")  # taker: fill at once
        qty = rules.round_qty(Decimal(str(verdict.tmn)) / price)
        problems = rules.problems(qty, price)
        if problems:
            self.event(now, "buy refused by rules", symbol=symbol, problems=problems)
            return {"placed": False, "error": "; ".join(problems)}
        cid = new_client_id("b")
        try:
            self.trader.place(symbol, "BUY", qty, price, cid)
        except WallexError as error:
            self.event(now, "buy failed", symbol=symbol, error=str(error), client_id=cid)
            return {"placed": False, "error": str(error)}
        p = Position(symbol, setup, float(verdict.tmn), verdict.stop_pct, now, cid,
                     target_pct=float(exits.get("target_pct") or 0), max_hours=float(exits.get("max_hours") or 0),
                     trend_exit=bool(exits.get("trend_exit")),
                     fill_minutes=int(exits.get("fill_minutes") or FILL_WINDOW // 60))
        self.positions_.append(p)
        self.save()
        self.event(now, "buy placed", p, price=str(price), quantity=str(qty), rule=verdict.rule)
        return {"placed": True, "client_id": cid, "price": str(price), "quantity": str(qty)}

    def sell(self, symbol: str, f: dict | None, now: int, reason: str) -> list[dict]:
        closed = []
        for p in self.active():
            if p.symbol != symbol:
                continue
            if p.status == "buying":
                self.cancel_buy(p, now)
            if p.status == "open":
                closed += self.send_sell(p, now, reason)
        self.save()
        return closed

    def cancel_buy(self, p: Position, now: int) -> None:
        """Cancel a buy. Whatever filled becomes an open position."""
        try:
            state = self.trader.cancel(p.buy_id) or self.trader.get(p.buy_id)
            state = self.trader.get(p.buy_id) or state
        except WallexError as error:
            self.event(now, "cancel failed", p, error=str(error))
            return
        self.take_fill(p, state, now)
        if p.status == "buying":
            p.status = "cancelled"
            self.event(now, "buy cancelled", p)

    def take_fill(self, p: Position, state: OrderState | None, now: int) -> None:
        if state is None or not state.filled_qty:
            return
        got = state.filled_qty - state.fee_coin
        avg = state.avg_price or state.price
        p.qty, p.entry = str(got), float(avg)
        p.cost_tmn = float(state.filled_tmn + state.fee_quote)
        p.entry_t, p.status = p.entry_t or now, "open"
        self.event(now, "bought", p)

    def send_sell(self, p: Position, now: int, reason: str) -> list[dict]:
        rules = self.rules[p.symbol]
        try:
            bid, _ = fetch_best_prices(p.symbol)
            free = self.balances().get(rules.base, (Decimal(0), Decimal(0)))[1]
        except WallexError as error:
            self.event(now, "sell failed", p, error=str(error))
            return []
        qty = rules.round_qty(min(Decimal(p.qty), free))
        price = rules.round_price(bid * (1 - SELL_SLIP), "SELL")
        if rules.problems(qty, price):  # too small to sell: dust stays, the position is done
            p.note = f"left {qty} as dust, below the minimum order"
            return [self.close(p, now, reason)]
        cid = new_client_id("s")
        try:
            state = self.trader.place(p.symbol, "SELL", qty, price, cid)
        except WallexError as error:
            self.event(now, "sell failed", p, error=str(error))
            return []
        p.status, p.sell_id, p.sell_t, p.sell_reason = "selling", cid, now, reason
        self.event(now, "sell placed", p, price=str(price), quantity=str(qty))
        return self.check_sell(p, state, now)

    def check_sell(self, p: Position, state: OrderState | None, now: int) -> list[dict]:
        """Book a sell that filled. If it is still open after RESELL_AFTER, cancel it and send it again."""
        if state is None:
            return []
        if not state.done:
            if now - (p.sell_t or now) >= RESELL_AFTER:
                self.trader.cancel(p.sell_id)
                state = self.trader.get(p.sell_id) or state
            else:
                return []
        p.proceeds_tmn += float(state.filled_tmn - state.fee_quote - state.fee_coin * (state.avg_price or 0))
        left = Decimal(p.qty) - state.filled_qty
        p.qty = str(max(left, Decimal(0)))
        if left > 0 and not self.rules[p.symbol].problems(self.rules[p.symbol].round_qty(left), state.price or 1):
            p.status = "open"  # part is left: sell it again now
            return self.send_sell(p, now, p.sell_reason)
        return [self.close(p, now, p.sell_reason)]

    def close(self, p: Position, now: int, reason: str) -> dict:
        p.status, p.exit_t, p.sell_reason = "closed", now, reason
        p.net_pct = round((p.proceeds_tmn / p.cost_tmn - 1) * 100, 3) if p.cost_tmn else None
        self.event(now, "closed", p)
        view = {"symbol": p.symbol, "setup": p.setup, "net_pct": p.net_pct, "entry": p.entry,
                "entry_t": p.entry_t, "exit_t": now, "placed_t": p.t, "reason": reason}
        self.unreported.append(view)
        return view

    # --- every cycle and every minute ---
    def sync(self, table: dict[str, dict], now: int) -> list[dict]:
        """Read every order back from Wallex, and apply the code exits (stop, the setup's rule)."""
        closed = []
        for p in self.active():
            try:
                if p.status == "buying":
                    state = self.trader.get(p.buy_id)
                    if state is not None and state.done:
                        self.take_fill(p, state, now)
                        if p.status == "buying":
                            p.status = "cancelled"
                            self.event(now, "buy ended unfilled", p, wallex_status=state.status)
                    elif now >= p.t + p.fill_minutes * 60:
                        self.cancel_buy(p, now)
                elif p.status == "selling":
                    closed += self.check_sell(p, self.trader.get(p.sell_id), now)
                if p.status == "open":
                    f = table.get(p.symbol)
                    hours = (now - (p.entry_t or p.t)) / 3600
                    if f and (f.get("ema20_vs_ema50_pct") or 0) >= 0:
                        p.trend_up_seen = True  # a dip bought in a downtrend is not sold for that downtrend
                    if f and p.stop and f["price"] <= p.stop:
                        closed += self.send_sell(p, now, "stop")
                    elif f and p.target_pct and f["price"] >= p.entry * (1 + p.target_pct / 100):
                        closed += self.send_sell(p, now, "target")
                    elif f and (p.max_hours or p.trend_exit) and \
                            exit_rule(p.max_hours, p.trend_exit and p.trend_up_seen)(f, hours):
                        closed += self.send_sell(p, now, "plan exit (time or trend)")
                    elif f and p.setup in SETUPS and not (p.max_hours or p.trend_exit) \
                            and SETUPS[p.setup].exit(f, hours):
                        closed += self.send_sell(p, now, "setup exit: " + SETUPS[p.setup].exit_meaning)
            except WallexError as error:
                self.event(now, "sync failed", p, error=str(error))
        self.save()
        return closed

    def guard(self, now: int) -> list[dict]:
        """Every minute: stops on the live bid, unfilled sells, old buys, and the end of trading."""
        closed = []
        if self.end_at is not None and self.end_at - now <= self.limits.flatten_minutes * 60:
            return self.flatten({}, now)
        closes = market_closes(self.data_dir)
        for p in self.active():
            try:
                if closing(closes, p.symbol, now, SELL_MINUTES) and p.status in ("buying", "open"):
                    if p.status == "buying":  # Wallex will close this market: get out while we still can
                        self.cancel_buy(p, now)
                    if p.status == "open":
                        closed += self.send_sell(p, now, "market closes")
                elif p.status == "open" and p.stop:
                    bid, _ = fetch_best_prices(p.symbol)
                    if float(bid) <= p.stop:
                        closed += self.send_sell(p, now, "stop")
                    elif p.target_pct and float(bid) >= p.entry * (1 + p.target_pct / 100):
                        closed += self.send_sell(p, now, "target")
                    elif p.max_hours and now - (p.entry_t or p.t) >= p.max_hours * 3600:
                        closed += self.send_sell(p, now, "time limit")
                elif p.status == "selling":
                    closed += self.check_sell(p, self.trader.get(p.sell_id), now)
                elif p.status == "buying" and now >= p.t + p.fill_minutes * 60:
                    self.cancel_buy(p, now)
            except WallexError as error:
                self.event(now, "guard failed", p, error=str(error))
        self.save()
        return closed

    def flatten(self, table: dict[str, dict], now: int) -> list[dict]:
        """Sell everything into Toman: cancel buys, sell positions, push unfilled sells again."""
        closed = []
        for p in self.active():
            try:
                if p.status == "buying":
                    self.cancel_buy(p, now)
                if p.status == "open":
                    closed += self.send_sell(p, now, "end of trading")
                elif p.status == "selling":
                    closed += self.check_sell(p, self.trader.get(p.sell_id), now)
            except WallexError as error:
                self.event(now, "flatten failed", p, error=str(error))
        self.save()
        return closed

    def kill(self, now: int) -> dict:
        """The kill switch: cancel every open order on the account, then sell every position."""
        cancelled = []
        with self.lock:
            try:
                for o in self.trader.open_orders():
                    self.trader.cancel(o.client_id)
                    cancelled.append(o.client_id)
            except WallexError as error:
                self.event(now, "kill: cancel failed", error=str(error))
            closed = self.flatten({}, now)
            self.event(now, "kill", cancelled=cancelled)
        return {"cancelled": cancelled, "closed": closed, "still_active": [asdict(p) for p in self.active()]}

    def report(self) -> dict:
        return {"active": [f"{p.symbol}:{p.status}" for p in self.active()],
                "closed": [(p.symbol, p.net_pct, p.sell_reason) for p in self.positions_ if p.status == "closed"]}
