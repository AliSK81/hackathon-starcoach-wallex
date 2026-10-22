import json
from datetime import UTC, datetime

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration

from test_brain import NOW
from wx.decide import log_decision, verify_chain
from wx.llm_cache import SQLiteLLMCache
from wx.risk import Account, Ledger, Limits, check_buy, mode_cap
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






def test_agent_replay_summary_compares_the_agent_with_rules_and_holding():
    from wx.agent_replay import summary
    rec = {"ai_error": None, "tool_calls": 4, "account_pct": 0.2, "rules_trades": [1.0, -2.0], "hold_12h_pct": -0.5,
           "trades": [{"symbol": "A", "tmn": 100, "net_pct": 2.0}, {"symbol": "B", "tmn": 0, "net_pct": None}]}
    text = summary([rec])
    assert "1 filled buys, +2.00% a trade" in text and "2 trades, -0.50% a trade" in text


def test_rule_set_mode_cap_after_losses():
    assert mode_cap(4_700_000, 5_000_000, 4_800_000) == "normal"  # 6% below the peak
    assert mode_cap(5_000_000, 5_000_000, 5_000_000) == "aggressive"


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
    m["DEEPTMN"] = {"stats": {"24h_tmnVolume": "2e9"}}  # thin by volume, but its book can take our size
    m["TINYTMN"] = {"stats": {"24h_tmnVolume": "5e8"}}  # under the floor: its book is not even read
    asked = []
    picked = liquid(m, held={"HELDTMN"}, book=lambda s: asked.append(s) or s == "DEEPTMN")
    assert "DEEPTMN" in picked and "THINTMN" not in picked and "TINYTMN" not in asked


def test_reasoning_models_get_no_temperature():
    from wx.config import Settings
    from wx.runner import chat_model, fixed_temperature
    assert fixed_temperature("openai/gpt-5-mini") and fixed_temperature("gpt-5-mini") and fixed_temperature("o3")
    assert not fixed_temperature("mohaymen/qwen3.8-27b") and not fixed_temperature("~deepseek/deepseek-flash-latest")
    settings = Settings({"LLM_MODEL": "openai/gpt-5-mini", "LLM_BASE_URL": "http://localhost:1", "LLM_API_KEY": "x"})
    payload = chat_model(settings)._get_request_payload([("user", "hi")])
    assert "temperature" not in payload
    settings = Settings({"LLM_MODEL": "mohaymen/qwen3.8-27b", "LLM_BASE_URL": "http://localhost:1", "LLM_API_KEY": "x"})
    assert chat_model(settings)._get_request_payload([("user", "hi")])["temperature"] == 0


def test_the_code_version_is_read_once(monkeypatch):
    from wx import decide
    monkeypatch.setattr(decide, "_VERSION", None)
    calls = []
    monkeypatch.setattr(decide, "_read_version", lambda: calls.append(1) or f"0.1.0+v{len(calls)}")
    assert decide.code_version() == decide.code_version() == "0.1.0+v1" and len(calls) == 1
