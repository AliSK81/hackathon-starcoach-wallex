import json
import threading

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from wx.brain import Brain, analyst_tools, build_graph, check_plan, hurst, regime_of, skills_index
from wx.risk import ENVELOPE, Account, Ledger, size_plan

NOW = 2_000_000_000


class FakeLLM(FakeMessagesListChatModel):
    """Answers from a list, in order. Tools and JSON mode are accepted and ignored."""

    def bind_tools(self, tools, **kwargs):
        return self

    def bind(self, **kwargs):
        return self


def market(**extra) -> dict:
    f = {"price": 100.0, "spread_pct": 0.1, "atr14_pct": 1.0, "data_age_min": 1.0, "zero_volume_hours_24": 0,
         "ret_24h_pct": -4.0, "ema20_vs_ema50_pct": -1.0, "rsi14": 20.0, "bb_z_20": -2.6, "adx14": 20.0,
         "plus_di14": 10.0, "minus_di14": 20.0, "setups": ["capitulation"], "round_trip_cost_pct": 0.7}
    return {**f, **extra}


class FakeExecutor:
    kind = "fake"

    def __init__(self, positions=None):
        self.lock = threading.RLock()
        self.bought, self.sold, self.flattened = [], [], 0
        self._positions = positions or {}
        self.unreported = []

    def sync(self, table, now):
        return []

    def account(self, table, now):
        return Account(5_000_000, 5_000_000, 0, 5_000_000, 5_000_000)

    def positions(self, table, now):
        return self._positions

    def held(self):
        return set(self._positions)

    def ledger(self):
        return Ledger([[0, s] for s, *_ in self.bought], [])

    def buy(self, symbol, setup, f, verdict, now, exits=None):
        self.bought.append((symbol, setup, verdict.tmn, exits))
        return {"placed": True}

    def sell(self, symbol, f, now, reason):
        self.sold.append((symbol, reason))
        self.unreported.append({"symbol": symbol, "setup": "capitulation", "net_pct": 1.2, "reason": reason})
        return []

    def flatten(self, table, now):
        self.flattened += 1
        return []

    def drain_closed(self):
        out, self.unreported = self.unreported, []
        return out


def brain(answers, table, executor=None, end_at=None, officer=False, debate=False):
    logs = []
    b = Brain(llm=FakeLLM(responses=[AIMessage(json.dumps(a)) for a in answers]),
              executor=executor or FakeExecutor(), features=lambda: (json.loads(json.dumps(table)), {}),
              micro=lambda s: {"book": {"ask_tmn_within_1pct": 10_000_000_000}}, closes=lambda s, h, now: [1.0, 1.1],
              store=InMemoryStore(), log=logs.append, end_at=end_at, officer=officer, debate=debate,
              clock=lambda: NOW)
    return b, logs


def buy(symbol="SOLTMN", **kw):
    x = {"symbol": symbol, "strategy": "capitulation", "risk_pct": 1.0, "stop_pct": 4.0, "target_pct": None,
         "max_hours": 12, "exit_on_trend_turn": False, "order": "maker", "conviction": 0.7, "reason": "deep dip",
         "invalidation": "new low"}
    return {**x, **kw}


def plan(buys=(), sells=()):
    return {"market_view": "calm", "approach": "normal", "buys": list(buys), "sells": list(sells)}


def test_the_agents_buy_is_sized_by_code_and_placed_with_its_exit_plan():
    b, logs = brain([plan([buy(risk_pct=0.9, target_pct=3, max_hours=8, order="taker")])], {"SOLTMN": market()})
    state = build_graph(b).invoke({})
    [d] = state["decisions"]
    assert d["action"] == "BUY" and d["verdict"]["rule"] == "approved"
    # 0.9% of 5,000,000 lost at a 4% stop plus 0.7% cost: 45,000 / 0.047 (under the 20% cap in one coin)
    assert d["verdict"]["tmn"] == round(45_000 / 0.047)
    symbol, strategy, tmn, exits = b.executor.bought[0]
    assert exits == {"target_pct": 3.0, "max_hours": 8.0, "trend_exit": False, "order": "taker", "fill_minutes": 60}
    assert logs[0]["role"] == "brain" and logs[0]["plan"]["approach"] == "normal"


def test_nothing_is_bought_unless_the_agent_asks():
    b, _ = brain([plan()], {"SOLTMN": market()})
    state = build_graph(b).invoke({})
    assert state["decisions"] == [] and not b.executor.bought


