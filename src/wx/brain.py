"""The trading agent: one LangGraph graph per decision cycle. The agent decides; code keeps the hard limits.

    sense ──> analyst ──┬─> bull ─┬─> officer ──> gate ──> act ──> reflect ──> journal
     (code)  (AI agent) └─> bear ─┘  (AI judge)  (code)   (code)  (AI, after
                         (AI, on the                                closed trades)
                          analyst's own buys)

- sense (code): features of every liquid allowed Toman market, whole-market context, our account, and our
  positions with their exit plans.
- analyst (AI): a ReAct agent with read-only tools (Wallex REST and the Wallex MCP server underneath),
  trader skills (skills/*.md), lessons from past trades and its own last cycles. It decides what a trader
  decides: which markets, whether to buy, how much to risk, where the stop is, how and when to exit, maker or
  taker, and which positions to sell. Setups and past results are evidence it reads, not gates.
- bull, bear (AI, in parallel): argue for and against each buy the analyst proposes.
- officer (AI): judges the debate. For each buy: approve, reduce the risk, or reject.
- gate (code): only the hard envelope (risk.Envelope): allowed markets, never all-in, the stop range, the risk
  range, the daily-loss and drawdown halts, what the book can take, the end of trading. It sizes each buy from
  the agent's risk and stop.
- act (code): orders to the shadow book or Wallex. reflect (AI): one lesson per closed trade.
  journal (code): logs the cycle and keeps a line for the next cycles.

Memory. Short term: the graph's state is saved after every cycle (SQLite checkpointer). Long term: closed
trades, lessons and each position's thesis live in a SQLite store.

If the AI fails, nothing is bought, and held positions keep their exit plans and stops.
After SAFE_AFTER failed analyst cycles in a row, or over the daily token budget, the debate and officer are skipped.
"""

import json
import math
import operator
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import pstdev
from typing import Annotated, Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.sqlite import SqliteStore

from wx.closures import NO_BUY_MINUTES, closing
from wx.features import FEATURES
from wx.horizon import Profile, profile
from wx.llm import LLMError, parse_json
from wx.risk import ENVELOPE, Account, Envelope, clamp, size_plan
from wx.setups import SETUPS

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
RECENT_CYCLES = 8  # cycle summaries the agent sees from its short-term memory
MAX_TOOL_ROUNDS = 12
SAFE_AFTER = 3  # failed analyst cycles in a row before safe mode
TOKEN_BUDGET = 12_000_000  # AI tokens a UTC day (sprint decides every 5 minutes). Above it, no debate
AUTO_LESSONS = 6  # lessons put in the analyst's facts, losses first
# The model's whole window is 32,768 tokens: the prompt plus its reasoning and answer (F59). Its reasoning has
# taken up to about 7,000. Past CLEAR_AT tokens, older tool results are cleared, keeping the newest KEEP_TOOLS.
CLEAR_AT = 16_000
KEEP_TOOLS = 4


def compact(value) -> str:
    """JSON without spaces: the model's window is small."""
    return json.dumps(value, default=str, separators=(",", ":"), ensure_ascii=False)


def overview_table(table: dict, columns: tuple | None = None) -> dict:
    """The market overview as one header and one row per market: far fewer tokens than a dict per market."""
    columns = columns or OVERVIEW
    return {"columns": ["symbol", *columns],
            "rows": [[s, *[f.get(k) for k in columns]] for s, f in table.items()]}

