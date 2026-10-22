import json

from wx.risk import Verdict
from wx.shadow import Book
from wx.tradelog import table, trades
from wx.trades import History

T0 = 1_700_000_000 - 1_700_000_000 % 3600
F = {"price": 100.0, "spread_pct": 0.2}


def test_each_order_is_joined_with_the_decision_that_placed_it(tmp_path):
    log = tmp_path / "shadow" / "orders.jsonl"
    log.parent.mkdir()
    book = Book()
    book.place("BTCTMN", "trend", F, Verdict(1_000_000, 4.0, "max per coin", "shrunk"), T0, log)
    minutes = [[T0 + i * 60, 100.0, 100.0, 99.0 if i == 5 else 100.0, 100.0, 1.0] for i in range(30)]
    book.update({"BTCTMN": History([], minutes)}, T0 + 1800, log)
    decision = {"time": "2023-11-14T22:14:00+00:00", "decided_at": T0, "decisions": [
        {"symbol": "BTCTMN", "action": "BUY", "confidence": 0.65, "reason": "strong | uptrend"}]}
    (tmp_path / "decisions").mkdir()
    (tmp_path / "decisions" / "d.jsonl").write_text(json.dumps(decision) + "\n", encoding="utf-8")
    [row] = trades(tmp_path)
    assert (row["symbol"], row["rule"], row["confidence"], row["status"]) == ("BTCTMN", "max per coin", 0.65, "open")
    text = table([row])
    assert "| BTCTMN | trend | 1,000,000 | max per coin | 0.65 | strong / uptrend | open | - | - |" in text


def test_no_orders_gives_an_empty_table(tmp_path):
    (tmp_path / "decisions").mkdir()
    assert trades(tmp_path) == []
    assert table([]).count("\n") == 1


def test_live_orders_are_joined_with_the_live_decisions(tmp_path):
    live = tmp_path / "live"
    (live / "decisions").mkdir(parents=True)
    events = [{"t": T0, "event": "buy placed", "symbol": "SOLTMN", "setup": "trend_strong", "tmn": 500_000,
               "status": "buying", "rule": "risk"},
              {"t": T0, "event": "closed", "symbol": "SOLTMN", "setup": "trend_strong", "tmn": 500_000,
               "status": "closed", "entry": 100.0, "sell_reason": "stop", "net_pct": -1.2},
              {"t": T0 + 60, "event": "kill", "cancelled": []}]
    (live / "orders.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    decision = {"time": "2023-11-14T22:14:00+00:00", "decided_at": T0, "executor": "live", "decisions": [
        {"symbol": "SOLTMN", "action": "BUY", "conviction": 0.7, "reason": "fresh push"}]}
    (live / "decisions" / "d.jsonl").write_text(json.dumps(decision) + "\n", encoding="utf-8")
    [row] = trades(tmp_path, live=True)
    assert (row["confidence"], row["status"], row["exit"], row["net_pct"]) == (0.7, "closed", "stop", -1.2)
    assert trades(tmp_path) == []  # the shadow log is separate