def test_a_failed_ai_buys_nothing():
    b, _ = brain([{"not": "a plan"}, {"still": "wrong"}], {"SOLTMN": market()})
    state = build_graph(b).invoke({})
    assert not b.executor.bought and state["decisions"] == [] and "unusable" in state["ai"]["error"]


def test_the_envelope_clamps_risk_and_stop_and_the_book_caps_the_size():
    d, _ = check_plan({"table": {"SOLTMN": market()}, "positions": {},
                       "plan": plan([buy(risk_pct=9, stop_pct=40, max_hours=500)])})
    assert (d[0]["risk_pct"], d[0]["stop_pct"], d[0]["max_hours"]) == (3.0, 15.0, 72.0)
    acc = Account(5_000_000, 5_000_000, 0, 5_000_000, 5_000_000)
    v = size_plan(market(), acc, 3.0, 2.0, ask_tmn_1pct=1_000_000)
    assert v.tmn == 500_000 and v.rule == "book depth"
    assert size_plan(market(), acc, 3.0, 1.0).rule == "max in one coin"  # never all-in: 40%


def test_halts_and_the_end_of_trading():
    acc = Account(4_400_000, 4_400_000, 0, 5_000_000, 4_600_000)  # 4.3% down today
    assert size_plan(market(), acc, 1.0, 4.0).rule == "daily loss"
    acc = Account(4_400_000, 4_400_000, 0, 5_000_000, 4_400_000)  # 12% under the peak
    assert size_plan(market(), acc, 1.0, 4.0).rule == "drawdown"
    b, _ = brain([plan([buy()])], {"SOLTMN": market()}, end_at=NOW + 40 * 60)
    state = build_graph(b).invoke({})
    assert not b.executor.bought and state["decisions"][0]["verdict"]["rule"] == "near the end"
    b, _ = brain([plan()], {"SOLTMN": market()}, end_at=NOW + 10 * 60)
    build_graph(b).invoke({})
    assert b.executor.flattened == 1


def test_bull_bear_and_the_judge_review_the_agents_buys():
    case = {"cases": [{"symbol": "SOLTMN", "argument": "x", "evidence": ["rsi14"], "strength": 0.5}]}
    review = {"reviews": [{"symbol": "SOLTMN", "verdict": "REDUCE", "risk_pct": 0.4, "reason": "thin"},
                          {"symbol": "ETHTMN", "verdict": "REJECT", "reason": "falling"}]}
    table = {"SOLTMN": market(), "ETHTMN": market()}
    b, _ = brain([plan([buy(), buy("ETHTMN")]), case, case, review], table, officer=True, debate=True)
    state = build_graph(b).invoke({})
    by = {d["symbol"]: d for d in state["decisions"]}
    assert by["SOLTMN"]["action"] == "BUY" and by["SOLTMN"]["risk_pct"] == 0.4
    assert by["ETHTMN"]["action"] == "HOLD" and state["bull"]["cases"] and state["bear"]["cases"]
    assert [s for s, *_ in b.executor.bought] == ["SOLTMN"]


def test_safe_mode_skips_the_debate():
    b, _ = brain([plan([buy()])], {"SOLTMN": market()}, debate=True, officer=True)
    state = build_graph(b).invoke({"fail_streak": 5})
    assert state["bull"] == {} and b.executor.bought


def test_the_agent_sells_what_it_wants_and_a_closed_trade_leaves_a_lesson():
    held = {"ETHTMN": {"setup": "capitulation", "entry": 90.0, "pnl_pct": 2.0, "hours_held": 3}}
    lesson = {"lessons": [{"symbol": "ETHTMN", "setup": "capitulation", "lesson": "one trade: dips paid"}]}
    b, _ = brain([plan(sells=[{"symbol": "ETHTMN", "reason": "momentum gone"}, {"symbol": "XTMN", "reason": "?"}]),
                  lesson], {"ETHTMN": market(setups=[])}, FakeExecutor(held))
    state = build_graph(b).invoke({})
    assert b.executor.sold == [("ETHTMN", "momentum gone")]
    assert any("XTMN" in p for p in state["problems"])
    assert [i.value["lesson"] for i in b.store.search(("lessons",))] == ["one trade: dips paid"]


def test_a_buy_keeps_its_thesis_and_short_term_memory_carries_over():
    b, _ = brain([plan([buy()]), plan()], {"SOLTMN": market()})
    graph, config = build_graph(b, MemorySaver()), {"configurable": {"thread_id": "t"}}
    graph.invoke({}, config)
    assert b.store.get(("theses",), "SOLTMN").value["reason"] == "deep dip"
    state = graph.invoke({}, config)
    assert state["cycle"] == 2 and len(state["recent"]) == 2 and "BUY SOLTMN" in state["recent"][0]


