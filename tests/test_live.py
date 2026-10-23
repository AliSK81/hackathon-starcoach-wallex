from datetime import UTC, datetime
from decimal import Decimal

import pytest

from wx import live
from wx.live import LiveExecutor
from wx.orders import OrderState
from wx.risk import Verdict
from wx.rules import MarketRules
from wx.wallex import WallexError

RULES = {"SOLTMN": MarketRules("SOLTMN", "SOL", "TMN", 5, 0, Decimal("0.00001"), Decimal("50000"), False)}
NOW = 2_000_000_000


class FakeTrader:
    """Keeps orders in memory. A test decides when they fill."""

    def __init__(self):
        self.orders: dict[str, OrderState] = {}

    def place(self, symbol, side, qty, price, client_id, kind="LIMIT"):
        o = OrderState(client_id, symbol, side, "NEW", True, price, qty, Decimal(0), Decimal(0), Decimal(0), Decimal(0))
        self.orders[client_id] = o
        return o

    def fill(self, client_id, fraction=Decimal(1), fee_coin=Decimal(0), fee_quote=Decimal(0), price=None):
        o = self.orders[client_id]
        o.filled_qty = o.qty * fraction
        o.filled_tmn = o.filled_qty * (price or o.price)
        o.fee_coin, o.fee_quote = fee_coin, fee_quote
        if fraction == 1:
            o.status, o.active = "FILLED", False

    def get(self, client_id):
        return self.orders.get(client_id)

    def cancel(self, client_id):
        o = self.orders.get(client_id)
        if o and o.active:
            o.status, o.active = "CANCELED", False
        return o

    def open_orders(self):
        return [o for o in self.orders.values() if o.active]


@pytest.fixture
def ex(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "fetch_best_prices", lambda s: (Decimal("1000000"), Decimal("1001000")))
    e = LiveExecutor(FakeTrader(), "key", RULES, tmp_path)
    monkeypatch.setattr(e, "balances", lambda: {"TMN": (Decimal(5_000_000), Decimal(4_000_000)),
                                                "SOL": (Decimal("1"), Decimal("1"))})
    return e


def f(price=1_000_000.0, **extra):
    return {"price": price, "spread_pct": 0.1, "ema20_vs_ema50_pct": 1.0, "rsi14": 50, "bb_z_20": 0, **extra}


def test_a_buy_is_a_limit_at_the_bid_and_becomes_a_position_when_it_fills(ex):
    result = ex.buy("SOLTMN", "stretched_dip", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW)
    assert result["placed"] and result["price"] == "1000000" and result["quantity"] == "1.00000"
    ex.trader.fill(result["client_id"], fee_coin=Decimal("0.0025"))
    ex.sync({"SOLTMN": f()}, NOW + 60)
    [p] = ex.positions_
    assert (p.status, p.qty, p.entry) == ("open", "0.99750", 1_000_000.0)
    assert p.stop == pytest.approx(960_000)
    assert ex.held() == {"SOLTMN"} and ex.positions({"SOLTMN": f()}, NOW)["SOLTMN"]["entry"] == 1_000_000.0


def test_an_unfilled_buy_is_cancelled_after_the_fill_window_and_a_part_fill_is_kept(ex):
    r = ex.buy("SOLTMN", "stretched_dip", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW)
    ex.trader.fill(r["client_id"], Decimal("0.5"))
    ex.sync({"SOLTMN": f()}, NOW + 3601)
    [p] = ex.positions_
    assert p.status == "open" and Decimal(p.qty) == Decimal("0.5")
    assert ex.trader.orders[r["client_id"]].status == "CANCELED"