# What our tests on the past found, for get_evidence. Each entry names the fact in docs/DECISIONS.md.
EVIDENCE = {
    "setups_12h": {
        "what": "each buy setup, held 12 hours with a 4 ATR stop, 18 TMN markets, 120 days, after costs (F41)",
        "capitulation (RSI<25, 2 sd under the 20h average)": "+0.41% a trade, both halves positive, 229 trades",
        "stretched_dip (2.5 sd under the 20h average)": "+0.25%, both halves positive, 560 trades",
        "dip_toman_weak": "+0.31%, both halves positive, 189 trades",
        "trend_strong": "+0.31% overall, but +0.78% then -0.51% in the 2nd half",
        "plain trend (EMA20 > EMA50)": "-0.05%; with the Toman getting stronger -0.32%",
        "breakout with volume": "+0.19%, +0.71% then -0.33%",
        "every hour, any market": "-0.26%",
    },
    "rule_sets_by_horizon": {
        "what": "fixed rule sets, sold into Toman at the end of each window, our 6 markets (F53)",
        "careful (dips only, small)": "12h avg -0.04% (ends up 14%), 3 days -0.03%, 89 days +2.8%",
        "normal (12-hour setups)": "12h -0.06% (23%), 3 days +0.13%, 89 days +14.7%",
        "active (plus the trend rule)": "12h -0.13% (34%), 3 days +0.40%, 89 days +25.2%",
        "aggressive (1.5% risk, 35% a coin)": "12h -0.19% (36%), worst -4.2%; 3 days +0.74%; 89 days +42.5% "
                                              "(drawdown 15%); without the Toman drift -4.4%",
        "hold every market": "12h -0.25%, 3 days +1.58% (worst -7.8%)",
    },
    "exits": {
        "what": "exit rules tested on the trend and 12-hour setups (F26, F48)",
        "fixed take-profit 1.5/2/3%": "worse in every test: it cuts the winners",
        "trailing stop 4 or 6 ATR": "worse than a fixed stop",
        "stops 2/3/4 ATR": "every stop lowered the average a little; 4 ATR lowered it least (F19)",
        "time exit after 12h on dips": "used by the dip setups above",
    },
    "usdt_as_cash": {
        "what": "holding USDT instead of Toman: buy USDTTMN, sell it 20 hours later, maker both ways, 0.51% round "
                "trip, every start hour, 120 days (F67)",
        "any time": "-0.16% on average, up in 41%, worst -4.18%; last 30 days -0.01%",
        "after USDTTMN rose over 1.5% in 24 hours": "1st half -0.03% (45% up, about 23 episodes); 2nd half +0.46% "
                                                    "(66% up, about 30 episodes): it worked in one half only",
        "use": "a choice like any market, inside the same limits; it pays only if the Toman falls more than 0.51% "
               "before you sell",
    },
    "time_of_day": "Most of the Toman's fall and coin gains came 01:00-13:00 UTC (Tehran daytime): USDTTMN +0.33% "
                   "to +0.49% on average then, against +0.07% to +0.09% from 13:00 to 01:00 (F44)",
    "how_big_12h": "A coin rose 20% in 12 hours in 0.03% of windows on our markets. Perfect hindsight (buy the low, "
                   "sell the high) reached 20% in under 1% of windows; median +1.5% (F52). Last 12 hours before "
                   "going live: perfect trader within the caps about +3.5%, holding everything -0.33% (F56)",
    "ai_record": "When the AI judged freely in past replays, it skipped the trades that later did best (F20, F27). "
                 "When it shrank weak trades, it helped a little (F33, F51). Base decisions on numbers, not stories.",
    "costs": "Maker 0.25%, taker 0.30% a side on TMN markets, plus the spread. A round trip costs 0.5% to 1%",
    "short_term": {
        "what": "fast strategies on 1-minute data, last 60 days, maker entries, after costs (F62)",
        "5-minute momentum (EMA 9/21 cross, volume)": "-0.53% to -0.95% a trade, profit factor 0.05-0.46, "
                                                     "4 to 13 trades a day",
        "breakout above the 1-hour high with volume": "-0.58% to -0.86% a trade, 13 to 64 trades a day",
        "5-minute dip scalp (RSI under 25, 2 sd under)": "-0.30% to -0.62% a trade, profit factor 0.12-0.73",
        "VWAP reversion (1.5% under the 4-hour VWAP)": "-0.39% to -0.59% a trade",
        "lesson": "every target, stop and hold tried lost: the moves are smaller than the 0.55% round trip. "
                  "Use fast data to time good trades, not to trade more",
    },
}

# Features shown per market in the overview. The rest are one tool call away.
OVERVIEW = ("price", "spread_pct", "ret_1h_pct", "ret_24h_pct", "typical_24h_move_pct", "ema20_vs_ema50_pct",
            "trend_4h_pct", "rsi14", "rsi14_15m", "bb_z_20", "adx14", "atr14_pct", "regime",
            "zero_volume_hours_24", "setups")
# In sprint the overview leads with the fast features (features.fast_features).
FAST_OVERVIEW = ("price", "spread_pct", "ret_5m_pct", "ret_30m_pct", "ret_1h_pct", "ret_24h_pct",
                 "ema9_vs_ema21_5m_pct", "rsi14_5m", "bb_z_5m", "atr14_5m_pct", "vol_ratio_5m", "vwap_4h_dev_pct",
                 "range_1h_pct", "pos_in_1h_range", "ema20_vs_ema50_pct", "regime")


class State(TypedDict, total=False):
    cycle: int
    now: int
    hours_left: float | None
    table: dict
    micro: dict
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
    lean: bool  # safe mode or over the token budget, decided at the start of the cycle
    profile: dict  # the pace for the time left (horizon.py)
    token_day: int  # the UTC day of tokens_today
    tokens_today: int
    recent: Annotated[list, operator.add]  # short-term memory: one line per cycle, kept by the checkpointer


@dataclass
class Brain:
    """Everything the graph needs from outside. Tests pass fakes."""
    llm: Any  # a LangChain chat model
    executor: Any  # execution.ShadowExecutor or live.LiveExecutor
    features: Callable[[], tuple[dict, dict]]  # () -> (table, errors) for the liquid markets
    micro: Callable[[str], dict]  # symbol -> order book and trade flow summary (Wallex MCP)
    closes: Callable[[str, int, int], list[float]]  # (symbol, hours, now) -> hourly closes
    store: Any  # a LangGraph store, for long-term memory
    log: Callable[[dict], None]  # writes one cycle record
    end_at: int | None = None  # Unix time trading ends, if known
    env: Envelope = field(default_factory=lambda: ENVELOPE)
    officer: bool = True  # run the officer
    debate: bool = True  # run the bull and bear analysts
    candles: Callable[[str, int, int], list] | None = None  # (symbol, minutes per bar, bars) -> bars, via MCP
    market_list: Callable[[], list[dict]] | None = None  # every allowed TMN market with Wallex's 24h stats
    market_features: Callable[[str], dict] | None = None  # features of any allowed market, on demand
    market_closes: Callable[[], dict[str, int]] = dict  # market -> Unix time Wallex closes it (closures.py)
    owner_note: Callable[[], str] = str  # the owner's current instruction to the trader (data/owner_note.txt)
    halted: bool = False  # set by the runner after repeated failures: no new buys
    clock: Callable[[], float] = time.time


class _Empty:
    value: dict = {}


