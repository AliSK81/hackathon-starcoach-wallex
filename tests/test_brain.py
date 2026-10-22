import json
import threading

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from wx.brain import Brain, build_graph, check_plan, skills_index
from wx.risk import Account, Ledger

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
         "plus_di14": 10.0, "minus_di14": 20.0, "setups": ["stretched_dip", "capitulation"]}
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
        return Ledger([[0, s] for s, _, _ in self.bought], [])

    def buy(self, symbol, setup, f, verdict, now):
        self.bought.append((symbol, setup, verdict.tmn))
        return {"placed": True}

    def sell(self, symbol, f, now, reason):
        self.sold.append((symbol, reason))
        self.unreported.append({"symbol": symbol, "setup": "stretched_dip", "net_pct": 1.2, "reason": reason})
        return []

    def flatten(self, table, now):
        self.flattened += 1
        return []

    def drain_closed(self):
        out, self.unreported = self.unreported, []
        return out


def brain(answers, table, executor=None, end_at=None, officer=False):
    logs = []
    b = Brain(llm=FakeLLM(responses=[AIMessage(json.dumps(a)) for a in answers]),
              executor=executor or FakeExecutor(), features=lambda: (json.loads(json.dumps(table)), {}),
              micro=lambda s: {"book": {"imbalance_1pct": -0.5}, "flow": {"buy_share": 0.2}},
              closes=lambda s, h, now: [1.0, 1.1], store=InMemoryStore(), log=logs.append, end_at=end_at,
              officer=officer, debate=False, clock=lambda: NOW)
    return b, logs


def plan(decision="TAKE", veto="", conviction=0.6, symbol="SOLTMN"):
    return {"market_view": "calm", "candidates": [{"symbol": symbol, "setup": "stretched_dip", "decision": decision,
                                                   "veto": veto, "conviction": conviction, "reason": "deep dip"}],
            "positions": []}


def test_a_take_is_sized_by_code_and_bought():
    b, logs = brain([plan()], {"SOLTMN": market()})
    state = build_graph(b).invoke({})
    [d] = state["decisions"]
    assert d["action"] == "BUY" and d["setup"] == "capitulation" and d["scale"] == 0.8  # grade A, conviction 0.6
    assert b.executor.bought and b.executor.bought[0][0] == "SOLTMN"
    assert logs and logs[0]["role"] == "brain" and logs[0]["plan"]["market_view"] == "calm"


def test_a_supported_veto_stops_the_buy_and_an_unsupported_one_is_overruled():
    b, _ = brain([plan("SKIP", "sell_pressure")], {"SOLTMN": market()})  # buy_share 0.2, imbalance -0.5
    state = build_graph(b).invoke({})
    assert state["decisions"][0]["action"] == "HOLD" and not b.executor.bought
    b, _ = brain([plan("SKIP", "illiquid")], {"SOLTMN": market()})  # 0 empty hours, spread 0.1%
    state = build_graph(b).invoke({})
    assert state["decisions"][0]["action"] == "BUY" and "overruled" in state["decisions"][0]["problems"][0]


def test_a_failed_ai_buys_nothing():
    b, _ = brain([{"not": "a plan"}, {"still": "wrong"}], {"SOLTMN": market()})
    state = build_graph(b).invoke({})
    assert not b.executor.bought and state["decisions"] == []
    assert "still unusable" in state["ai"]["error"]  # no entry for SOLTMN, even after asking again


def test_no_new_buys_near_the_end_and_everything_is_sold_at_the_end():
    b, _ = brain([plan()], {"SOLTMN": market()}, end_at=NOW + 2 * 3600)
    state = build_graph(b).invoke({})
    assert not b.executor.bought and state["decisions"][0]["verdict"]["rule"] == "near the end"
    b, _ = brain([plan()], {"SOLTMN": market()}, end_at=NOW + 10 * 60)
    build_graph(b).invoke({})
    assert b.executor.flattened == 1


def test_the_risk_officer_can_only_shrink():
    review = {"reviews": [{"symbol": "SOLTMN", "verdict": "REDUCE", "reason": "thin book"}]}
    b, _ = brain([plan(conviction=1.0), review], {"SOLTMN": market()}, officer=True)
    state = build_graph(b).invoke({})
    assert state["decisions"][0]["scale"] == 0.5


def test_exits_are_checked_and_a_closed_trade_leaves_a_lesson():
    held = {"ETHTMN": {"setup": "stretched_dip", "entry": 90.0, "pnl_pct": 2.0, "hours_held": 3}}
    answer = {"market_view": "", "candidates": [],
              "positions": [{"symbol": "ETHTMN", "decision": "EXIT", "exit_reason": "take_profit", "reason": "+2%"}]}
    lesson = {"lessons": [{"symbol": "ETHTMN", "setup": "stretched_dip", "lesson": "one trade: dips paid"}]}
    b, _ = brain([answer, lesson], {"ETHTMN": market(setups=[])}, FakeExecutor(held))
    state = build_graph(b).invoke({})
    assert b.executor.sold == [("ETHTMN", "take_profit: +2%")]
    assert [i.value["lesson"] for i in b.store.search(("lessons",))] == ["one trade: dips paid"]
    assert state["closed"][0]["symbol"] == "ETHTMN"


def test_an_exit_the_data_does_not_support_is_overruled():
    state = {"table": {"ETHTMN": market()}, "candidates": [], "plan": {"positions": [
        {"symbol": "ETHTMN", "decision": "EXIT", "exit_reason": "take_profit"}]},
        "positions": {"ETHTMN": {"setup": "stretched_dip", "entry": 99.0, "pnl_pct": 0.5, "hours_held": 1}}}
    decisions, problems, mode = check_plan(state)
    assert decisions == [] and "overruled" in problems[-1] and mode == "normal"


def test_short_term_memory_carries_over_between_cycles():
    b, _ = brain([plan(), plan()], {"SOLTMN": market()})
    graph, config = build_graph(b, MemorySaver()), {"configurable": {"thread_id": "t"}}
    graph.invoke({}, config)
    state = graph.invoke({}, config)
    assert state["cycle"] == 2 and len(state["recent"]) == 2 and "BUY SOLTMN" in state["recent"][0]


def test_nothing_to_decide_skips_the_ai():
    b, logs = brain([], {"SOLTMN": market(setups=[])})
    state = build_graph(b).invoke({})
    assert state["ai"] == {} and logs


def test_every_skill_has_a_description():
    skills = skills_index()
    assert {"trader-core", "mean-reversion-dips", "order-book-and-flow", "risk-and-sizing"} <= set(skills)
    assert all(skills.values())
