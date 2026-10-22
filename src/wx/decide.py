"""Ask the AI for one decision per market, check the answer, and log it.

The AI gets the features (with their meanings), our cash and what we hold.
It answers in JSON: BUY, SELL or HOLD per market, with a confidence, a reason
and the feature names it used. A BUY must name a setup that is active for
that market (setups.py). Code checks every part. Anything wrong turns
that market into HOLD, and the problem is logged. If the AI fails, every
market is HOLD and the record says driver "fallback".

Log: data/decisions/<UTC date>.jsonl, one JSON line per decision, including
"do nothing". No orders are placed here.
"""

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from wx import __version__
from wx.features import FEATURES
from wx.llm import LLMError, Reply, parse_json
from wx.prices import append_log
from wx.rules import MarketRules
from wx.setups import SETUPS

ACTIONS = ("BUY", "SELL", "HOLD")
MAX_REASON = 400
MAX_VIEW = 400

HEAD = """You are the strategist of a trading bot on the Wallex exchange in Iran.
You decide, for each market you are given, whether to BUY, SELL or HOLD.

How the bot works:
- Spot only, long only. All markets are quoted in Toman (TMN). We can only sell a coin we hold.
- Code has computed every number for you. Do not do maths and do not invent numbers.
  Base each decision on the features you are given, and name the ones you used.
- You do not choose the order size, the price or the stop-loss. Code does that. Code puts a
  stop-loss below every entry, and can still refuse or shrink your decision.
- We hold a position for about a day (roughly 12 to 48 hours), not for minutes or one hour.
  One hour's move is usually smaller than our costs, so judge each market over the next day.
- Every buy then sell pays round_trip_cost_pct (fees plus spread). Compare it with
  typical_24h_move_pct, the usual size of a one-day move.
"""


@dataclass(frozen=True)
class Role:
    """What the AI is asked to do, which setups it may buy through, and whether it gets tools (agent.py)."""
    text: str
    setups: tuple[str, ...]
    tools: bool = False


# The AI's possible roles. `wx replay --role` compares them (DECISIONS D24).
ROLES = {
    # The AI picks among all active setups (change 13). It made results worse (F20).
    "pick": Role("""
Buy setups:
- Code checks fixed buy setups on every market. The ones that hold now are in the "setups"
  feature, and setup_meanings says what each one is.
- You may only BUY a market through one of its active setups, and you must name it.
- Your job is to judge each active setup: take it, or skip it. Take it when the other features
  support it and the likely gain over the next day beats round_trip_cost_pct. Skip it when they
  warn against it, and say which features warn. A market with no active setup is HOLD.
""", tuple(SETUPS)),
    # The AI sees each setup's past record, and takes a setup unless it finds a specific warning.
    "informed": Role("""
Buy setups:
- Code checks fixed buy setups on every market. The ones that hold now are in the "setups"
  feature, and setup_meanings says what each one is.
- setup_history gives each setup's past results on these markets, using only data from before
  now: how many entries, the average result after costs and the stop, and how often it made
  money. Weigh it. A setup with a good record has earned trust. A setup with a poor record
  needs clear extra support from the features.
- The default is to BUY an active setup. Skip it only when you can name a specific warning in
  the features, and say which features warn.
- You may only BUY a market through one of its active setups, and you must name it. A market
  with no active setup is HOLD.
""", tuple(SETUPS)),
    # Code buys through the trend setup. The AI may only stop a buy, for a specific danger (D29).
    "veto": Role("""
Buy setups:
- Code buys a market when its trend setup is active (see the "setups" feature and
  setup_meanings). Other setups in the "setups" feature are for information only.
- Your job is to veto. For each market where trend is active, answer BUY to let the buy go
  ahead, or HOLD to stop it. Stop it only for a specific danger you can point to in the
  features, for example: the move is already very stretched (RSI far above 70, the price far
  above its averages), so a normal pullback would hit the stop; the market is illiquid (many
  zero-volume hours, a wide spread); or the data looks broken. A strong trend alone is not a
  reason to stop.
- For a BUY, name the setup. Every other market is HOLD.
- Code already sells when the trend turns or the stop is hit. Say SELL for a market we hold
  only for a serious danger you can name.
""", ("trend",)),
}
# The veto role with tools: the AI can look closer before it lets a buy go ahead or stops it.
AGENT_TEXT = """- You have tools. Before deciding on a candidate, look closer where it helps: the shape of
  its last hours (get_hourly_closes), other markets such as BTCTMN for the whole market
  (get_market, get_hourly_closes), and how the setup did before (get_setup_record).
"""
ROLES["agent"] = Role(ROLES["veto"].text + AGENT_TEXT, ROLES["veto"].setups, tools=True)
DEFAULT_ROLE = "pick"

