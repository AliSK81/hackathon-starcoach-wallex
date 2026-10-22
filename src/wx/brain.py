"""The trading agent: one LangGraph graph per decision cycle.

          ┌─> bull ─┐
    sense ┤         ├─> analyst ──> risk_officer ──> gate ──> act ──> reflect ──> journal
      │   └─> bear ─┘  (LLM agent,   (LLM judge,      (code)   (code)  (LLM, only
      │   (LLM, in      tools,        can only                          when trades
      │    parallel)    skills,       shrink)                           closed)
      │                 memory)
      └── nothing to decide ─────────────────────────────────────> act

- sense (code): live features for every market, whole-market context, the book
  and trade flow of each candidate (Wallex MCP), our account and positions.
  Candidates are markets where a 12-hour setup (setups.SHORT_SETUPS) is active.
- bull, bear (LLM, in parallel): each argues one side for every candidate, citing
  feature names only. Skipped in safe mode or over the daily token budget.
- analyst (LLM): a ReAct agent with read-only tools. It reads trader skills
  (skills/*.md), weighs the bull and bear cases, and gets its lessons from past
  trades (losses first) and its own thesis for each position. It studies each
  candidate and each position, and answers in JSON.
- risk_officer (LLM): judges the debate and challenges each TAKE. It can only
  make an order smaller, never bigger.
- gate (code): checks every claim against the data (checked vetoes, checked exit
  reasons), and sizes every buy with the risk check. The AI never sizes an order.
- act (code): sends approved orders to the executor (shadow book or Wallex).
- reflect (LLM): after a trade closes, writes one lesson to long-term memory.
- journal (code): logs the whole cycle, and keeps a short summary for the next cycles.

Memory. Short term: the graph's state is saved after every cycle (SQLite
checkpointer), so the agent sees what it thought in its last cycles. Long term:
lessons and closed trades live in a SQLite store, and the agent can recall them.

AI suggests, code decides (ROADMAP rule 7). If the AI fails, nothing is bought.
After SAFE_AFTER failed analyst cycles in a row, the bot is in safe mode: no
debate and no officer (fewer calls) until the analyst answers again.
"""

import json
import operator
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware, ToolRetryMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.sqlite import SqliteStore

from wx.features import FEATURES
from wx.llm import LLMError, parse_json
from wx.risk import AGENT_LIMITS, Account, Limits, check_buy, edge_problem
from wx.setups import SETUPS, SHORT_SETUPS
from wx.veto import VETOES

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
RECENT_CYCLES = 8  # cycle summaries the agent sees from its short-term memory
MAX_TOOL_ROUNDS = 10
TAKE_PROFIT_NET_PCT = 1.0  # exit reason take_profit: the gain after a round trip is at least this
ROUND_TRIP_PCT = 0.55  # maker in, taker out, a little spread
OFFICER_CUT = 0.5  # a REDUCE from the risk officer halves the risk
SAFE_AFTER = 3  # failed analyst cycles in a row before safe mode
TOKEN_BUDGET = 3_000_000  # AI tokens a UTC day. Above it, no debate and no officer
AUTO_LESSONS = 6  # lessons put in the analyst's facts, losses first

# 12-hour record of each setup on 18 markets over 120 days: fixed 12-hour hold, 4 ATR stop, net of costs (F41).
# `scripts/study_12h.py` makes these numbers again.
RECORD_12H = {
    "capitulation": {"entries": 229, "avg_net_pct": 0.41, "win_pct": 52, "first_half": 0.06, "second_half": 0.62},
    "stretched_dip": {"entries": 560, "avg_net_pct": 0.25, "win_pct": 50, "first_half": 0.02, "second_half": 0.42},
    "dip_toman_weak": {"entries": 189, "avg_net_pct": 0.31, "win_pct": 54, "first_half": 0.32, "second_half": 0.31},
    "trend_strong": {"entries": 5166, "avg_net_pct": 0.31, "win_pct": 45, "first_half": 0.78, "second_half": -0.51},
    "every_hour_any_market": {"entries": 37980, "avg_net_pct": -0.26, "win_pct": 38},
}

EXITS = {
    "take_profit": f"the position is up at least {TAKE_PROFIT_NET_PCT}% after the round-trip cost",
    "setup_exit": "the setup's own exit rule holds now",
    "sell_pressure": VETOES["sell_pressure"][0],
    "market_crash": VETOES["market_crash"][0],
}

