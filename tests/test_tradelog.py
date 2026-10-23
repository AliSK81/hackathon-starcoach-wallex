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


def test_the_live_report_explains_each_trade(tmp_path):
    from wx.live_report import live_report
    live = tmp_path / "live"
    (live / "decisions").mkdir(parents=True)
    base = {"symbol": "SOLTMN", "setup": "stretched_dip", "tmn": 900_000, "stop_pct": 6.0, "max_hours": 12,
            "trend_exit": True, "buy_id": "wx_b_1"}
    events = [{"t": T0, "event": "buy placed", **base, "status": "buying", "price": "100", "quantity": "9000"},
              {"t": T0, "event": "bought", **base, "status": "open", "qty": "8977.5", "entry": 100.0,
               "cost_tmn": 900_000},
              {"t": T0, "event": "closed", **base, "status": "closed", "qty": "0.5", "entry": 100.0,
               "cost_tmn": 900_000, "proceeds_tmn": 905_000, "net_pct": 0.556, "exit_price": 101.0,
               "sell_reason": "plan exit (time or trend)", "exit_t": T0 + 7200}]
    (live / "orders.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    record = {"time": "2023-11-14T22:14:00+00:00", "decided_at": T0, "role": "brain", "version": "0.1.0+abc",
              "plan": {"buys": []}, "account": {"equity": 5_005_000},
              "markets": {"SOLTMN": {"setups": ["stretched_dip"], "rsi14": 27.0, "bb_z_20": -2.6}},
              "decisions": [{"symbol": "SOLTMN", "action": "BUY", "strategy": "stretched_dip", "conviction": 0.7,
                             "reason": "deep dip", "invalidation": "new low", "risk_pct": 1.5, "stop_pct": 6.0,
                             "order": "maker", "judge": "fine", "verdict": {"tmn": 900_000, "reason": "approved"}}]}
    (live / "decisions" / "d.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    text = live_report(tmp_path, now=T0 + 7300)
    assert "| Return | +0.10% |" in text and "1 won, average +0.56%" in text and "0.5 SOL" in text
    from wx.live_report import live_trades, real_net
    assert real_net(live_trades(tmp_path)[0]) == round((905_000 + 0.5 * 101 * 0.997) / 900_000 * 100 - 100, 3)
    assert "Signal seen by code:** stretched_dip. Numbers: rsi14 27.0, bb_z_20 -2.6" in text
    assert "Reason: deep dip" in text and "Judge (AI):** fine" in text and "at 101" in text
    assert "`0.1.0+abc`" in text and "buy placed -> bought -> closed" in text
