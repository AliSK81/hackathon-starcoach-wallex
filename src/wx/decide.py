"""Ask the AI for one decision per market, check the answer, and log it.

The AI gets the features (with their meanings), our cash and what we hold.
It answers in JSON: BUY, SELL or HOLD per market, with a confidence, a reason
and the feature names it used. Code checks every part. Anything wrong turns
that market into HOLD, and the problem is logged. If the AI fails, every
market is HOLD and the record says driver "fallback".

Log: data/decisions/<UTC date>.jsonl, one JSON line per decision, including
"do nothing". No orders are placed here.
"""

import json
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from wx import __version__
from wx.features import FEATURES
from wx.llm import LLMError, Reply, parse_json
from wx.prices import append_log
from wx.rules import MarketRules

ACTIONS = ("BUY", "SELL", "HOLD")
MAX_REASON = 400
MAX_VIEW = 400

SYSTEM_PROMPT = f"""You are the strategist of a trading bot on the Wallex exchange in Iran.
You decide, for each market you are given, whether to BUY, SELL or HOLD.

How the bot works:
- Spot only, long only. All markets are quoted in Toman (TMN). We can only sell a coin we hold.
- Code has computed every number for you. Do not do maths and do not invent numbers.
  Base each decision on the features you are given, and name the ones you used.
- You do not choose the order size, the price or the stop-loss. Code does that, and code
  can still refuse or shrink your decision.
- Every buy then sell pays round_trip_cost_pct (fees plus spread). A BUY only makes sense
  if you expect the price to rise clearly more than that cost within the next few hours.
- HOLD is the right answer when there is no clear edge. Do not trade just to trade.

Actions:
- BUY: open or add to a position in this market.
- SELL: sell what we hold in this market. Only for markets listed in "held".
- HOLD: do nothing.

Reply with one JSON object and nothing else:
{{
  "market_view": "<the overall picture across markets, at most {MAX_VIEW} characters>",
  "decisions": [
    {{
      "symbol": "<market, e.g. BTCTMN>",
      "action": "BUY" | "SELL" | "HOLD",
      "confidence": <number from 0 to 1>,
      "reason": "<why, at most {MAX_REASON} characters>",
      "cited": ["<feature names you used, e.g. rsi14>"],
      "invalidation": "<what would show this decision was wrong>"
    }}
  ]
}}
Give exactly one decision for every market."""


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


def build_messages(table: dict[str, dict], cash_tmn: int | None, held: dict) -> list[dict]:
    facts = {
        "feature_meanings": FEATURES,
        "cash_tmn": cash_tmn if cash_tmn is not None else "unknown",
        "held": held,
        "markets": table,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
    ]


def hold(symbol: str, problem: str | None = None) -> dict:
    return {"symbol": symbol, "action": "HOLD", "confidence": 0.0, "reason": "", "cited": {},
            "invalidation": "", "problems": [problem] if problem else []}


def check_decision(item: dict, features: dict, held: dict) -> dict:
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
    return {
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "reason": str(item.get("reason") or "")[:MAX_REASON],
        "cited": cited,
        "invalidation": str(item.get("invalidation") or "")[:MAX_REASON],
        "problems": problems,
    }


def check_answer(answer: dict, table: dict[str, dict], held: dict) -> tuple[str, list[dict], list[str]]:
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
        check_decision(by_symbol[s], table[s], held) if s in by_symbol else hold(s, "the AI gave no decision")
        for s in table
    ]
    return str(answer.get("market_view") or "")[:MAX_VIEW], decisions, problems


def decide(table: dict[str, dict], cash_tmn: int | None, held: dict, ask: Callable[[list[dict]], Reply]) -> dict:
    """Ask the AI and return the checked decision record. Never raises for an AI problem."""
    record = {"driver": "ai", "error": None, "ai": None, "market_view": "", "problems": []}
    try:
        reply = ask(build_messages(table, cash_tmn, held))
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
    view, decisions, problems = check_answer(answer, table, held)
    return {**record, "market_view": view, "problems": problems, "decisions": decisions}


def log_decision(data_dir: Path, record: dict, now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    path = data_dir / "decisions" / f"{now:%Y-%m-%d}.jsonl"
    append_log(path, {"time": now.isoformat(timespec="seconds"), **record})
    return path
