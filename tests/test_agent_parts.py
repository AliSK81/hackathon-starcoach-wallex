import json
from datetime import UTC, datetime

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration
from langgraph.store.memory import InMemoryStore

from test_brain import NOW, FakeExecutor, brain, market, plan
from wx.brain import build_graph, check_plan, recall
from wx.decide import log_decision, verify_chain
from wx.llm_cache import SQLiteLLMCache
from wx.risk import RISK_MODES, Account, Ledger, Limits, check_buy, mode_cap
from wx.trades import History, trade
from wx.wallex_mcp import book_summary, candle_bars, walk

ACCOUNT = Account(5_000_000, 5_000_000, 0, 5_000_000, 5_000_000)


def test_cost_is_part_of_the_size():
    f = {"atr14_pct": 1.5, "data_age_min": 1, "round_trip_cost_pct": 1.0}
    plain = check_buy(f, ACCOUNT, limits=Limits()).tmn
    with_cost = check_buy(f, ACCOUNT, limits=Limits(cost_in_size=True)).tmn
    assert with_cost < plain < 1_250_000  # risk / (6% stop + 1% cost) instead of risk / 6%


def test_min_edge_blocks_a_market_whose_usual_move_is_too_small():
    f = {"atr14_pct": 1.0, "data_age_min": 1, "round_trip_cost_pct": 0.7, "typical_24h_move_pct": 1.2}
    v = check_buy(f, ACCOUNT, limits=Limits(min_edge=1.5))
    assert v.rule == "edge" and v.tmn == 0
    assert check_buy({**f, "typical_24h_move_pct": 3.0}, ACCOUNT, limits=Limits(min_edge=1.5)).tmn > 0


def test_trade_cap_cooldown_and_losing_streak():
    f = {"atr14_pct": 1.0, "data_age_min": 1}
    capped = Ledger([[NOW - 60, "A"]] * 12, [])
    assert check_buy(f, ACCOUNT, limits=Limits(max_trades_day=12), ledger=capped, now=NOW, symbol="B").rule \
        == "trade cap"
    stopped = Ledger([], [[NOW - 600, "A", -2.0, "stop"]])
    limits = Limits(cooldown_stop_min=120)
    assert check_buy(f, ACCOUNT, limits=limits, ledger=stopped, now=NOW, symbol="A").rule == "cooldown"
    assert check_buy(f, ACCOUNT, limits=limits, ledger=stopped, now=NOW, symbol="B").tmn > 0
    losses = Ledger([], [[NOW - 600 - i, "A", -1.0, "stop"] for i in range(3)])
    assert losses.streak() == 3
    assert check_buy(f, ACCOUNT, limits=Limits(loss_streak=3), ledger=losses, now=NOW, symbol="B").rule \
        == "loss streak"


def test_take_profit_exits_at_the_target():
    t0 = 1_700_000_000 - 1_700_000_000 % 3600
    minutes = [[t0 + 60 * i, 100.0, 100.5 if i != 30 else 103.0, 99.5, 100.0, 1.0] for i in range(240)]
    h = History([], minutes)
    f = {"price": 100.0, "spread_pct": 0.0, "round_trip_cost_pct": 0.6}
    done = trade(h, "stretched_dip", t0, f, 10.0, "taker", lambda hour: None, take_profit_pct=2.0)
    assert done.exit_reason == "take profit" and abs(done.net_pct - 1.4) < 1e-9


def test_walk_and_book_summary_give_the_cost_of_our_order_size():
    asks = [(100.0, 5000.0), (101.0, 10000.0)]
    assert walk(asks, 400_000, 100.0) == 0.0  # fits in the first level
    assert walk(asks, 1_000_000, 100.0) > 0.0
    assert walk([(100.0, 1.0)], 1_000_000, 100.0) is None  # the book is too thin
    s = book_summary({"bid": [{"price": 99, "quantity": 20000}], "ask": [{"price": 101, "quantity": 20000}]})
    assert "buy_1250k_cost_pct" in s and s["sell_500k_cost_pct"] is not None


def test_candle_bars_build_larger_bars_from_minutes():
    t0 = 1_700_000_100 - 1_700_000_100 % 900
    raw = {"t": [t0 + 60 * i for i in range(30)], "o": [100] * 30, "h": [101] * 30, "l": [99] * 30,
           "c": [100 + i for i in range(30)], "v": [1] * 30}
    bars = candle_bars(raw, 15, 2)
    assert len(bars) == 2 and bars[0]["o"] == 0.0 and bars[-1]["c"] == 29.0 and bars[0]["v"] == 15


def test_the_llm_cache_records_and_replays(tmp_path):
    path = tmp_path / "c.sqlite"
    record = SQLiteLLMCache(path)
    answer = [ChatGeneration(message=AIMessage("hello"))]
    record.update("prompt", "model", answer)
    assert record.lookup("prompt", "model") is None  # live runs only record
    replay = SQLiteLLMCache(path, replay=True)
    assert replay.lookup("prompt", "model")[0].message.content == "hello"


def test_the_decision_log_is_hash_chained(tmp_path):
    when = datetime(2026, 10, 22, tzinfo=UTC)
    for i in range(3):
        path = log_decision(tmp_path, {"cycle": i}, when, chain=True)
    assert verify_chain(path) == (3, [])
    lines = path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[1])
    edited["cycle"] = 99
    lines[1] = json.dumps(edited)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    checked, problems = verify_chain(path)
    assert checked == 3 and "changed" in problems[0]