def skills_index() -> dict[str, str]:
    """name -> one-line description, from each skill file's header."""
    out = {}
    for path in sorted(SKILLS_DIR.glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        out[path.stem] = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("description:")), "")
    return out


def read_skill_text(name: str) -> str:
    path = SKILLS_DIR / f"{name}.md"
    if not path.is_file():
        return f"No skill named {name!r}. Skills: {', '.join(skills_index())}"
    return path.read_text(encoding="utf-8")


def analyst_prompt(skill: str, env: Envelope) -> str:
    """The trader's system prompt. Everything in it is the same every cycle of a profile, so the provider can
    cache it, and so can each later call of the same cycle, which repeats it and the messages before. That is
    why nothing that changes per cycle goes here: it goes in the first human message (the facts)."""
    names = ["trader-core"] + ([skill] if skill and skill != "trader-core" else [])
    texts = "\n".join(f"\nSkill {n}:\n{read_skill_text(n)}" for n in names)
    return ANALYST.format(rounds=MAX_TOOL_ROUNDS, skills=json.dumps(skills_index()), format=FORMAT,
                          envelope=compact(asdict(env)), setups=compact({k: v.meaning for k, v in SETUPS.items()}),
                          evidence=compact(EVIDENCE), skill_texts=texts)


def portfolio_view(account: dict, positions: dict, hours_left, ledger, now: int, env: Envelope) -> dict:
    """Our account now, as get_portfolio shows it and as the trader's facts carry it."""
    peak, start = account.get("peak") or 1, account.get("day_start") or account.get("equity") or 1
    equity = account.get("equity") or 0
    return {"account": account, "positions": positions, "hours_left": hours_left,
            "today_pct": round((equity / start - 1) * 100, 2), "drawdown_pct": round((1 - equity / peak) * 100, 2),
            "since_start_pct": round((equity / 5_000_000 - 1) * 100, 2),
            "buys_last_24h": sum(now - t < 86400 for t, _ in ledger.entries), "envelope": asdict(env)}


ANALYST = """You are the trader of a bot on the Wallex exchange in Iran. Spot only, long only, Toman (TMN) markets.
Your goal: the highest Toman value of the account when trading ends. All coins are sold into Toman then.

How the contest scores us: profit is ranked among teams, and a loss scores zero. A smaller drawdown also scores.
Regular trading scores a little. So: end above the start, as high as you can, without a deep drawdown.

You decide everything a trader decides: which markets to study, whether to buy, how much to risk, where the
stop is, the exit plan (target, time limit, sell when the trend turns), maker or taker, and which positions to
sell. Nothing is bought unless you ask for it. Code only keeps the hard limits in `envelope` and sizes your buy
from your risk and stop. A bull and a bear analyst will argue each buy you propose, and a judge can reduce or
reject it.

Your pace follows the time left (`profile`): with under a day left you are in sprint. Then decide every 5 minutes
on 1, 5 and 15-minute data, and plan holds of minutes to a few hours; a buy that can't work before the end is a
bad buy. With days or weeks left, slow down and use 1-hour and 4-hour data.

The owner chose active risk (D54), one level under aggressive, and prefers several coins at once over a few
big bets. When you see an edge after costs: risk_pct 1 to 1.5, at most the envelope's limit in one coin (20%), so
several trades can run together. Take the good trades rather than waiting for perfect ones; a buy still needs an
edge after costs. The hard limits and the halts after losses stay.

Follow `owner_instructions` when they are present: the owner of the account wrote them for now.
Never propose a buy in a market listed in `markets_closing_utc`: Wallex closes it (or closed it) at that time, so
code refuses the buy and sells what we hold there before the close.

USDTTMN is a market like the others: holding USDT instead of Toman is a choice you may make, or not, from the
evidence (usdt_as_cash) and the Toman's trend now. It is sold into Toman at the end like every coin.

Work like a professional:
1. The skill trader-core, the skill named in `profile`, the hard limits, the setups and our past evidence are
   below. Your portfolio is in the facts. They are already here: don't fetch them again. Read the market overview.
2. Find opportunities: get_regime and get_market on the markets that matter, list_markets for the rest.
3. Check evidence before you act: get_evidence (what worked here, by horizon and exit), get_orderbook (live book
   and trades from the Wallex MCP server), get_candles or get_hourly_closes (shape), recall_lessons.
4. Size and plan each buy: check_order shows what code would do with your risk and stop.
5. Decide. Use at most {rounds} tool calls. Then answer.

Rules: never invent numbers; name the features you used. A buy with no edge after costs loses money.
Skills (read_skill): {skills}

Reply with one JSON object and nothing else, in exactly this format:
{format}

The hard limits code keeps (envelope): {envelope}
Setups (names the code knows): {setups}
Evidence from our tests on the past (get_evidence gives the same): {evidence}
{skill_texts}"""

FORMAT = """{
  "market_view": "<the overall picture, at most 300 characters>",
  "approach": "<how hard you trade now and why: time left, our result, regime, evidence; at most 300 characters>",
  "buys": [{"symbol": "...", "strategy": "<a setup name or your own short label>",
            "risk_pct": <0.25 to 3: % of equity lost if the stop is hit>,
            "stop_pct": <1 to 15: stop distance under the entry, %>,
            "target_pct": <null, or the gain % to sell at>,
            "max_hours": <the longest hold in hours, 0.1 up to the profile's max_hold_hours>,
            "exit_on_trend_turn": true | false,
            "order": "maker" | "taker",
            "conviction": <0 to 1>, "reason": "<at most 300 characters>", "cited": ["<feature names>"],
            "invalidation": "<what would prove this wrong>"}],
  "sells": [{"symbol": "...", "reason": "<at most 200 characters>"}]
}
"buys" may be empty. Positions not in "sells" are kept with their exit plan."""