# Features shown per market in the overview. The rest are one tool call away.
OVERVIEW = ("price", "spread_pct", "ret_1h_pct", "ret_24h_pct", "typical_24h_move_pct", "ema20_vs_ema50_pct",
            "trend_4h_pct", "rsi14", "rsi14_15m", "bb_z_20", "adx14", "regime", "zero_volume_hours_24", "setups")


class State(TypedDict, total=False):
    cycle: int
    now: int
    hours_left: float | None
    table: dict
    micro: dict
    candidates: list
    positions: dict
    account: dict
    closed: list
    lessons: list
    plan: dict
    review: dict
    decisions: list
    orders: list
    ai: dict
    problems: list
    bull: dict
    bear: dict
    theses: dict
    fail_streak: int  # failed analyst cycles in a row (kept between cycles)
    token_day: int  # the UTC day of tokens_today
    tokens_today: int
    recent: Annotated[list, operator.add]  # short-term memory: one line per cycle, kept by the checkpointer


@dataclass
class Brain:
    """Everything the graph needs from outside. Tests pass fakes."""
    llm: Any  # a LangChain chat model
    executor: Any  # execution.ShadowExecutor or live.LiveExecutor
    features: Callable[[], tuple[dict, dict]]  # () -> (table, errors)
    micro: Callable[[str], dict]  # symbol -> order book and trade flow summary
    closes: Callable[[str, int, int], list[float]]  # (symbol, hours, now) -> hourly closes
    store: Any  # a LangGraph store, for long-term memory
    log: Callable[[dict], None]  # writes one cycle record
    end_at: int | None = None  # Unix time trading ends, if known
    limits: Limits = AGENT_LIMITS
    officer: bool = True  # run the risk officer
    debate: bool = True  # run the bull and bear analysts
    candles: Callable[[str, int, int], list] | None = None  # (symbol, minutes per bar, bars) -> bars, via MCP
    halted: bool = False  # set by the runner after repeated failures: no new buys
    clock: Callable[[], float] = time.time


class _Empty:
    value: dict = {}


