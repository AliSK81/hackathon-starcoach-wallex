"""Run the agent graph (brain.py) on past moments, and see how its choices played out.

For each moment t with at least one candidate, the whole graph runs as it would live:
bull and bear, the analyst with its tools, the risk officer, the code gate. Every
tool sees only data that ended by t. The past order book is not saved, so
get_orderbook says so, and the sell_pressure veto can't be used. Memory starts empty.

Then every candidate's trade is played out with trade(): a limit buy at the bid,
the setup's exit, the 4 ATR stop, the costs. We compare the buys the AI let through
(weighted by the size it allowed) with all candidates, which is what the rules
alone would buy.
"""

import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from langgraph.store.memory import InMemoryStore

from wx.brain import Brain, build_graph
from wx.risk import AGENT_LIMITS, Account, Ledger, edge_problem
from wx.setups import SHORT_SETUPS
from wx.study import lookup_from
from wx.trades import History, trade
from wx.wallex_mcp import candle_bars


@dataclass
class PaperExecutor:
    """An empty book at one moment: 5,000,000 TMN, nothing held. Buys are only recorded."""
    kind: str = "replay"
    lock: threading.RLock = field(default_factory=threading.RLock)
    bought: list = field(default_factory=list)

    def sync(self, table, now):
        return []

    def account(self, table, now):
        return Account(5_000_000, 5_000_000 - sum(b[2] for b in self.bought), sum(b[2] for b in self.bought),
                       5_000_000, 5_000_000)

    def positions(self, table, now):
        return {}

    def held(self):
        return {b[0] for b in self.bought}

    def ledger(self):
        return Ledger([], [])

    def buy(self, symbol, setup, f, verdict, now):
        self.bought.append((symbol, setup, verdict.tmn))
        return {"placed": True}

    def sell(self, symbol, f, now, reason):
        return []

    def flatten(self, table, now):
        return []

    def drain_closed(self):
        return []


def load_rows(symbols: list[str], data_dir: Path, now: int) -> tuple[list[dict], dict[str, History]]:
    """Features at every past hour, with the whole-market context. Cached for 6 hours (it takes minutes)."""
    import pickle

    from wx.backtest import with_context
    from wx.study import scan
    from wx.trades import typical_spreads
    histories = {s: History.load(data_dir, s, now) for s in symbols}
    cache = data_dir / f"rows_{'_'.join(symbols)}.pkl"
    if cache.is_file() and cache.stat().st_mtime > now - 6 * 3600:
        return pickle.loads(cache.read_bytes()), histories
    rows = with_context(scan(histories, typical_spreads(symbols), {s: 0.003 for s in symbols}))
    cache.write_bytes(pickle.dumps(rows))
    return rows, histories


def candidate_moments(rows: list[dict], since: int) -> list[int]:
    """Hours since `since` where some market has a 12-hour setup that passes the edge rule."""
    found = set()
    for r in rows:
        f = r["features"]
        if r["t"] >= since and any(s in SHORT_SETUPS for s in f["setups"]) and not edge_problem(f, AGENT_LIMITS):
            found.add(r["t"])
    return sorted(found)