DEBATER = """You are the {side} analyst of a trading bot on Wallex (spot, long only, Toman markets).
The trader wants to make the buys below. For each, make the strongest honest {side} case, given the data and the
plan (stop, target, time). Use only the numbers given. Cite feature names. Don't invent numbers. Be short.
Reply with one JSON object: {{"cases": [{{"symbol": "...", "argument": "<at most 250 characters>",
"evidence": ["<feature names>"], "strength": <0 to 1>}}]}}"""

OFFICER = """You are the judge of a trading bot's buys. The trader proposed the buys below, each with a plan, and a
bull and a bear analyst argued each one. Weigh the arguments against the data and the evidence. For each buy:
APPROVE it, REDUCE its risk_pct (give the new, lower value), or REJECT it. Reject only for a concrete reason in the
data. The owner chose active risk with several small positions: reduce a buy only for a concrete reason.
Reply with one JSON object: {"reviews": [{"symbol": "...", "verdict": "APPROVE" | "REDUCE" | "REJECT",
"risk_pct": <only for REDUCE>, "reason": "..."}], "note": "<one sentence>"}"""

# The same every call, so it sits in the system message, where the provider can cache it.
EVIDENCE_NOTE = "\nEvidence from our tests on the past: " + compact(EVIDENCE)

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
        hours_left = None if b.end_at is None else round((b.end_at - now) / 3600, 2)
        day = now // 86400
        tokens = state.get("tokens_today", 0) if state.get("token_day") == day else 0
        theses = {s: (b.store.get(("theses",), s) or _Empty).value for s in positions}
        return {"cycle": state.get("cycle", 0) + 1, "now": now, "hours_left": hours_left, "table": table,
                "profile": profile(hours_left).as_dict(),
                "token_day": day, "tokens_today": tokens, "bull": {}, "bear": {}, "micro": {},
                "lean": state.get("fail_streak", 0) >= SAFE_AFTER or tokens >= TOKEN_BUDGET,
                "theses": {s: t for s, t in theses.items() if t}, "positions": positions, "closed": [],
                "account": {"equity": round(account.equity), "cash": round(account.cash),
                            "in_coins": round(account.exposure), "peak": round(account.peak),
                            "day_start": round(account.day_start)},
                "lessons": [], "plan": {}, "review": {}, "decisions": [], "orders": [], "ai": {},
                "problems": problems}

    def after_sense(state: State) -> str:
        return "analyst" if state["table"] else "journal"

    def after_analyst(state: State):
        buys = (state.get("plan") or {}).get("buys") or []
        if not buys or state.get("lean"):  # safe mode or over the token budget: no debate, no officer
            return "gate"
        if b.debate:
            return ["bull", "bear"]
        return "officer" if b.officer else "gate"

    def analyst(state: State) -> State:
        table = state["table"]
        extra: dict[str, dict] = {}
        micro: dict[str, dict] = {}
        tools = analyst_tools(b, state, extra, micro)
        prompt = analyst_prompt(state["profile"].get("skill", ""), b.env)
        view = portfolio_view(state["account"], state["positions"], state["hours_left"], b.executor.ledger(),
                              state["now"], b.env)
        facts = {
            "now_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(state["now"])),
            "hours_left": state["hours_left"], "profile": state["profile"], "account_tmn": state["account"],
            "positions": state["positions"],
            "result_pct": {k: view[k] for k in ("today_pct", "drawdown_pct", "since_start_pct")},
            "buys_last_24h": view["buys_last_24h"],
            "markets_overview": overview_table(table, FAST_OVERVIEW if state["profile"]["name"] == "sprint"
                                               else OVERVIEW),
            "owner_instructions": b.owner_note() or None,
            "markets_closing_utc": {s: time.strftime("%Y-%m-%d %H:%M", time.gmtime(t))
                                    for s, t in b.market_closes().items()},
            "your_last_cycles": state.get("recent", [])[-RECENT_CYCLES:],
            "lessons_losses_first": recall(b.store, None, AUTO_LESSONS),
            "your_thesis_per_position": state.get("theses", {}),
            "feature_names": "explain_features gives the meaning of any feature",
        }
        # A LangChain agent (a LangGraph subgraph): the model calls tools until it answers. Middleware caps the
        # tool calls (then the model must answer) and tries a failed tool once more (the MCP server can be slow).
        agent = create_agent(b.llm, tools, system_prompt=prompt, middleware=[
            ToolCallLimitMiddleware(run_limit=MAX_TOOL_ROUNDS, exit_behavior="continue"),
            ToolRetryMiddleware(max_retries=1, initial_delay=2.0),
            ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=CLEAR_AT, keep=KEEP_TOOLS,
                                                              exclude_tools=("get_portfolio",))])])
        started = time.monotonic()
        try:
            ask = compact(facts) + "\n\nWhen you are done, answer in the JSON format you were given."
            result = agent.invoke({"messages": [HumanMessage(ask)]}, {"recursion_limit": 4 * MAX_TOOL_ROUNDS + 10})
            messages = result["messages"]
            plan = final_json(b.llm, messages)
            error = None
        except Exception as e:  # any AI failure: fail closed, nothing is bought
            messages, plan, error = [], {}, f"{type(e).__name__}: {e}"[:500]
        ai = {"seconds": round(time.monotonic() - started, 1), "steps": tool_steps(messages),
              "tokens": token_count(messages), "cached_tokens": cached_tokens(messages), "error": error,
              "model": getattr(b.llm, "model_name", ""),
              "largest_prompt_tokens": largest_prompt(messages)}
        return {"plan": plan, "ai": ai, "table": {**table, **extra}, "micro": micro,
                "fail_streak": state.get("fail_streak", 0) + 1 if error else 0,
                "tokens_today": state.get("tokens_today", 0) + ai["tokens"]}

    def debater(side: str):
        def node(state: State) -> State:
            buys = state["plan"].get("buys") or []
            facts = {"buys": buys, "hours_left": state["hours_left"],
                     "markets": {x.get("symbol"): state["table"].get(x.get("symbol")) for x in buys},
                     "books": state.get("micro"), "btc": state["table"].get("BTCTMN")}
            try:
                reply = b.llm.bind(response_format={"type": "json_object"}).invoke(
                    [SystemMessage(DEBATER.format(side=side) + EVIDENCE_NOTE), HumanMessage(compact(facts))])
                out = parse_json(text_of(reply))
                out["tokens"] = (getattr(reply, "usage_metadata", None) or {}).get("total_tokens", 0)
            except Exception as e:  # the judge decides without this side's case
                out = {"error": f"{type(e).__name__}: {e}"[:300]}
            return {side: out}
        return node

    def officer(state: State) -> State:
        buys = state["plan"].get("buys") or []
        if not b.officer or not buys:
            return {"review": {}}
        facts = {"hours_left": state["hours_left"], "buys": buys, "approach": state["plan"].get("approach"),
                 "markets": {x.get("symbol"): state["table"].get(x.get("symbol")) for x in buys},
                 "books": state.get("micro"), "bull_case": state.get("bull"), "bear_case": state.get("bear"),
                 "account": state["account"]}
        spent = sum((state.get(s) or {}).get("tokens", 0) for s in ("bull", "bear"))
        try:
            reply = b.llm.bind(response_format={"type": "json_object"}).invoke(
                [SystemMessage(OFFICER + EVIDENCE_NOTE), HumanMessage(compact(facts))])
            spent += (getattr(reply, "usage_metadata", None) or {}).get("total_tokens", 0)
            review = parse_json(text_of(reply))
        except Exception as e:  # without the judge, the trader's plan stands inside the envelope
            review = {"error": f"{type(e).__name__}: {e}"[:300]}
        return {"review": review, "tokens_today": state.get("tokens_today", 0) + spent}

    def gate(state: State) -> State:
        decisions, problems = check_plan(state, b.env, Profile(**state["profile"]) if state.get("profile")
                                         else None)
        return {"decisions": decisions, "problems": state["problems"] + problems}

    def act(state: State) -> State:
        table, now, orders = state["table"], state["now"], []
        with b.executor.lock:
            if state["hours_left"] is not None and state["hours_left"] * 60 <= b.env.flatten_minutes:
                b.executor.flatten(table, now)
                orders.append({"action": "FLATTEN", "reason": "end of trading"})
            for d in state.get("decisions", []):
                if d["action"] == "SELL":
                    b.executor.sell(d["symbol"], table.get(d["symbol"]), now, d["reason"])
                    orders.append({"symbol": d["symbol"], "action": "SELL", "reason": d["reason"]})
            account = b.executor.account(table, now)
            for d in state.get("decisions", []):
                if d["action"] != "BUY":
                    continue
                f = table[d["symbol"]]
                if closing(b.market_closes(), d["symbol"], now, NO_BUY_MINUTES):
                    d["verdict"] = {"tmn": 0, "rule": "market closes",
                                    "reason": "rejected: Wallex closes this market soon, we could not sell it"}
                    continue
                if b.halted:
                    d["verdict"] = {"tmn": 0, "rule": "halted", "reason": "rejected: halted after repeated failures"}
                    continue
                book = ((state.get("micro") or {}).get(d["symbol"]) or {}).get("book") or {}
                v = size_plan(f, account, d["risk_pct"], d["stop_pct"], b.env, b.executor.ledger(), now,
                              state["hours_left"], book.get("ask_tmn_within_1pct"), symbol=d["symbol"])
                d["verdict"] = {"tmn": v.tmn, "rule": v.rule, "reason": v.reason, "stop_pct": round(v.stop_pct, 2)}
                if v.tmn:
                    exits = {k: d[k] for k in ("target_pct", "max_hours", "trend_exit", "order")}
                    exits["fill_minutes"] = (state.get("profile") or {}).get("fill_minutes", 60)
                    result = b.executor.buy(d["symbol"], d["strategy"], f, v, now, exits)
                    orders.append({"symbol": d["symbol"], "action": "BUY", "tmn": v.tmn, **exits, **result})
                    if result.get("placed"):  # the trader sees its own thesis while it holds the position
                        b.store.put(("theses",), d["symbol"], {"strategy": d["strategy"], "reason": d["reason"],
                                                               "invalidation": d["invalidation"], **exits, "t": now})
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
            b.store.put(("trades",), f"{trade['symbol']}_{trade.get('entry_t') or trade.get('placed_t')}", trade)
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
        record = {k: state.get(k) for k in ("cycle", "now", "hours_left", "account", "positions", "micro", "plan",
                                             "review", "decisions", "orders", "closed", "lessons", "ai", "problems",
                                             "bull", "bear", "theses", "fail_streak", "tokens_today")}
        record.update(decided_at=state.get("now"), role="brain", markets=state.get("table"),
                      executor=b.executor.kind)
        b.log(record)
        return {"recent": [cycle_summary(state)]}

    g = StateGraph(State)
    for name, fn in [("sense", sense), ("analyst", analyst), ("bull", debater("bull")), ("bear", debater("bear")),
                     ("officer", officer), ("gate", gate), ("act", act), ("reflect", reflect), ("journal", journal)]:
        g.add_node(name, fn)
    g.add_edge(START, "sense")
    g.add_conditional_edges("sense", after_sense, ["analyst", "journal"])
    g.add_conditional_edges("analyst", after_analyst, ["bull", "bear", "officer", "gate"])
    g.add_edge(["bull", "bear"], "officer")  # the judge waits for both sides
    g.add_edge("officer", "gate")
    g.add_edge("gate", "act")
    g.add_edge("act", "reflect")
    g.add_edge("reflect", "journal")
    g.add_edge("journal", END)
    return g.compile(checkpointer=checkpointer, store=b.store)


