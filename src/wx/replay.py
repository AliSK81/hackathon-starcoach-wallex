"""Ask the AI about past moments, and see what happened next.

For each moment t, features are rebuilt from saved candles that ended by t,
as `wx decide` would have seen them then. The past order book is not saved,
so bid and ask are the last close plus and minus half of today's spread. The
AI gets no dates. Then each active setup's trade is played out with trade():
its own exit rule, the stop, and the costs.

This tests the AI's judgement only. It is not a full backtest: there are no
positions, sizes or cash limits.
"""

import json
import random
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from wx.decide import DEFAULT_ROLE, ROLES, decide
from wx.features import HOUR
from wx.llm import Reply
from wx.risk import Limits
from wx.trades import History, trade

BEAT = 900  # moments fall on the same 15-minute beat as `wx run`
CASH_TMN = 5_000_000
STOP_ATR = Limits().stop_atr

# lookup(symbol, hour) gives the features of a market at an hour, or None.
Lookup = Callable[[str, int], dict | None]
# ask(messages, t, table) asks the AI about the moment t, whose features are table.
Ask = Callable[[list[dict], int, dict], Reply]


def outcome(history: History, symbol: str, t: int, f: dict, lookup: Lookup) -> dict:
    """What a buy at t would have made: the price 24 hours later, and each active setup's trade, net of costs."""
    later = history.close_at(t + 24 * HOUR)
    by_setup = {}
    for setup in f["setups"]:
        done = trade(history, setup, t, f, STOP_ATR * f["atr14_pct"], "taker", lambda h: lookup(symbol, h))
        by_setup[setup] = round(done.net_pct, 2)
    return {"fwd_24h_pct": round((later / f["price"] - 1) * 100, 2), "by_setup": by_setup}


def sample_times(start: int, end: int, count: int, seed: int) -> list[int]:
    """`count` different moments on the beat between start and end, picked at random but repeatable."""
    beats = range(start - start % BEAT + BEAT, end - end % BEAT + 1, BEAT)
    return sorted(random.Random(seed).sample(beats, min(count, len(beats))))


def pick_times(candidates: list[int], count: int, seed: int) -> list[int]:
    """`count` of the candidate moments, picked at random but repeatable."""
    return sorted(random.Random(seed).sample(candidates, min(count, len(candidates))))


def replay_moment(t: int, histories: dict[str, History], spreads: dict[str, float], fees: dict[str, float],
                  ask: Ask, lookup: Lookup, role: str = DEFAULT_ROLE,
                  setup_history: Callable[[int], dict] | None = None) -> dict:
    """One past moment: features, the checked AI decision, and how each active setup played out.

    setup_history(t) gives each setup's record from before t, for the "informed" role.
    """
    table, feature_errors = {}, {}
    for symbol, history in histories.items():
        try:
            table[symbol] = history.features_at(t, spreads[symbol], fees.get(symbol))
        except ValueError as error:
            feature_errors[symbol] = str(error)
    known = setup_history(t) if setup_history else None
    record = (decide(table, CASH_TMN, {}, lambda messages: ask(messages, t, table), role, known) if table
              else {"driver": "none", "role": role, "decisions": []})
    outcomes = {s: outcome(histories[s], s, t, f, lookup) for s, f in table.items()}
    moment = datetime.fromtimestamp(t, UTC).isoformat(timespec="minutes")
    return {"moment": moment, "markets": table, "feature_errors": feature_errors, **record, "outcomes": outcomes}


def run_replay(times: list[int], histories: dict[str, History], spreads: dict[str, float],
               fees: dict[str, float], ask: Ask, lookup: Lookup, log: Path, workers: int = 3,
               role: str = DEFAULT_ROLE, setup_history: Callable[[int], dict] | None = None) -> list[dict]:
    """Replay every moment, a few at a time. Each result is logged as soon as it is ready."""
    log.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    results = []

    def one(t: int) -> None:
        result = replay_moment(t, histories, spreads, fees, ask, lookup, role, setup_history)
        with lock:
            results.append(result)
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(result) + "\n")
            actions = " ".join(f"{d['symbol'][:-3]}:{d['action']}" for d in result["decisions"])
            print(f"  {len(results):>3}/{len(times)} {result['moment']} {result['driver']:<8} {actions}", flush=True)

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, times))
    return sorted(results, key=lambda r: r["moment"])


def summary(results: list[dict]) -> str:
    """The AI's buys, the setups its role may take, and doing nothing.

    Each buy is played out through its setup: the setup's exit, the stop
    (STOP_ATR), net of the round-trip cost. A market with several setups that
    the AI skipped counts once, through the first of them.
    """
    role = results[0].get("role", DEFAULT_ROLE) if results else DEFAULT_ROLE
    allowed = ROLES[role].setups
    rows = [(r, d) for r in results for d in r["decisions"] if d["symbol"] in r["outcomes"]]
    buys, takeable, skipped, per_setup = [], [], [], {}
    for r, d in rows:
        by_setup = r["outcomes"][d["symbol"]]["by_setup"]
        usable = [s for s in by_setup if s in allowed]
        if d["action"] == "BUY":
            buys.append(by_setup[d["setup"]])
            per_setup[d["setup"]] = per_setup.get(d["setup"], 0) + 1
        if usable:
            net = by_setup[d["setup"]] if d["action"] == "BUY" else by_setup[usable[0]]
            takeable.append(net)
            if d["action"] != "BUY":
                skipped.append(net)
    counts = {a: sum(d["action"] == a for _, d in rows) for a in ("BUY", "SELL", "HOLD")}
    problems = sum(len(d["problems"]) for _, d in rows) + sum(len(r.get("problems", [])) for r in results)

    def line(name: str, nets: list[float]) -> str:
        if not nets:
            return f"  {name:<34} none"
        return (f"  {name:<34} {len(nets):>4}  average net {mean(nets):+.2f}%, "
                f"net above 0 in {sum(n > 0 for n in nets) / len(nets):.0%}, total {sum(nets):+.1f}%")

    return "\n".join([
        f"Role: {role} (may buy through: {', '.join(allowed)}). "
        f"Moments: {len(results)}. AI failures: {sum(r['driver'] == 'fallback' for r in results)}. "
        f"Market decisions: {len(rows)} ({counts['BUY']} BUY, {counts['SELL']} SELL, {counts['HOLD']} HOLD). "
        f"Problems found: {problems}.",
        f"Each buy through its setup's exit, with a stop {STOP_ATR:g} ATR below the entry, net of costs:",
        line("AI buys", buys),
        line("every setup this role may take", takeable),
        line("of those, the ones the AI skipped", skipped),
        "  doing nothing                         0  average net +0.00%",
        "AI buys per setup: " + (", ".join(f"{k} {v}" for k, v in per_setup.items()) or "none"),
    ])