TAIL = f"""
Actions:
- BUY: open or add to a position, through an active setup of this market.
- SELL: sell what we hold in this market. Only for markets listed in "held".
- HOLD: do nothing.

Reply with one JSON object and nothing else:
{{
  "market_view": "<the overall picture across markets, at most {MAX_VIEW} characters>",
  "decisions": [
    {{
      "symbol": "<market, e.g. BTCTMN>",
      "action": "BUY" | "SELL" | "HOLD",
      "setup": "<for a BUY: the active setup you take. Otherwise empty>",
      "confidence": <number from 0 to 1>,
      "reason": "<why, at most {MAX_REASON} characters>",
      "cited": ["<feature names you used, e.g. rsi14>"],
      "invalidation": "<what would show this decision was wrong>"
    }}
  ]
}}
Give exactly one decision for every market. Write each market name exactly as given."""


def system_prompt(role: str) -> str:
    return HEAD + ROLES[role].text + TAIL


def code_version() -> str:
    """Package version and git commit, e.g. "0.1.0+82877ed". "+dirty" if files changed."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                timeout=5, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                               text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return __version__
    return f"{__version__}+{commit}{'.dirty' if dirty else ''}"


def holdings(balances: dict[str, dict], rules: dict[str, MarketRules], table: dict[str, dict]):
    """Free Toman, and what we hold in each market worth at least its minimum order.

    Smaller amounts can't be sold on Wallex, so they don't count.
    """
    def free(asset: str) -> Decimal:
        info = balances.get(asset) or {}
        return Decimal(info.get("value") or 0) - Decimal(info.get("locked") or 0)

    held = {}
    for symbol, features in table.items():
        r = rules[symbol]
        qty = free(r.base)
        value = qty * Decimal(str(features["price"]))
        if qty > 0 and value >= r.min_notional:
            held[symbol] = {"qty": str(qty), "value_tmn": int(value)}
    return int(free("TMN")), held


def build_messages(table: dict[str, dict], cash_tmn: int | None, held: dict, role: str = DEFAULT_ROLE,
                   setup_history: dict | None = None) -> list[dict]:
    facts = {
        "feature_meanings": FEATURES,
        "setup_meanings": {name: f"{s.meaning}. Exit: {s.exit_meaning}." for name, s in SETUPS.items()},
        "market_names": list(table),
        "cash_tmn": cash_tmn if cash_tmn is not None else "unknown",
        "held": held,
        "markets": table,
    }
    if setup_history is not None:
        facts["setup_history"] = setup_history
    return [
        {"role": "system", "content": system_prompt(role)},
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
    ]


def hold(symbol: str, problem: str | None = None) -> dict:
    return {"symbol": symbol, "action": "HOLD", "confidence": 0.0, "setup": "", "reason": "", "cited": {},
            "invalidation": "", "problems": [problem] if problem else []}


def check_decision(item: dict, features: dict, held: dict, allowed: tuple[str, ...] = tuple(SETUPS)) -> dict:
    """One checked decision. Anything wrong makes it HOLD, with the reasons in problems."""
    symbol = item["symbol"]
    problems = []
    action = str(item.get("action", "")).upper()
    if action not in ACTIONS:
        problems.append(f"unknown action {item.get('action')!r}")
        action = "HOLD"
    try:
        confidence = float(item.get("confidence"))
    except (TypeError, ValueError):
        confidence = None
    if confidence is None or not 0 <= confidence <= 1:
        problems.append(f"confidence {item.get('confidence')!r} is not a number from 0 to 1")
        confidence, action = 0.0, "HOLD"
    names = [str(n) for n in item.get("cited")] if isinstance(item.get("cited"), list) else []
    unknown = [n for n in names if n not in FEATURES]
    if unknown:
        problems.append(f"cited unknown features: {', '.join(unknown)}")
    cited = {n: features[n] for n in names if n in FEATURES}
    if action == "SELL" and symbol not in held:
        problems.append("SELL but we hold nothing to sell here")
        action = "HOLD"
    if action != "HOLD" and not cited:
        problems.append(f"{action} without any known feature cited")
        action = "HOLD"
    setup = str(item.get("setup") or "")
    usable = [s for s in features.get("setups", []) if s in allowed]
    if action == "BUY" and setup not in usable:
        problems.append(f"BUY through setup {setup!r}, which is not active here "
                        f"(active and allowed: {', '.join(usable) or 'none'})")
        action = "HOLD"
    return {
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "setup": setup if action == "BUY" else "",
        "reason": str(item.get("reason") or "")[:MAX_REASON],
        "cited": cited,
        "invalidation": str(item.get("invalidation") or "")[:MAX_REASON],
        "problems": problems,
    }


def check_answer(answer: dict, table: dict[str, dict], held: dict,
                 allowed: tuple[str, ...] = tuple(SETUPS)) -> tuple[str, list[dict], list[str]]:
    """Market view, one checked decision per market (in table order), and answer-level problems."""
    problems = []
    items = answer.get("decisions")
    if not isinstance(items, list):
        problems.append("no decisions list in the answer")
        items = []
    by_symbol = {}
    for item in items:
        symbol = item.get("symbol") if isinstance(item, dict) else None
        if symbol not in table:
            problems.append(f"decision for a market we did not ask about: {symbol!r}")
        elif symbol in by_symbol:
            problems.append(f"two decisions for {symbol}, kept the first")
        else:
            by_symbol[symbol] = item
    decisions = [
        check_decision(by_symbol[s], table[s], held, allowed) if s in by_symbol else hold(s, "the AI gave no decision")
        for s in table
    ]
    return str(answer.get("market_view") or "")[:MAX_VIEW], decisions, problems


def decide(table: dict[str, dict], cash_tmn: int | None, held: dict, ask: Callable[[list[dict]], Reply],
           role: str = DEFAULT_ROLE, setup_history: dict | None = None) -> dict:
    """Ask the AI and return the checked decision record. Never raises for an AI problem.

    With no setup this role may take and nothing held, there is nothing to
    decide. The AI is not asked, every market is HOLD, and the record says
    driver "rules".
    """
    allowed = ROLES[role].setups
    record = {"driver": "ai", "role": role, "error": None, "ai": None, "market_view": "", "problems": []}
    if not held and not any(s in allowed for f in table.values() for s in f.get("setups", [])):
        return {**record, "driver": "rules", "decisions": [hold(s, None) for s in table]}
    try:
        reply = ask(build_messages(table, cash_tmn, held, role, setup_history))
    except LLMError as error:
        return {**record, "driver": "fallback", "error": str(error),
                "decisions": [hold(s, "the AI call failed") for s in table]}
    record["ai"] = {"model": reply.model, "seconds": reply.seconds, "usage": reply.usage,
                    "answer": reply.text, "reasoning": reply.reasoning}
    try:
        answer = parse_json(reply.text)
    except LLMError as error:
        return {**record, "driver": "fallback", "error": str(error),
                "decisions": [hold(s, "the AI answer was not valid JSON") for s in table]}
    view, decisions, problems = check_answer(answer, table, held, allowed)
    return {**record, "market_view": view, "problems": problems, "decisions": decisions}


def log_decision(data_dir: Path, record: dict, now: datetime | None = None) -> Path:
    now = now or datetime.now(UTC)
    path = data_dir / "decisions" / f"{now:%Y-%m-%d}.jsonl"
    append_log(path, {"time": now.isoformat(timespec="seconds"), **record})
    return path