def test_a_halted_bot_buys_nothing():
    b, _ = brain([plan([buy()])], {"SOLTMN": market()})
    b.halted = True
    state = build_graph(b).invoke({})
    assert not b.executor.bought and state["decisions"][0]["verdict"]["rule"] == "halted"


def test_tools_reach_any_allowed_market_and_dry_run_the_size():
    b, _ = brain([], {"SOLTMN": market(), "BTCTMN": market(btc_ret_24h_pct=1.0, usdt_trend_up=True)})
    b.market_features = lambda s: market(price=50.0)
    state = {"table": b.features()[0], "now": NOW, "hours_left": None, "positions": {},
             "account": {"equity": 5_000_000, "cash": 5_000_000, "in_coins": 0, "peak": 5_000_000,
                         "day_start": 5_000_000}}
    extra, micro = {}, {}
    tools = {t.name: t for t in analyst_tools(b, state, extra, micro)}
    assert tools["get_market"].invoke({"symbol": "ADATMN"})["price"] == 50.0 and "ADATMN" in extra
    assert tools["check_order"].invoke({"symbol": "SOLTMN", "risk_pct": 1, "stop_pct": 4})["tmn"] > 0
    assert "playbook" in tools["get_regime"].invoke({"symbol": "SOLTMN"})


def test_regime_and_hurst():
    assert regime_of({"atr_pctile_100": 0.9, "adx14": 15}, 0.3)["playbook"].startswith("choppy")
    trending = [100 * 1.01 ** i for i in range(120)]
    assert hurst(trending) is not None and hurst([1.0] * 10) is None


def test_every_skill_has_a_description():
    skills = skills_index()
    assert {"trader-core", "mean-reversion-dips", "order-book-and-flow", "risk-and-sizing"} <= set(skills)
    assert all(skills.values())
    assert ENVELOPE.max_position < 1 and ENVELOPE.max_exposure < 1  # never all-in


def test_the_pace_follows_the_time_left():
    from wx.horizon import profile
    assert profile(6).name == "sprint" and profile(6).cycle_seconds == 300 and profile(18).name == "short"
    assert profile(72).name == "short" and profile(24 * 30).name == "swing" and profile(None).name == "swing"
    b, _ = brain([plan([buy(max_hours=40)])], {"SOLTMN": market()}, end_at=NOW + 6 * 3600)
    state = build_graph(b).invoke({})
    assert state["profile"]["name"] == "sprint" and state["decisions"][0]["max_hours"] == 6.0  # sprint holds
    assert b.executor.bought[0][3]["fill_minutes"] == 10


def test_a_time_limit_is_kept_to_the_minute():
    from wx.trades import History, trade
    t0 = 1_700_000_000 - 1_700_000_000 % 3600
    minutes = [[t0 + 60 * i, 100.0, 100.2, 99.9, 100.0 + i * 0.01, 1.0] for i in range(240)]
    done = trade(History([], minutes), "agent", t0, {"price": 100.0, "spread_pct": 0.0, "round_trip_cost_pct": 0.6},
                 50.0, "taker", lambda h: None, max_seconds=25 * 60)
    assert done.exit_reason == "time" and done.exit_t == t0 + 25 * 60


def test_fast_features_from_minutes():
    from wx.features import fast_features
    minutes = [[i * 60, 100.0, 100.5, 99.5, 100.0 + (i % 10) * 0.01, 1.0 + (i % 5)] for i in range(1500)]
    f = fast_features(minutes, 100.05)
    assert f["rsi14_5m"] is not None and f["vwap_4h_dev_pct"] is not None and 0 <= f["pos_in_1h_range"] <= 1
    assert fast_features(minutes[:100], 100.0)["rsi14_5m"] is None


SEEN: list = []  # every prompt a RecordingLLM was sent (a pydantic model can't keep it on the class)


class RecordingLLM(FakeLLM):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        SEEN.append(messages)
        return super()._generate(messages, stop, run_manager, **kwargs)