def skills_index() -> dict[str, str]:
    """name -> one-line description, from each skill file's header."""
    out = {}
    for path in sorted(SKILLS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        desc = next((line.split(":", 1)[1].strip() for line in lines if line.startswith("description:")), "")
        out[path.stem] = desc
    return out


def read_skill_text(name: str) -> str:
    path = SKILLS_DIR / f"{name}.md"
    if not path.is_file():
        return f"No skill named {name!r}. Skills: {', '.join(skills_index())}"
    return path.read_text(encoding="utf-8")


ANALYST = """You are the analyst of a trading bot on the Wallex exchange in Iran. Spot only, long only.
Markets are quoted in Toman (TMN). The result is counted in Toman when trading ends.

Code found the candidates below: markets where one of our 12-hour setups is active now. Code will BUY
every candidate unless you stop it with a checked veto. You also review each position we hold.

Work like a careful trader:
1. Read the skill trader-core first. Read other skills when a candidate needs them.
2. For each candidate, check its setup record, the shape of its last hours, and its order book and trade
   flow (get_orderbook reads the Wallex MCP server). Check the whole market (BTCTMN, the Toman).
3. Recall lessons from past trades on that market or setup.
4. Decide. Use at most {rounds} tool calls in total. Then answer.

Rules:
- Never invent numbers. Use the tools and name the features you used.
- To stop a candidate, give decision SKIP with one veto from `vetoes`. Code checks the veto against the data.
  A SKIP without a supported veto is overruled, and the buy goes ahead.
- conviction (0 to 1) shrinks the order: risk is scaled from 0.5x (0) to 1.0x (1). It can't make it bigger.
- For a held position: KEEP, or EXIT with one reason from `exit_reasons`. Code checks the reason. Code already
  sells at the stop, on the setup's exit rule, and before the end of trading.

Skills you can read with read_skill: {skills}

Reply with one JSON object and nothing else, in exactly this format:
{format}"""

FORMAT = """{
  "market_view": "<the overall picture, at most 300 characters>",
  "candidates": [{"symbol": "...", "setup": "...", "decision": "TAKE" | "SKIP", "veto": "<only for SKIP>",
                  "conviction": <0 to 1>, "reason": "<at most 300 characters>", "cited": ["<feature names>"],
                  "invalidation": "<what would prove this wrong>"}],
  "positions": [{"symbol": "...", "decision": "KEEP" | "EXIT", "exit_reason": "<only for EXIT>",
                 "reason": "<at most 200 characters>"}]
}
One entry in "candidates" for every candidate, and one in "positions" for every position we hold."""

OFFICER = """You are the risk officer of a trading bot. The analyst wants to buy the candidates below.
You also judge the debate: a bull analyst and a bear analyst each argued one side.
Challenge each buy like a sceptical senior trader: what could go wrong in the next 12 hours, given the
data? You can only answer AGREE or REDUCE (halve the risk). You can't stop a buy and you can't enlarge it.
REDUCE only when the bear case names a concrete risk in the data that the bull case does not answer.
Most good setups deserve AGREE.

Reply with one JSON object: {"reviews": [{"symbol": "...", "verdict": "AGREE" | "REDUCE", "reason": "..."}],
"note": "<one sentence>"}"""

DEBATER = """You are the {side} analyst of a trading bot on Wallex (spot, long only, Toman markets).
For each candidate below, make the strongest honest {side} case for buying it now and holding up to 12 hours.
Use only the numbers given. Cite feature names. Don't invent numbers. Be short.
Reply with one JSON object: {{"cases": [{{"symbol": "...", "argument": "<at most 250 characters>",
"evidence": ["<feature names>"], "strength": <0 to 1>}}]}}"""

REFLECT = """You review closed trades of a trading bot, to write lessons for its future self.
Read the skill below, then reply with one JSON object:
{"lessons": [{"symbol": "...", "setup": "...", "lesson": "<at most 300 characters>"}]}

"""


def build_graph(b: Brain, checkpointer=None):
    """The compiled graph. Nodes are closures over the Brain's parts."""

    def sense(state: State) -> State:
        now = int(b.clock())
        table, errors = b.features()
        problems = [f"{s}: {e}" for s, e in errors.items()]
        with b.executor.lock:
            b.executor.sync(table, now)
            account = b.executor.account(table, now)
            positions = b.executor.positions(table, now)
            held = b.executor.held()
        candidates = [
            {"symbol": s, "setup": name, "grade": SETUPS[name].grade, "meaning": SETUPS[name].meaning}
            for s, f in table.items() if s not in held
            for name in [next((n for n in f.get("setups", []) if n in SHORT_SETUPS), None)] if name
        ]
        too_small = [c for c in candidates if edge_problem(table[c["symbol"]], b.limits)]
        problems += [f"{c['symbol']} {c['setup']} not a candidate: {edge_problem(table[c['symbol']], b.limits)}"
                     for c in too_small]
        candidates = [c for c in candidates if c not in too_small]  # the risk check would refuse them anyway
        micro = {}
        for c in candidates:  # the gate needs the live book to check a sell_pressure veto
            micro[c["symbol"]] = m = b.micro(c["symbol"])
            table[c["symbol"]].update({"buy_share": (m.get("flow") or {}).get("buy_share"),
                                       "imbalance_1pct": (m.get("book") or {}).get("imbalance_1pct")})
        hours_left = None if b.end_at is None else round((b.end_at - now) / 3600, 2)
        day = now // 86400
        tokens = state.get("tokens_today", 0) if state.get("token_day") == day else 0
        theses = {s: (b.store.get(("theses",), s) or _Empty).value for s in positions}
        return {"cycle": state.get("cycle", 0) + 1, "now": now, "hours_left": hours_left, "table": table,
                "token_day": day, "tokens_today": tokens, "bull": {}, "bear": {},
                "theses": {s: t for s, t in theses.items() if t},
                "micro": micro, "candidates": candidates, "positions": positions, "closed": [],
                "account": {"equity": round(account.equity), "cash": round(account.cash),
                            "in_coins": round(account.exposure), "peak": round(account.peak)},
                "lessons": [], "plan": {}, "review": {}, "decisions": [], "orders": [], "ai": {},
                "problems": problems}

    def lean(state: State) -> bool:
        """Safe mode or over the token budget: skip the debate and the officer."""
        return state.get("fail_streak", 0) >= SAFE_AFTER or state.get("tokens_today", 0) >= TOKEN_BUDGET

    def route(state: State):
        if not state["table"]:
            return "journal"
        if not state["candidates"] and not state["positions"]:
            return "act"
        if state["candidates"] and b.debate and not lean(state):
            return ["bull", "bear"]
        return "analyst"

    def debater(side: str):
        def node(state: State) -> State:
            facts = {"candidates": state["candidates"], "hours_left": state["hours_left"],
                     "markets": {c["symbol"]: state["table"][c["symbol"]] for c in state["candidates"]},
                     "books": state["micro"], "btc": state["table"].get("BTCTMN"),
                     "feature_meanings": FEATURES}
            try:
                reply = b.llm.bind(response_format={"type": "json_object"}).invoke(
                    [SystemMessage(DEBATER.format(side=side)), HumanMessage(json.dumps(facts, default=str))])
                out = parse_json(text_of(reply))
                out["tokens"] = (getattr(reply, "usage_metadata", None) or {}).get("total_tokens", 0)
            except Exception as e:  # the analyst decides without this side's case
                out = {"error": f"{type(e).__name__}: {e}"[:300]}
            return {side: out}
        return node

    def analyst(state: State) -> State:
        table = state["table"]
        tools = analyst_tools(b, state)
        prompt = ANALYST.format(rounds=MAX_TOOL_ROUNDS, skills=json.dumps(skills_index()), format=FORMAT)
        facts = {
            "hours_left": state["hours_left"], "account_tmn": state["account"], "positions": state["positions"],
            "candidates": state["candidates"],
            "markets": {s: {k: f.get(k) for k in OVERVIEW} for s, f in table.items()},
            "vetoes": {k: v[0] for k, v in VETOES.items()}, "exit_reasons": EXITS,
            "your_last_cycles": state.get("recent", [])[-RECENT_CYCLES:],
            "lessons_losses_first": recall(b.store, None, AUTO_LESSONS),
            "your_thesis_per_position": state.get("theses", {}),
            "bull_case": state.get("bull") or None, "bear_case": state.get("bear") or None,
            "feature_meanings": FEATURES,
        }
        # A LangChain agent (a LangGraph subgraph): the model calls tools until it answers. Middleware caps the
        # tool calls (then the model must answer) and tries a failed tool once more (the MCP server can be slow).
        agent = create_agent(b.llm, tools, system_prompt=prompt, middleware=[
            ToolCallLimitMiddleware(run_limit=MAX_TOOL_ROUNDS, exit_behavior="continue"),
            ToolRetryMiddleware(max_retries=1, initial_delay=2.0)])
        started = time.monotonic()
        try:
            ask = json.dumps(facts, default=str) + ("\n\nWhen you are done, answer in the JSON format from your "
                                                    "instructions: one entry per candidate and one per position.")
            result = agent.invoke({"messages": [HumanMessage(ask)]},
                                  {"recursion_limit": 4 * MAX_TOOL_ROUNDS + 10})
            messages = result["messages"]
            plan = final_json(b.llm, messages, state)
            error = None
        except Exception as e:  # any AI failure: fail closed, nothing is bought
            messages, plan, error = [], {}, f"{type(e).__name__}: {e}"[:500]
        ai = {"seconds": round(time.monotonic() - started, 1), "steps": tool_steps(messages),
              "tokens": token_count(messages), "error": error, "model": getattr(b.llm, "model_name", "")}
        spent = ai["tokens"] + sum((state.get(s) or {}).get("tokens", 0) for s in ("bull", "bear"))
        return {"plan": plan, "ai": ai, "fail_streak": state.get("fail_streak", 0) + 1 if error else 0,
                "tokens_today": state.get("tokens_today", 0) + spent}

    def risk_officer(state: State) -> State:
        takes = [c for c in state["plan"].get("candidates", []) if c.get("decision") == "TAKE"]
        if not b.officer or not takes or lean(state):
            return {"review": {}}
        facts = {"hours_left": state["hours_left"], "takes": takes,
                 "markets": {c["symbol"]: state["table"].get(c["symbol"]) for c in takes if c.get("symbol") in
                             state["table"]},
                 "books": {s: state["micro"].get(s) for s in (c.get("symbol") for c in takes)},
                 "bull_case": state.get("bull"), "bear_case": state.get("bear"),
                 "rules": read_skill_text("risk-and-sizing")}
        try:
            reply = b.llm.bind(response_format={"type": "json_object"}).invoke(
                [SystemMessage(OFFICER), HumanMessage(json.dumps(facts, default=str))])
            return {"review": parse_json(text_of(reply))}
        except Exception as e:  # the officer can only shrink orders, so without it nothing gets bigger
            return {"review": {"error": f"{type(e).__name__}: {e}"[:300]}}

    def gate(state: State) -> State:
        decisions, problems = check_plan(state, b.limits)
        return {"decisions": decisions, "problems": state["problems"] + problems}

    def act(state: State) -> State:
        table, now, orders = state["table"], state["now"], []
        with b.executor.lock:
            if state["hours_left"] is not None and state["hours_left"] * 60 <= b.limits.flatten_minutes:
                b.executor.flatten(table, now)
                orders.append({"action": "FLATTEN", "reason": "end of trading"})
            for d in state.get("decisions", []):
                if d["action"] == "SELL":
                    b.executor.sell(d["symbol"], table[d["symbol"]], now, d["reason"])
                    orders.append({"symbol": d["symbol"], "action": "SELL", "reason": d["reason"]})
            account = b.executor.account(table, now)
            for d in state.get("decisions", []):
                if d["action"] != "BUY":
                    continue
                f = table[d["symbol"]]
                if b.halted:
                    d["verdict"] = {"tmn": 0, "rule": "halted", "reason": "rejected: halted after repeated failures"}
                    continue
                v = check_buy(f, account, 0.0, b.limits, d["scale"], state["hours_left"], b.executor.ledger(), now,
                              d["symbol"])
                d["verdict"] = {"tmn": v.tmn, "rule": v.rule, "reason": v.reason, "stop_pct": round(v.stop_pct, 2)}
                if v.tmn:
                    result = b.executor.buy(d["symbol"], d["setup"], f, v, now)
                    orders.append({"symbol": d["symbol"], "action": "BUY", "tmn": v.tmn, **result})
                    if result.get("placed"):  # the analyst sees its own thesis while it holds the position
                        b.store.put(("theses",), d["symbol"], {"setup": d["setup"], "reason": d["reason"],
                                                               "invalidation": d["invalidation"], "t": now})
                    account = b.executor.account(table, now)
            closed = b.executor.drain_closed()  # from this cycle's sync and sells, and the guard since the last cycle
        return {"orders": orders, "closed": closed, "decisions": state.get("decisions", [])}

    def reflect(state: State) -> State:
        closed = state.get("closed", [])
        if not closed:
            return {}
        lessons, problems = [], []
        try:
            reply = b.llm.bind(response_format={"type": "json_object"}).invoke(
                [SystemMessage(REFLECT + read_skill_text("post-trade-review")),
                 HumanMessage(json.dumps({"closed_trades": closed, "past_lessons": recall(b.store, None, 10)},
                                         default=str))])
            lessons = parse_json(text_of(reply)).get("lessons", [])
        except Exception as e:  # the trades are still stored below, without a lesson
            problems.append(f"reflect failed: {type(e).__name__}: {e}"[:300])
        for trade in closed:
            key = f"{trade['symbol']}_{trade.get('entry_t') or trade.get('placed_t')}"
            b.store.put(("trades",), key, trade)
        nets = {t["symbol"]: t.get("net_pct") for t in closed}
        for i, lesson in enumerate(lessons):
            if isinstance(lesson, dict) and lesson.get("lesson"):
                symbol = str(lesson.get("symbol", ""))
                net = nets.get(symbol)
                b.store.put(("lessons",), f"{state['now']}_{i}", {
                    "symbol": symbol, "setup": str(lesson.get("setup", "")), "net_pct": net,
                    "loss": net is not None and net < 0, "lesson": str(lesson["lesson"])[:400], "t": state["now"]})
        for trade in closed:
            b.store.delete(("theses",), trade["symbol"])
        return {"lessons": lessons, "problems": state["problems"] + problems}

    def journal(state: State) -> State:
        record = {k: state.get(k) for k in ("cycle", "now", "hours_left", "account", "positions", "candidates",
                                             "micro", "plan", "review", "decisions", "orders", "closed",
                                             "lessons", "ai", "problems", "bull", "bear", "theses",
                                             "fail_streak", "tokens_today")}
        record.update(decided_at=state.get("now"), role="brain", markets=state.get("table"),
                      executor=b.executor.kind)
        b.log(record)
        summary = cycle_summary(state)
        return {"recent": [summary]}

    g = StateGraph(State)
    for name, fn in [("sense", sense), ("bull", debater("bull")), ("bear", debater("bear")), ("analyst", analyst),
                     ("risk_officer", risk_officer), ("gate", gate), ("act", act), ("reflect", reflect),
                     ("journal", journal)]:
        g.add_node(name, fn)
    g.add_edge(START, "sense")
    g.add_conditional_edges("sense", route, ["bull", "bear", "analyst", "act", "journal"])
    g.add_edge(["bull", "bear"], "analyst")  # the analyst waits for both sides
    g.add_edge("analyst", "risk_officer")
    g.add_edge("risk_officer", "gate")
    g.add_edge("gate", "act")
    g.add_edge("act", "reflect")
    g.add_edge("reflect", "journal")
    g.add_edge("journal", END)
    return g.compile(checkpointer=checkpointer, store=b.store)


def analyst_tools(b: Brain, state: State) -> list:
    """Read-only tools for the analyst. They only see data up to this moment."""
    table, now = state["table"], state["now"]
    cache: dict[str, dict] = dict(state.get("micro") or {})

    @tool
    def get_market(symbol: str) -> dict:
        """All features of one market right now (names and meanings as in feature_meanings)."""
        return table.get(symbol) or {"error": f"unknown market {symbol}; markets: {sorted(table)}"}

    @tool
    def get_hourly_closes(symbol: str, hours: int = 24) -> list:
        """The last N hourly closes of one market (N at most 72), oldest first, as % change from the first."""
        closes = b.closes(symbol, max(2, min(int(hours), 72)), now)
        return [round((c / closes[0] - 1) * 100, 2) for c in closes] if closes else []

    @tool
    def get_orderbook(symbol: str) -> dict:
        """Live order book and the last 50 trades of one market, from the Wallex MCP server: spread, Toman within
        1% of the price per side, imbalance, buy share of traded Toman, trades per minute."""
        if symbol not in cache:
            cache[symbol] = b.micro(symbol)
        return cache[symbol]

    @tool
    def get_setup_record(setup: str) -> dict:
        """How a setup did over 12 hours in 120 days of history (F41), and our own closed trades with it."""
        ours = [i.value for i in b.store.search(("trades",), filter={"setup": setup}, limit=50)]
        nets = [t["net_pct"] for t in ours if t.get("net_pct") is not None]
        return {"history_12h": RECORD_12H.get(setup, "no record"), "baseline": RECORD_12H["every_hour_any_market"],
                "our_trades": {"closed": len(nets), "avg_net_pct": round(sum(nets) / len(nets), 2) if nets else None}}

    @tool
    def recall_lessons(symbol: str = "", setup: str = "") -> list:
        """Lessons written after our past trades, newest first. Filter by market and/or setup, or leave both empty."""
        return recall(b.store, {k: v for k, v in (("symbol", symbol), ("setup", setup)) if v} or None, 8)

    @tool
    def read_skill(name: str) -> str:
        """The full text of one trader skill (see the skills list in your instructions)."""
        return read_skill_text(name)

    @tool
    def get_candles(symbol: str, minutes: int = 15, bars: int = 16) -> list:
        """Recent candles of one market from the Wallex MCP server: `minutes` per bar (5, 15 or 60), the last `bars`
        bars (at most 24). Prices are % from the first open, so the shape is easy to read."""
        if b.candles is None:
            return [{"error": "no candle source"}]
        return b.candles(symbol, minutes if minutes in (5, 15, 60) else 15, max(2, min(int(bars), 24)))

    @tool
    def get_portfolio() -> dict:
        """Our account now: equity, cash, positions, drawdown from the peak, buys in the last 24 hours, losses in a
        row, hours left, and the risk limits code applies."""
        acc, ledger = state["account"], b.executor.ledger()
        peak = acc.get("peak") or acc.get("equity") or 1
        return {"account": acc, "positions": state["positions"], "hours_left": state["hours_left"],
                "drawdown_pct": round((1 - (acc.get("equity") or 0) / peak) * 100, 2),
                "buys_last_24h": sum(now - t < 86400 for t, _ in ledger.entries), "losses_in_a_row": ledger.streak(),
                "limits": {k: v for k, v in vars(b.limits).items()}}

    @tool
    def check_order(symbol: str, conviction: float = 0.5) -> dict:
        """What the risk check would do with a buy of this candidate now: size in Toman, or why it refuses.
        Nothing is ordered."""
        c = next((c for c in state["candidates"] if c["symbol"] == symbol), None)
        if c is None:
            return {"error": f"{symbol} is not a candidate"}
        scale = (1.0 if c["grade"] == "A" else b.limits.grade_b_scale) * (0.5 + 0.5 * min(max(conviction, 0), 1))
        acc = state["account"]
        account = Account(acc["equity"], acc["cash"], acc["in_coins"], acc["peak"], acc["equity"])
        v = check_buy(table[symbol], account, 0.0, b.limits, scale, state["hours_left"], b.executor.ledger(), now,
                      symbol)
        return {"tmn": v.tmn, "rule": v.rule, "reason": v.reason, "stop_pct": round(v.stop_pct, 2)}

    return [get_market, get_hourly_closes, get_candles, get_orderbook, get_setup_record, get_portfolio, check_order,
            recall_lessons, read_skill]


def recall(store, filter_: dict | None, limit: int) -> list:
    """Lessons, from losing trades first, then the newest."""
    items = store.search(("lessons",), filter=filter_, limit=100) if store else []
    items = sorted(items, key=lambda i: (not i.value.get("loss"), -i.value.get("t", 0)))[:limit]
    return [{k: i.value.get(k) for k in ("symbol", "setup", "net_pct", "lesson")} for i in items]


def check_plan(state: State, limits: Limits) -> tuple[list[dict], list[str]]:
    """Turn the AI's plan into checked decisions. Code has the last word on every claim."""
    table, plan, problems = state["table"], state.get("plan") or {}, []
    if not plan:  # the AI failed: fail closed, no new buys. Held positions keep their code exits.
        problems.append("no plan from the AI, so no new buys: " + str((state.get("ai") or {}).get("error")))
        return [], problems
    officer = {r.get("symbol"): r for r in (state.get("review") or {}).get("reviews", []) if isinstance(r, dict)}
    said = {c.get("symbol"): c for c in plan.get("candidates", []) if isinstance(c, dict)}
    decisions = []
    for c in state["candidates"]:
        s, f = c["symbol"], table[c["symbol"]]
        a = said.get(s) or {}
        conviction = a.get("conviction")
        conviction = min(max(float(conviction), 0.0), 1.0) if isinstance(conviction, int | float) else 0.5
        d = {"symbol": s, "setup": c["setup"], "grade": c["grade"], "ai_decision": a.get("decision"),
             "conviction": conviction, "reason": str(a.get("reason", ""))[:400], "cited": a.get("cited", []),
             "invalidation": str(a.get("invalidation", ""))[:300], "problems": []}
        if not a:
            d["problems"].append("the AI said nothing about this candidate: the buy goes ahead")
        veto = a.get("veto") or ""
        if a.get("decision") == "SKIP":
            if veto in VETOES and VETOES[veto][1](f, table):
                decisions.append({**d, "action": "HOLD", "veto": veto, "scale": 0.0})
                continue
            d["problems"].append(f"veto {veto!r} overruled: the data does not support it" if veto
                                 else "SKIP without a veto: the buy goes ahead")
        scale = (1.0 if c["grade"] == "A" else limits.grade_b_scale) * (0.5 + 0.5 * conviction)
        if (officer.get(s) or {}).get("verdict") == "REDUCE":
            scale *= OFFICER_CUT
            d["officer"] = officer[s].get("reason", "")
        decisions.append({**d, "action": "BUY", "veto": "", "scale": round(scale, 3)})
    decisions.sort(key=lambda d: -d["conviction"])  # the strongest gets the free cash first

    for p in plan.get("positions", []):
        if not isinstance(p, dict) or p.get("decision") != "EXIT":
            continue
        s, reason = p.get("symbol"), p.get("exit_reason") or ""
        pos = state["positions"].get(s)
        if not pos or "entry" not in pos:
            problems.append(f"EXIT {s}: we hold no open position there")
            continue
        if exit_supported(reason, pos, table[s], table):
            decisions.append({"symbol": s, "action": "SELL", "reason": f"{reason}: {p.get('reason', '')}"[:300]})
        else:
            problems.append(f"EXIT {s} with {reason!r} overruled: the data does not support it")
    return decisions, problems


def exit_supported(reason: str, pos: dict, f: dict, table: dict) -> bool:
    if reason == "take_profit":
        return (pos.get("pnl_pct") or 0) - ROUND_TRIP_PCT >= TAKE_PROFIT_NET_PCT
    if reason == "setup_exit":
        setup = SETUPS.get(pos.get("setup", ""))
        return bool(setup and setup.exit(f, pos.get("hours_held") or 0))
    if reason in ("sell_pressure", "market_crash"):
        return VETOES[reason][1](f, table)
    return False


def text_of(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    text = str(content)
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def plan_problem(plan: dict, state: State) -> str | None:
    """Why a plan does not have the shape code needs, or None if it does."""
    if state["candidates"] and not isinstance(plan.get("candidates"), list):
        return 'no "candidates" list'
    if state["positions"] and not isinstance(plan.get("positions"), list):
        return 'no "positions" list'
    missing = {c["symbol"] for c in state["candidates"]} - {
        c.get("symbol") for c in plan.get("candidates", []) if isinstance(c, dict)}
    return f"no entry for {sorted(missing)}" if missing else None


def final_json(llm, messages: list, state: State) -> dict:
    """The JSON plan in the agent's last answer. If it is broken or has the wrong shape, ask once more in JSON mode."""
    last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    try:
        plan = parse_json(text_of(last))
        problem = plan_problem(plan, state)
    except (LLMError, AttributeError) as error:
        problem = f"not valid JSON ({error})"
    if problem is None:
        return plan
    retry = HumanMessage(
        f"Your last answer has a problem: {problem}. Give your final decisions again, as one JSON object in "
        f"exactly this format:\n{FORMAT}\nCandidates: {json.dumps(state['candidates'])}\n"
        f"Positions: {json.dumps(sorted(state['positions']))}")
    clean = [m for m in messages if not (isinstance(m, AIMessage) and m.tool_calls)
             and not isinstance(m, ToolMessage)]
    reply = llm.bind(response_format={"type": "json_object"}).invoke(clean + [retry])
    plan = parse_json(text_of(reply))
    problem = plan_problem(plan, state)
    if problem:  # still wrong: treat it as a failed AI call, so nothing is bought
        raise LLMError(f"the plan is still unusable: {problem}")
    return plan


def tool_steps(messages: list) -> list[dict]:
    """Every tool call and its result (cut short), for the log."""
    results = {m.tool_call_id: m.content for m in messages if isinstance(m, ToolMessage)}
    return [{"tool": c["name"], "args": c["args"], "result": str(results.get(c["id"], ""))[:600]}
            for m in messages if isinstance(m, AIMessage) for c in (m.tool_calls or [])]


def token_count(messages: list) -> int:
    return sum((getattr(m, "usage_metadata", None) or {}).get("total_tokens", 0) for m in messages)


def cycle_summary(state: State) -> str:
    """One line for the agent's short-term memory."""
    t = time.strftime("%H:%M", time.gmtime(state.get("now", 0)))
    acts = [f"{d['action']} {d['symbol']}" + (f" ({d.get('veto')})" if d.get("veto") else "")
            for d in state.get("decisions", []) if d.get("action") in ("BUY", "SELL", "HOLD")]
    view = (state.get("plan") or {}).get("market_view", "")
    eq = (state.get("account") or {}).get("equity")
    return f"{t} UTC equity {eq}: {', '.join(acts) or 'no action'}. {view}"[:400]


def open_memory(data_dir: Path, name: str):
    """The short-term checkpointer and the long-term store, both SQLite files in data/brain/."""
    folder = data_dir / "brain"
    folder.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(folder / f"{name}_checkpoints.sqlite", check_same_thread=False))
    store = SqliteStore(sqlite3.connect(folder / f"{name}_memory.sqlite", check_same_thread=False,
                                        isolation_level=None))
    store.setup()
    return saver, store