def hurst(closes: list[float]) -> float | None:
    """Hurst exponent of hourly log returns by rescaled range: under 0.4 reverts, over 0.6 trends."""
    if len(closes) < 40:
        return None
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    points = []
    for lag in (8, 12, 16, 24, 32):
        rs = []
        for i in range(0, len(rets) - lag + 1, lag):
            chunk = rets[i:i + lag]
            mean = sum(chunk) / lag
            dev, low, high = 0.0, 0.0, 0.0
            for r in chunk:
                dev += r - mean
                low, high = min(low, dev), max(high, dev)
            s = pstdev(chunk)
            if s > 0:
                rs.append((high - low) / s)
        if rs:
            points.append((math.log(lag), math.log(sum(rs) / len(rs))))
    if len(points) < 3:
        return None
    mx, my = sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
    num = sum((x - mx) * (y - my) for x, y in points)
    den = sum((x - mx) ** 2 for x, _ in points)
    return round(num / den, 2) if den else None


def regime_of(f: dict, h: float | None) -> dict:
    """The 4-quadrant regime of the installed regime-detection skill, with its playbook."""
    vol = f.get("atr_pctile_100")
    vol_regime = "unknown" if vol is None else "low" if vol < 0.3 else "high" if vol > 0.7 else "normal"
    adx = f.get("adx14") or 0
    trend = "trending" if adx > 25 else "ranging" if adx < 20 else "transitional"
    direction = "up" if (f.get("ema20_slope_5h_pct") or 0) > 0 and (f.get("ema20_vs_ema50_pct") or 0) > 0 \
        else "down" if (f.get("ema20_slope_5h_pct") or 0) < 0 and (f.get("ema20_vs_ema50_pct") or 0) < 0 \
        else "neutral"
    volume = "high" if (f.get("vol_ratio_20") or 0) > 1.5 else "low" if (f.get("vol_ratio_20") or 1) < 0.5 \
        else "normal"
    playbook = {
        ("low", "trending"): "clean trend: trend following, normal stops",
        ("normal", "trending"): "trend: trend following",
        ("high", "trending"): "volatile trend: momentum at half size, wide stops",
        ("low", "ranging"): "quiet range: mean reversion",
        ("normal", "ranging"): "range: mean reversion at the edges",
        ("high", "ranging"): "choppy: a quarter size or sit out",
    }.get((vol_regime, trend), "transition: small size or wait")
    return {"volatility": vol_regime, "trend": trend, "direction": direction, "volume": volume, "hurst_100h": h,
            "mean_reversion": None if h is None else "reverting" if h < 0.4 else "trending" if h > 0.6 else "random",
            "playbook": playbook}