def test_static_text_is_in_the_cached_system_prompt_and_the_portfolio_in_the_facts():
    from wx.brain import EVIDENCE, analyst_prompt, read_skill_text
    prompt = analyst_prompt("sprint-trading", ENVELOPE)
    assert read_skill_text("trader-core") in prompt and read_skill_text("sprint-trading") in prompt
    assert '"short_term"' in prompt and "capitulation" in prompt and str(EVIDENCE["costs"]) in prompt
    assert analyst_prompt("sprint-trading", ENVELOPE) == prompt  # the same every cycle, so it can be cached
    assert analyst_prompt("trader-core", ENVELOPE).count("Skill trader-core:") == 1
    b, _ = brain([plan()], {"SOLTMN": market()})
    b.llm = RecordingLLM(responses=[AIMessage(json.dumps(plan()))])
    SEEN.clear()
    build_graph(b).invoke({})
    system, human = SEEN[0][0], SEEN[0][1]
    assert "Skill trader-core:" in system.content and "short_term" in system.content
    facts = json.loads(human.content.split("\n\n")[0])
    assert facts["our_result"] == "+0.00% since the start, +0.00% today (UTC), 0.00% below the peak"
    assert "envelope" not in facts and "setup_meanings" not in facts  # moved to the system prompt


def test_the_debate_and_judge_get_the_evidence_in_their_system_message():
    case = {"cases": [{"symbol": "SOLTMN", "argument": "x", "evidence": ["rsi14"], "strength": 0.5}]}
    review = {"reviews": [{"symbol": "SOLTMN", "verdict": "APPROVE", "reason": "ok"}]}
    b, _ = brain([], {"SOLTMN": market()}, officer=True, debate=True)
    b.llm = RecordingLLM(responses=[AIMessage(json.dumps(x)) for x in (plan([buy()]), case, case, review)])
    SEEN.clear()
    build_graph(b).invoke({})
    reviews = [m for m in SEEN if "analyst of a trading bot" in m[0].content
               or "judge of a trading bot" in m[0].content]
    assert len(reviews) == 3
    for system, human in reviews:
        assert "short_term" in system.content and "short_term" not in human.content


def test_cached_tokens_are_counted():
    from wx.brain import cached_tokens
    m = AIMessage("x", usage_metadata={"input_tokens": 9000, "output_tokens": 10, "total_tokens": 9010,
                                       "input_token_details": {"cache_read": 6000}})
    assert cached_tokens([m, AIMessage("y")]) == 6000


def test_no_buy_in_a_market_that_closes_soon_and_the_agent_is_told():
    b, _ = brain([], {"SOLTMN": market()})
    b.llm = RecordingLLM(responses=[AIMessage(json.dumps(plan([buy()])))])
    b.market_closes = lambda: {"SOLTMN": NOW + 30 * 60}
    SEEN.clear()
    state = build_graph(b).invoke({})
    assert not b.executor.bought and state["decisions"][0]["verdict"]["rule"] == "market closes"
    facts = json.loads(SEEN[0][1].content.split("\n\n")[0])
    assert "SOLTMN" in facts["markets_closing_utc"]
    assert "active risk" in SEEN[0][0].content
    b.market_closes = lambda: {"SOLTMN": NOW - 60}  # closed already: still listed, still refused
    SEEN.clear()
    b.llm = RecordingLLM(responses=[AIMessage(json.dumps(plan([buy()])))])
    state = build_graph(b).invoke({})
    assert json.loads(SEEN[0][1].content.split("\n\n")[0])["markets_closing_utc"]
    assert state["decisions"][0]["verdict"]["rule"] == "market closes"


def test_market_closes_file(tmp_path):
    from wx.closures import closing, market_closes
    assert market_closes(tmp_path) == {}
    (tmp_path / "market_closes.json").write_text('{"usdttmn": "2026-10-22T20:15"}', encoding="utf-8")
    t = market_closes(tmp_path)["USDTTMN"]
    closes = {"USDTTMN": t}
    assert closing(closes, "USDTTMN", t - 29 * 60, 30) and not closing(closes, "USDTTMN", t - 31 * 60, 30)
    (tmp_path / "market_closes.json").write_text('{"USDTTMN": ["2026-10-22T20:00", "2026-10-23T08:00"]}',
                                                 encoding="utf-8")
    assert "USDTTMN" in market_closes(tmp_path, now=t)  # closed
    assert market_closes(tmp_path, now=t + 12 * 3600) == {}  # reopened at 08:00
    (tmp_path / "market_closes.json").write_text("not json", encoding="utf-8")
    assert market_closes(tmp_path) == {}


def test_no_buy_in_a_market_that_moves_too_little_for_its_cost():
    b, _ = brain([plan([buy()])], {"SOLTMN": market(typical_24h_move_pct=1.0, round_trip_cost_pct=0.9)})
    state = build_graph(b).invoke({})
    assert not b.executor.bought and state["decisions"][0]["verdict"]["rule"] == "moves too little"
    b, _ = brain([plan([buy()])], {"SOLTMN": market(typical_24h_move_pct=3.0, round_trip_cost_pct=0.7)})
    build_graph(b).invoke({})
    assert b.executor.bought
