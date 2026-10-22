import json

import pytest

from wx import cycle
from wx.config import Settings
from wx.cycle import Context, run_cycle
from wx.llm import Reply
from wx.replay import History
from wx.risk import Verdict
from wx.shadow import Book

T0 = 1_700_000_000 - 1_700_000_000 % 3600
FEATURES = {"price": 100.0, "spread_pct": 0.2, "atr14_pct": 1.0, "data_age_min": 1.0, "round_trip_cost_pct": 0.8,
            "setups": ["sharp_drop"], "rsi14": 25.0}


def minutes(n, low_at=None, low=99.8, crash_at=None):
    rows = [[T0 + i * 60, 100.0, 100.0, 100.0, 100.0, 1.0] for i in range(n)]
    if low_at is not None:
        rows[low_at][3] = low
    if crash_at is not None:
        for row in rows[crash_at:]:
            row[1:5] = [90.0] * 4
    return History([], rows)


def test_order_life_fill_then_stop(tmp_path):
    log = tmp_path / "orders.jsonl"
    book = Book()
    book.place("BTCTMN", "sharp_drop", FEATURES, Verdict(1_000_000, 4.0, "approved", "approved"), T0, log)
    assert book.cash == 4_000_000
    book.update({"BTCTMN": minutes(5)}, T0 + 300, log)
    assert book.orders[0].status == "waiting"
    book.update({"BTCTMN": minutes(20, low_at=10)}, T0 + 1200, log)
    assert book.orders[0].status == "open" and book.orders[0].entry == pytest.approx(99.9)
    book.update({"BTCTMN": minutes(200, low_at=10, crash_at=100)}, T0 + 12000, log)
    o = book.orders[0]
    # Opens at 90, below the 4% stop: out at 90. Maker fee in, taker fee and half the spread out.
    assert o.status == "closed" and o.net_pct == pytest.approx((90 / 99.9 - 1) * 100 - 0.25 - 0.4, abs=1e-3)
    assert book.cash == pytest.approx(4_000_000 + 1_000_000 * (1 + o.net_pct / 100))
    events = [json.loads(line)["event"] for line in log.read_text(encoding="utf-8").splitlines()]
    assert events == ["placed", "filled", "closed"]


def test_unfilled_order_is_cancelled_after_an_hour(tmp_path):
    log = tmp_path / "orders.jsonl"
    book = Book()
    book.place("BTCTMN", "sharp_drop", FEATURES, Verdict(500_000, 4.0, "approved", "approved"), T0, log)
    book.update({"BTCTMN": minutes(70)}, T0 + 4200, log)
    assert book.orders[0].status == "cancelled" and book.cash == 5_000_000


def test_book_survives_a_restart(tmp_path):
    path, log = tmp_path / "book.json", tmp_path / "orders.jsonl"
    book = Book()
    book.place("BTCTMN", "oversold", FEATURES, Verdict(700_000, 4.0, "approved", "approved"), T0, log)
    book.save(path)
    again = Book.load(path)
    assert again == book and again.held() == {"BTCTMN"}
    assert Book.load(tmp_path / "missing.json") == Book()


def test_sell_now_closes_at_the_bid(tmp_path):
    log = tmp_path / "orders.jsonl"
    book = Book()
    book.place("BTCTMN", "sharp_drop", FEATURES, Verdict(1_000_000, 4.0, "approved", "approved"), T0, log)
    book.update({"BTCTMN": minutes(20, low_at=10)}, T0 + 1200, log)
    assert book.positions({"BTCTMN": {"price": 110.0}}, T0 + 3600)["BTCTMN"]["pnl_pct"] == pytest.approx(10.11, abs=0.01)
    book.sell_now("BTCTMN", {"price": 110.0, "spread_pct": 0.2}, T0 + 3600, log)
    assert book.orders[0].status == "closed" and book.active() == []


def test_shadow_cycle_places_an_approved_buy(monkeypatch, tmp_path):
    settings = Settings({"LLM_BASE_URL": "https://ai.example.com/v1", "LLM_MODEL": "m1", "LLM_API_KEY": "sk-x"})
    monkeypatch.setattr(cycle, "collect_features", lambda symbols, s, d: ({"BTCTMN": FEATURES}, {}))
    answer = {"market_view": "dip", "decisions": [{"symbol": "BTCTMN", "action": "BUY", "confidence": 0.6,
                                                   "setup": "sharp_drop", "reason": "r", "cited": ["rsi14"]}]}
    monkeypatch.setattr(cycle, "chat", lambda *a, **k: Reply(json.dumps(answer), "m1", 1.0))
    ctx = Context({"BTCTMN": {}}, settings, tmp_path, role="veto", shadow=True)
    record = run_cycle(ctx, 1)
    assert record["decisions"][0]["action"] == "BUY"
    # 0.75% of 5,000,000 at risk with a 4% stop is 937,500 TMN.
    assert record["shadow"]["verdicts"]["BTCTMN"] == {"tmn": 937_500, "rule": "approved", "reason": "approved"}
    assert Book.load(ctx.book_path).held() == {"BTCTMN"}
    second = run_cycle(ctx, 2)
    assert second["shadow"]["verdicts"]["BTCTMN"]["rule"] == "already held"
    assert "Shadow book: equity" in cycle.report(second)