def analyst_tools(b: Brain, state: State, extra: dict, micro: dict) -> list:
    """Read-only tools for the trader. They only see data up to this moment."""
    table, now = state["table"], state["now"]

    def features_of(symbol: str) -> dict | None:
        if symbol in table:
            return table[symbol]
        if symbol not in extra and b.market_features is not None:
            try:
                f = b.market_features(symbol)
            except Exception as error:  # a market without enough history, or a Wallex error
                return {"error": f"{type(error).__name__}: {error}"[:200]}
            for k in ("usdt_trend_up", "btc_ret_24h_pct"):  # the whole-market context, as in the overview
                f[k] = next((g.get(k) for g in table.values()), None)
            extra[symbol] = f
        return extra.get(symbol)

    @tool
    def list_markets() -> list:
        """Every allowed Toman market on Wallex now, with its 24-hour Toman volume and price change from Wallex's
        stats, and whether it is in your overview. Use get_market for the features of any of them."""
        if b.market_list is None:
            return [[s, None, None, True] for s in table]
        rows = [[m.get("symbol"), round((m.get("volume_24h_tmn") or 0) / 1e9, 1), m.get("change_24h_pct"),
                 m.get("symbol") in table] for m in b.market_list()]
        return [["symbol", "volume_24h_billion_tmn", "change_24h_pct", "in_overview"], *rows]

    @tool
    def get_market(symbol: str) -> dict:
        """All features of one allowed market right now (names and meanings as in feature_meanings)."""
        return features_of(symbol) or {"error": f"unknown market {symbol}"}

    @tool
    def get_regime(symbol: str) -> dict:
        """The market's regime: volatility, trend, direction, volume, Hurst exponent, and the playbook for it."""
        f = features_of(symbol)
        if not f or "error" in f:
            return f or {"error": f"unknown market {symbol}"}
        return regime_of(f, hurst(b.closes(symbol, 100, now)))

    @tool
    def get_hourly_closes(symbol: str, hours: int = 24) -> list:
        """The last N hourly closes of one market (N at most 72), oldest first, as % change from the first."""
        closes = b.closes(symbol, max(2, min(int(hours), 72)), now)
        return [round((c / closes[0] - 1) * 100, 2) for c in closes] if closes else []

    @tool
    def get_candles(symbol: str, minutes: int = 15, bars: int = 16) -> list:
        """Recent candles from the Wallex MCP server: `minutes` per bar (5, 15 or 60), the last `bars` (at most 24).
        Prices are % from the first open."""
        if b.candles is None:
            return [{"error": "no candle source"}]
        return b.candles(symbol, minutes if minutes in (5, 15, 60) else 15, max(2, min(int(bars), 24)))

    @tool
    def get_orderbook(symbol: str) -> dict:
        """The live book and the last 50 trades from the Wallex MCP server: spread, Toman within 1% per side,
        imbalance, buyer share, trades per minute, and the cost of filling 500k and 1.25M TMN."""
        if symbol not in micro:
            micro[symbol] = b.micro(symbol)
        return micro[symbol]

    @tool
    def get_evidence(topic: str = "all") -> dict:
        """What our tests on the past found. Topics: short_term, setups_12h, rule_sets_by_horizon, exits,
        time_of_day, how_big_12h, ai_record, costs, or all."""
        return EVIDENCE if topic not in EVIDENCE else {topic: EVIDENCE[topic]}

    @tool
    def get_portfolio() -> dict:
        """Our account now: equity, cash, positions with their exit plans, today's result, drawdown, buys in the
        last 24 hours, and the hard limits (envelope)."""
        return portfolio_view(state["account"], state["positions"], state["hours_left"], b.executor.ledger(), now,
                              b.env)

    @tool
    def check_order(symbol: str, risk_pct: float = 1.0, stop_pct: float = 4.0) -> dict:
        """What code would do with a buy of this market with your risk and stop: size in Toman and the limit that
        set it, or why it refuses. Nothing is ordered."""
        f = features_of(symbol)
        if not f or "error" in f:
            return f or {"error": f"unknown market {symbol}"}
        acc = state["account"]
        account = Account(acc["equity"], acc["cash"], acc["in_coins"], acc["peak"], acc.get("day_start") or 0)
        book = (micro.get(symbol) or {}).get("book") or {}
        v = size_plan(f, account, risk_pct, stop_pct, b.env, b.executor.ledger(), now, state["hours_left"],
                      book.get("ask_tmn_within_1pct"), symbol=symbol)
        return {"tmn": v.tmn, "rule": v.rule, "reason": v.reason, "stop_pct": v.stop_pct,
                "pct_of_equity": round(v.tmn / max(acc["equity"], 1) * 100, 1)}

    @tool
    def recall_lessons(symbol: str = "", setup: str = "") -> list:
        """Lessons written after our past trades, losses first. Filter by market and/or setup, or leave both empty."""
        return recall(b.store, {k: v for k, v in (("symbol", symbol), ("setup", setup)) if v} or None, 8)

    @tool
    def explain_features(names: list[str] | None = None) -> dict:
        """The meaning of the named features (all of them if no names are given)."""
        return {k: v for k, v in FEATURES.items() if not names or k in names}

    @tool
    def read_skill(name: str) -> str:
        """The full text of one trader skill (see the skills list in your instructions)."""
        return read_skill_text(name)

    return [get_portfolio, list_markets, get_market, get_regime, get_evidence, get_orderbook, get_candles,
            get_hourly_closes, check_order, recall_lessons, explain_features, read_skill]