def test_the_guard_sells_at_the_stop_and_books_the_result(ex, monkeypatch):
    r = ex.buy("SOLTMN", "stretched_dip", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW)
    ex.trader.fill(r["client_id"], fee_quote=Decimal(2500))
    ex.sync({"SOLTMN": f()}, NOW + 60)
    monkeypatch.setattr(live, "fetch_best_prices", lambda s: (Decimal("950000"), Decimal("951000")))
    ex.guard(NOW + 120)
    [p] = ex.positions_
    assert p.status == "selling" and p.sell_reason == "stop"
    sell = ex.trader.orders[p.sell_id]
    assert sell.side == "SELL" and sell.price == Decimal("945250")  # 0.5% under the bid, so it fills at once
    ex.trader.fill(p.sell_id, fee_quote=Decimal(2850), price=Decimal("950000"))
    ex.guard(NOW + 180)
    assert p.status == "closed" and p.net_pct == pytest.approx((947150 / 1002500 - 1) * 100, abs=0.001)
    assert ex.drain_closed()[0]["reason"] == "stop" and ex.drain_closed() == []


def test_a_sell_that_does_not_fill_is_sent_again(ex):
    r = ex.buy("SOLTMN", "stretched_dip", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW)
    ex.trader.fill(r["client_id"])
    ex.sync({"SOLTMN": f()}, NOW + 60)
    ex.sell("SOLTMN", None, NOW + 100, "take_profit")
    [p] = ex.positions_
    first = p.sell_id
    ex.guard(NOW + 100 + live.RESELL_AFTER)
    assert ex.trader.orders[first].status == "CANCELED" and p.sell_id != first and p.status == "selling"


def test_the_setup_exit_rule_sells_after_12_hours(ex):
    r = ex.buy("SOLTMN", "stretched_dip", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW)
    ex.trader.fill(r["client_id"])
    ex.sync({"SOLTMN": f()}, NOW + 60)
    ex.sync({"SOLTMN": f()}, NOW + 12 * 3600 + 120)
    assert ex.positions_[0].status == "selling" and "12 hours" in ex.positions_[0].sell_reason


def test_flatten_and_kill_cancel_buys_and_sell_positions(ex):
    a = ex.buy("SOLTMN", "stretched_dip", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW)
    ex.trader.fill(a["client_id"])
    ex.sync({"SOLTMN": f()}, NOW + 60)
    ex.end_at = NOW + 1000
    ex.guard(NOW + 200)  # within 30 minutes of the end: sell everything
    assert ex.positions_[0].status == "selling" and ex.positions_[0].sell_reason == "end of trading"
    result = ex.kill(NOW + 300)
    assert result["cancelled"]


def test_a_refused_order_is_logged_not_raised(ex, monkeypatch):
    def refuse(*args, **kwargs):
        raise WallexError("POST /v1/account/orders: HTTP 400 1234 insufficient balance")
    monkeypatch.setattr(ex.trader, "place", refuse)
    result = ex.buy("SOLTMN", "stretched_dip", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW)
    assert not result["placed"] and "insufficient" in result["error"] and ex.positions_ == []


def test_the_book_survives_a_restart(ex, tmp_path):
    r = ex.buy("SOLTMN", "stretched_dip", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW)
    again = LiveExecutor(ex.trader, "key", RULES, tmp_path)
    assert [p.buy_id for p in again.positions_] == [r["client_id"]]


def test_order_state_reads_wallex_fields():
    o = OrderState.from_wallex({"clientOrderId": "wx_b_1", "symbol": "SOLTMN", "side": "BUY", "status": "FILLED",
                                "active": False, "price": "100", "origQty": "2", "executedQty": "2",
                                "executedSum": "200", "fills": [{"fee": "0.005", "feeAsset": "SOL"},
                                                                {"fee": "1", "feeAsset": "TMN"}]})
    assert o.done and o.avg_price == 100 and o.fee_coin == Decimal("0.005") and o.fee_quote == 1


def test_an_excluded_or_unknown_market_is_never_ordered(ex):
    for symbol in ("APTTMN", "NOPETMN"):  # APT/TMN is on the exclusion list; NOPETMN has no rules
        result = ex.buy(symbol, "trend", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW)
        assert not result["placed"] and "not an allowed market" in result["error"]
    assert ex.trader.orders == {}