def test_bull_and_bear_run_and_reach_the_analyst():
    case = {"cases": [{"symbol": "SOLTMN", "argument": "deep dip", "evidence": ["bb_z_20"], "strength": 0.6}]}
    b, logs = brain([case, case, plan()], {"SOLTMN": market()})
    b.debate = True
    state = build_graph(b).invoke({})
    assert state["bull"]["cases"] and state["bear"]["cases"] and b.executor.bought
    assert logs[0]["bull"]["cases"][0]["symbol"] == "SOLTMN"


def test_lessons_come_back_losses_first_and_a_buy_keeps_its_thesis():
    store = InMemoryStore()
    store.put(("lessons",), "1", {"symbol": "A", "setup": "s", "net_pct": 1.0, "loss": False, "lesson": "won", "t": 3})
    store.put(("lessons",), "2", {"symbol": "B", "setup": "s", "net_pct": -2.0, "loss": True, "lesson": "lost", "t": 1})
    assert [x["lesson"] for x in recall(store, None, 5)] == ["lost", "won"]
    b, _ = brain([plan()], {"SOLTMN": market()})
    build_graph(b).invoke({})
    assert b.store.get(("theses",), "SOLTMN").value["reason"] == "deep dip"


def test_a_halted_bot_buys_nothing():
    b, _ = brain([plan()], {"SOLTMN": market()})
    b.halted = True
    state = build_graph(b).invoke({})
    assert not b.executor.bought and state["decisions"][0]["verdict"]["rule"] == "halted"


def test_safe_mode_skips_the_debate():
    b, _ = brain([plan()], {"SOLTMN": market()}, FakeExecutor())
    b.debate = True
    state = build_graph(b).invoke({"fail_streak": 5})
    assert state["bull"] == {} and b.executor.bought


def test_agent_replay_summary_compares_ai_buys_with_all_candidates():
    from wx.agent_replay import summary
    rec = {"ai_error": None, "tool_calls": 4, "results": [
        {"symbol": "A", "ai": "BUY", "tmn": 100, "net_pct": 2.0, "conviction": 0.7, "officer": ""},
        {"symbol": "B", "ai": "HOLD", "tmn": 0, "net_pct": -1.0, "conviction": 0.2, "officer": ""},
        {"symbol": "C", "ai": "BUY", "tmn": 0, "net_pct": None, "conviction": 0.5, "officer": ""}]}
    text = summary([rec])
    assert "every candidate (rules only): +0.50% (2)" in text and "bought by the agent:          +2.00% (1)" in text


def mode_state(mode, cap="aggressive", setup="trend", grade="B"):
    return {"table": {"SOLTMN": market(setups=[setup])}, "risk_mode": "normal", "mode_cap": cap, "positions": {},
            "candidates": [{"symbol": "SOLTMN", "setup": setup, "grade": grade,
                            "modes": ["active", "aggressive"] if setup == "trend" else list(RISK_MODES)}],
            "plan": {"risk_mode": mode, "candidates": [{"symbol": "SOLTMN", "decision": "TAKE", "conviction": 1.0}]}}


def test_the_agent_chooses_the_mode_and_the_mode_decides_what_is_traded():
    d, _, mode = check_plan(mode_state("aggressive"))
    assert mode == "aggressive" and d[0]["action"] == "BUY" and d[0]["scale"] == 1.0  # ungraded in aggressive
    d, _, mode = check_plan(mode_state("active"))
    assert mode == "active" and d[0]["scale"] == 0.5  # grade B halves the risk
    d, _, mode = check_plan(mode_state("defensive"))
    assert d[0]["action"] == "HOLD" and "not traded in risk mode defensive" in d[0]["problems"][0]


def test_code_caps_the_mode_after_losses_and_keeps_it_on_a_bad_answer():
    assert mode_cap(4_700_000, 5_000_000, 4_800_000) == "normal"  # 6% below the peak
    assert mode_cap(5_000_000, 5_000_000, 5_000_000) == "aggressive"
    d, problems, mode = check_plan(mode_state("aggressive", cap="normal"))
    assert mode == "normal" and d[0]["action"] == "HOLD" and "capped" in problems[0]
    _, problems, mode = check_plan(mode_state("reckless"))
    assert mode == "normal" and "unknown" in problems[0]


def test_the_backtest_buys_a_market_once_even_with_two_active_setups():
    from wx.backtest import setups_policy
    policy = setups_policy(("trend_strong", "trend"))
    picks = policy(0, {"A": {"setups": ["trend", "trend_strong"]}, "B": {"setups": ["trend"]}}, set())
    assert picks == [("A", "trend_strong"), ("B", "trend")]


def test_the_universe_is_every_liquid_market_plus_held_and_context():
    from wx.universe import liquid
    m = {s: {"stats": {"24h_tmnVolume": v}} for s, v in
         (("BIGTMN", "9e9"), ("THINTMN", "1e9"), ("HELDTMN", "1e8"), ("BTCTMN", "2e9"), ("USDTTMN", "3e10"))}
    assert list(liquid(m, held={"HELDTMN"})) == ["USDTTMN", "BIGTMN", "BTCTMN", "HELDTMN"]