def recall(store, filter_: dict | None, limit: int) -> list:
    """Lessons, from losing trades first, then the newest."""
    items = store.search(("lessons",), filter=filter_, limit=100) if store else []
    items = sorted(items, key=lambda i: (not i.value.get("loss"), -i.value.get("t", 0)))[:limit]
    return [{k: i.value.get(k) for k in ("symbol", "setup", "net_pct", "lesson")} for i in items]


def check_plan(state: State, env: Envelope = ENVELOPE, pace: Profile | None = None
               ) -> tuple[list[dict], list[str]]:
    """The trader's plan, after the judge, as decisions. Code only fills gaps and keeps values in the envelope."""
    table, plan, problems = state["table"], state.get("plan") or {}, []
    if not plan:  # the AI failed: fail closed, no new buys. Held positions keep their exit plans and stops.
        problems.append("no plan from the AI, so no new buys: " + str((state.get("ai") or {}).get("error")))
        return [], problems
    review = {r.get("symbol"): r for r in (state.get("review") or {}).get("reviews", []) if isinstance(r, dict)}
    held, decisions, seen = set(state.get("positions") or {}), [], set()
    for x in plan.get("buys") or []:
        if not isinstance(x, dict):
            continue
        s = x.get("symbol")
        if s in seen or s in held:
            problems.append(f"BUY {s}: already held or asked twice")
            continue
        seen.add(s)
        if s not in table:
            problems.append(f"BUY {s}: no features for this market (not allowed, or not looked at)")
            continue
        risk = clamp(x.get("risk_pct"), 0.05, env.max_risk_pct, 0.5)
        d = {"symbol": s, "strategy": str(x.get("strategy") or "agent")[:40], "risk_pct": risk,
             "stop_pct": clamp(x.get("stop_pct"), env.min_stop_pct, env.max_stop_pct, 4.0),
             "target_pct": clamp(x.get("target_pct"), 0.5, 100, 0) if x.get("target_pct") else 0.0,
             "max_hours": clamp(x.get("max_hours"), 0.1, min(env.max_hours, pace.max_hold_hours if pace else
                                                              env.max_hours), 12),
             "trend_exit": bool(x.get("exit_on_trend_turn")),
             "order": "taker" if x.get("order") == "taker" else "maker",
             "conviction": clamp(x.get("conviction"), 0, 1, 0.5), "reason": str(x.get("reason", ""))[:400],
             "cited": x.get("cited", []), "invalidation": str(x.get("invalidation", ""))[:300], "problems": []}
        r = review.get(s) or {}
        if r.get("verdict") == "REJECT":
            decisions.append({**d, "action": "HOLD", "judge": r.get("reason", "")})
            continue
        if r.get("verdict") == "REDUCE":
            d["risk_pct"] = min(risk, clamp(r.get("risk_pct"), 0.05, env.max_risk_pct, risk / 2))
            d["judge"] = r.get("reason", "")
        decisions.append({**d, "action": "BUY"})
    decisions.sort(key=lambda d: -d["conviction"])  # the strongest gets the free cash first
    for x in plan.get("sells") or []:
        if isinstance(x, dict) and x.get("symbol") in held:
            decisions.append({"symbol": x["symbol"], "action": "SELL", "reason": str(x.get("reason", ""))[:300]})
        elif isinstance(x, dict):
            problems.append(f"SELL {x.get('symbol')}: we hold no position there")
    return decisions, problems