def test_the_agents_exit_plan_target_and_time_limit(ex, monkeypatch):
    r = ex.buy("SOLTMN", "agent", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW,
               {"target_pct": 3.0, "max_hours": 6, "trend_exit": False, "order": "maker"})
    ex.trader.fill(r["client_id"])
    ex.sync({"SOLTMN": f()}, NOW + 60)
    [p] = ex.positions_
    assert (p.target_pct, p.max_hours) == (3.0, 6.0)
    monkeypatch.setattr(live, "fetch_best_prices", lambda s: (Decimal("1031000"), Decimal("1032000")))
    ex.guard(NOW + 120)
    assert p.status == "selling" and p.sell_reason == "target"


def test_a_taker_buy_is_priced_at_the_ask(ex):
    r = ex.buy("SOLTMN", "agent", f(), Verdict(1_000_000, 4.0, "approved", "approved"), NOW, {"order": "taker"})
    assert r["price"] == "1001000"


def test_a_position_is_sold_before_its_market_closes(ex, tmp_path):
    import json as js
    ex.buy("SOLTMN", "x", f(), Verdict(500_000, 4.0, "approved", "ok"), NOW)
    p = ex.positions_[0]
    ex.trader.fill(p.buy_id)
    ex.sync({"SOLTMN": f()}, NOW + 60)
    assert p.status == "open"
    ex.guard(NOW + 120)
    assert p.status == "open"  # no close planned
    close = datetime.fromtimestamp(NOW + 20 * 60, UTC).strftime("%Y-%m-%dT%H:%M")
    (tmp_path / "market_closes.json").write_text(js.dumps({"SOLTMN": close}), encoding="utf-8")
    ex.guard(NOW + 180)
    assert p.status in ("selling", "closed") and p.sell_reason == "market closes"


def test_the_trend_exit_waits_for_a_real_turn(ex):
    """A dip bought in a downtrend is not sold at once for that downtrend; once the trend was up, a turn sells."""
    ex.buy("SOLTMN", "stretched_dip", f(), Verdict(500_000, 6.0, "approved", "ok"), NOW,
           {"max_hours": 12, "trend_exit": True})
    p = ex.positions_[0]
    ex.trader.fill(p.buy_id)
    down = f(ema20_vs_ema50_pct=-1.3)
    ex.sync({"SOLTMN": down}, NOW + 60)
    ex.sync({"SOLTMN": down}, NOW + 900)
    assert p.status == "open" and not p.trend_up_seen
    ex.sync({"SOLTMN": f(ema20_vs_ema50_pct=0.4)}, NOW + 1800)
    assert p.status == "open" and p.trend_up_seen
    ex.sync({"SOLTMN": down}, NOW + 2700)
    assert p.status in ("selling", "closed") and p.sell_reason == "plan exit (trend turned)"


def test_the_guard_books_a_fill_within_the_minute(ex):
    ex.buy("SOLTMN", "x", f(), Verdict(500_000, 4.0, "approved", "ok"), NOW)
    p = ex.positions_[0]
    ex.guard(NOW + 60)
    assert p.status == "buying"  # not filled yet: keep waiting
    ex.trader.fill(p.buy_id)
    ex.guard(NOW + 120)
    assert p.status == "open" and p.entry  # booked by the guard, before the next cycle: the stop is live


def test_the_time_limit_is_the_agents_call_not_a_sale(ex):
    ex.buy("SOLTMN", "x", f(), Verdict(500_000, 4.0, "approved", "ok"), NOW, {"max_hours": 1})
    p = ex.positions_[0]
    ex.trader.fill(p.buy_id)
    ex.sync({"SOLTMN": f()}, NOW + 60)
    ex.guard(NOW + 2 * 3600)
    ex.sync({"SOLTMN": f()}, NOW + 2 * 3600)
    assert p.status == "open"  # past its 1-hour limit, still held
    assert ex.positions({"SOLTMN": f()}, NOW + 2 * 3600)["SOLTMN"]["past_time_limit"] is True