def replay_moment(t: int, rows_at: dict[str, dict], histories: dict[str, History], llm, lookup) -> dict:
    table = json.loads(json.dumps(rows_at))

    def closes(symbol, hours, now):
        return histories[symbol].hourly_closes(t, hours) if symbol in histories else []

    def candles(symbol, minutes, bars):
        if symbol not in histories:
            return []
        part = histories[symbol].candles(t - (bars + 1) * minutes * 60, t)
        raw = {k: [c[i] for c in part] for i, k in enumerate("tohlcv")}
        return candle_bars(raw, minutes, bars)

    logs: list[dict] = []
    executor = PaperExecutor()
    brain = Brain(llm=llm, executor=executor, features=lambda: (table, {}),
                  micro=lambda s: {"source": "replay", "error": "the past order book is not saved"},
                  closes=closes, store=InMemoryStore(), log=logs.append, candles=candles, clock=lambda: t)
    try:
        state = build_graph(brain).invoke({})
    except Exception as error:  # count it as a failed AI cycle: nothing bought
        state = {"decisions": [], "candidates": [], "ai": {"error": f"{type(error).__name__}: {error}"}}
    results = []
    for d in state.get("decisions", []):
        if d.get("action") not in ("BUY", "HOLD") or "setup" not in d:
            continue
        f = table[d["symbol"]]
        done = trade(histories[d["symbol"]], d["setup"], t, f, AGENT_LIMITS.stop_atr * f["atr14_pct"], "limit",
                     lambda h, s=d["symbol"]: lookup(s, h))
        tmn = (d.get("verdict") or {}).get("tmn") or 0
        results.append({"symbol": d["symbol"], "setup": d["setup"], "grade": d.get("grade"),
                        "ai": d["action"], "veto": d.get("veto", ""), "conviction": d.get("conviction"),
                        "officer": d.get("officer", ""), "tmn": tmn,
                        "filled": done is not None, "net_pct": round(done.net_pct, 3) if done else None,
                        "exit": done.exit_reason if done else "never filled"})
    return {"moment": datetime.fromtimestamp(t, UTC).isoformat(timespec="minutes"), "t": t,
            "ai_error": (state.get("ai") or {}).get("error"),
            "tool_calls": len((state.get("ai") or {}).get("steps") or []),
            "plan": state.get("plan"), "bull": state.get("bull"), "bear": state.get("bear"),
            "review": state.get("review"), "results": results}


def run(rows: list[dict], histories: dict[str, History], llm, moments: int, days: int, seed: int,
        out: Path, workers: int = 3) -> list[dict]:
    lookup = lookup_from(rows)
    by_t: dict[int, dict] = {}
    for r in rows:
        by_t.setdefault(r["t"], {})[r["symbol"]] = r["features"]
    end = max(by_t) - 13 * 3600  # leave room for the 12-hour trades to play out
    pool = [t for t in candidate_moments(rows, end - days * 86400) if t <= end]
    times = sorted(random.Random(seed).sample(pool, min(moments, len(pool))))
    out.parent.mkdir(parents=True, exist_ok=True)
    done, lock = [], threading.Lock()

    def one(t):
        rec = replay_moment(t, by_t[t], histories, llm, lookup)
        with lock:
            done.append(rec)
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
            print(f"  {rec['moment']}: {len(rec['results'])} candidates, "
                  f"{sum(r['tmn'] > 0 for r in rec['results'])} bought" + (f", AI failed: {rec['ai_error']}"
                                                                           if rec["ai_error"] else ""), flush=True)
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, times))
    return done


def summary(records: list[dict]) -> str:
    rows = [r for rec in records for r in rec["results"] if r["net_pct"] is not None]
    if not rows:
        return "no filled candidates"
    taken = [r for r in rows if r["tmn"] > 0]
    stopped = [r for r in rows if r["ai"] == "HOLD"]
    refused = [r for r in rows if r["ai"] == "BUY" and r["tmn"] == 0]

    def avg(xs):
        return f"{mean(r['net_pct'] for r in xs):+.2f}% ({len(xs)})" if xs else "none"
    weighted = (sum(r["net_pct"] * r["tmn"] for r in taken) / sum(r["tmn"] for r in taken)) if taken else 0.0
    hi = [r for r in taken if (r["conviction"] or 0) >= 0.6]
    lo = [r for r in taken if (r["conviction"] or 0) < 0.6]
    failed = sum(1 for rec in records if rec["ai_error"])
    return "\n".join([
        f"{len(records)} moments, {failed} with a failed AI cycle. Net per trade after costs, (count):",
        f"  every candidate (rules only): {avg(rows)}",
        f"  bought by the agent:          {avg(taken)}, weighted by size {weighted:+.2f}%",
        f"  stopped by an AI veto:        {avg(stopped)}",
        f"  refused by the risk check:    {avg(refused)}",
        f"  agent buys, conviction >= 0.6: {avg(hi)}   below 0.6: {avg(lo)}",
        f"  officer REDUCE: {sum(1 for r in taken if r['officer'])} of {len(taken)} buys",
        f"  tool calls per moment: {mean(rec['tool_calls'] for rec in records):.1f}",
    ])