def text_of(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    text = str(content)
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def plan_problem(plan: dict) -> str | None:
    """Why a plan does not have the shape code needs, or None if it does."""
    for key in ("buys", "sells"):
        if not isinstance(plan.get(key, []), list):
            return f'"{key}" is not a list'
    if "buys" not in plan and "sells" not in plan:
        return 'no "buys" and no "sells"'
    return None


def final_json(llm, messages: list) -> dict:
    """The JSON plan in the agent's last answer. If it is broken or has the wrong shape, ask once more in JSON mode."""
    last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    try:
        plan = parse_json(text_of(last))
        problem = plan_problem(plan)
    except (LLMError, AttributeError) as error:
        problem = f"not valid JSON ({error})"
    if problem is None:
        return plan
    retry = HumanMessage(f"Your last answer has a problem: {problem}. Give your final decisions again, as one JSON "
                         f"object in exactly this format:\n{FORMAT}")
    clean = [m for m in messages if not (isinstance(m, AIMessage) and m.tool_calls)
             and not isinstance(m, ToolMessage)]
    reply = llm.bind(response_format={"type": "json_object"}).invoke(clean + [retry])
    plan = parse_json(text_of(reply))
    problem = plan_problem(plan)
    if problem:  # still wrong: treat it as a failed AI call, so nothing is bought
        raise LLMError(f"the plan is still unusable: {problem}")
    return plan


def tool_steps(messages: list) -> list[dict]:
    """Every tool call and its result (cut short), for the log."""
    results = {m.tool_call_id: m.content for m in messages if isinstance(m, ToolMessage)}
    return [{"tool": c["name"], "args": c["args"], "result": str(results.get(c["id"], ""))[:600]}
            for m in messages if isinstance(m, AIMessage) for c in (m.tool_calls or [])]


def largest_prompt(messages: list) -> int:
    """The largest prompt any AI call of the trader sent, in tokens, as the provider counted it."""
    return max(((getattr(m, "usage_metadata", None) or {}).get("input_tokens", 0) for m in messages), default=0)


def token_count(messages: list) -> int:
    return sum((getattr(m, "usage_metadata", None) or {}).get("total_tokens", 0) for m in messages)


def cached_tokens(messages: list) -> int:
    """Prompt tokens the provider read from its cache (billed at a tenth or less), as it reported them."""
    return sum(((getattr(m, "usage_metadata", None) or {}).get("input_token_details") or {}).get("cache_read", 0)
               or 0 for m in messages)


def cycle_summary(state: State) -> str:
    """One line for the agent's short-term memory."""
    t = time.strftime("%H:%M", time.gmtime(state.get("now", 0)))
    acts = [f"{d['action']} {d['symbol']}" + (f" {d.get('risk_pct')}% risk" if d["action"] == "BUY" else "")
            for d in state.get("decisions", [])]
    plan = state.get("plan") or {}
    eq = (state.get("account") or {}).get("equity")
    return f"{t} UTC equity {eq}: {', '.join(acts) or 'no action'}. {plan.get('approach', '')}"[:400]


def open_memory(data_dir: Path, name: str):
    """The short-term checkpointer and the long-term store, both SQLite files in data/brain/."""
    folder = data_dir / "brain"
    folder.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(folder / f"{name}_checkpoints.sqlite", check_same_thread=False))
    store = SqliteStore(sqlite3.connect(folder / f"{name}_memory.sqlite", check_same_thread=False,
                                        isolation_level=None))
    store.setup()
    return saver, store
