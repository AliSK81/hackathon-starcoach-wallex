"""Run the whole agent graph (brain.py) on past moments, and see how its own trades played out.

At each moment t the graph runs as it would live: the trader with its tools, bull and bear, the judge, the
code envelope. Every tool sees only data that ended by t. The past order book is not saved, so get_orderbook
says so. Memory starts empty at every moment.

Each buy the agent makes is played out with trade(): its entry (maker or taker), its stop, its target, its time
limit or trend-turn exit, and the costs. The account result of the moment is the sum of the trades' results,
weighted by their size. It is compared with doing nothing (0), with the earlier fixed rules (every 12-hour setup
active then, 4 ATR stop, the setup's own exit), and with holding every market for 12 hours.
"""

import json
import pickle
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from langgraph.store.memory import InMemoryStore

from wx.brain import Brain, build_graph
from wx.risk import Account, Ledger
from wx.setups import SHORT_SETUPS
from wx.study import lookup_from
from wx.trades import MAKER_FEE_PCT, TAKER_FEE_PCT, History, exit_rule, trade
from wx.wallex_mcp import candle_bars

START = 5_000_000
HOLD_HOURS = 12


@dataclass
class PaperExecutor:
    """An empty book at one moment: 5,000,000 TMN, nothing held. Buys are only recorded."""
    kind: str = "replay"
    lock: threading.RLock = field(default_factory=threading.RLock)
    bought: list = field(default_factory=list)

    def sync(self, table, now):
        return []

    def account(self, table, now):
        spent = sum(b[2] for b in self.bought)
        return Account(START, START - spent, spent, START, START)

    def positions(self, table, now):
        return {}

    def held(self):
        return {b[0] for b in self.bought}

    def ledger(self):
        return Ledger([], [])

    def buy(self, symbol, setup, f, verdict, now, exits=None):
        self.bought.append((symbol, setup, verdict.tmn, exits or {}))
        return {"placed": True}

    def sell(self, symbol, f, now, reason):
        return []

    def flatten(self, table, now):
        return []

    def drain_closed(self):
        return []


def load_rows(symbols: list[str], data_dir: Path, now: int) -> tuple[list[dict], dict[str, History]]:
    """Features at every past hour, with the whole-market context. Cached for 6 hours (it takes minutes)."""
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


def play(history: History, strategy: str, t: int, f: dict, plan: dict, lookup, symbol: str):
    """How one of the agent's buys played out, with its own exit plan. None if a maker buy never filled."""
    rule = exit_rule(plan.get("max_hours") or HOLD_HOURS, bool(plan.get("trend_exit")))
    return trade(history, strategy, t, f, plan["stop_pct"], "taker" if plan.get("order") == "taker" else "limit",
                 lambda h: lookup(symbol, h), take_profit_pct=plan.get("target_pct") or 0.0, rule=rule)


def rules_result(t: int, rows_at: dict, histories: dict, lookup) -> list[float]:
    """Net % of each trade the earlier fixed rules would have made at t: every active 12-hour setup."""
    out = []
    for s, f in rows_at.items():
        name = next((n for n in SHORT_SETUPS if n in f["setups"]), None)
        if name:
            done = trade(histories[s], name, t, f, 4 * f["atr14_pct"], "limit", lambda h, s=s: lookup(s, h))
            if done is not None:
                out.append(done.net_pct)
    return out


def hold_result(t: int, histories: dict, spreads: dict) -> float:
    moves = []
    for s, h in histories.items():
        a, b = h.close_at(t), h.close_at(t + HOLD_HOURS * 3600)
        if a and b:
            moves.append((b / a - 1) * 100 - MAKER_FEE_PCT - TAKER_FEE_PCT - spreads.get(s, 0.3) / 2)
    return mean(moves) if moves else 0.0


def replay_moment(t: int, rows_at: dict[str, dict], histories: dict[str, History], llm, lookup,
                  spreads: dict) -> dict:
    table = json.loads(json.dumps(rows_at))

    def closes(symbol, hours, now):
        return histories[symbol].hourly_closes(t, hours) if symbol in histories else []

    def candles(symbol, minutes, bars):
        if symbol not in histories:
            return []
        part = histories[symbol].candles(t - (bars + 1) * minutes * 60, t)
        return candle_bars({k: [c[i] for c in part] for i, k in enumerate("tohlcv")}, minutes, bars)

    executor = PaperExecutor()
    brain = Brain(llm=llm, executor=executor, features=lambda: (table, {}),
                  micro=lambda s: {"source": "replay", "error": "the past order book is not saved"},
                  closes=closes, store=InMemoryStore(), log=lambda r: None, candles=candles, clock=lambda: t)
    try:
        state = build_graph(brain).invoke({})
    except Exception as error:  # a failed AI cycle: nothing bought
        state = {"decisions": [], "ai": {"error": f"{type(error).__name__}: {error}"}}
    trades = []
    for symbol, strategy, tmn, plan in executor.bought:
        d = next((x for x in state.get("decisions", []) if x.get("symbol") == symbol), {})
        plan = {**plan, "stop_pct": (d.get("verdict") or {}).get("stop_pct") or d.get("stop_pct") or 4.0}
        done = play(histories[symbol], strategy, t, table[symbol], plan, lookup, symbol)
        trades.append({"symbol": symbol, "strategy": strategy, "tmn": tmn, "risk_pct": d.get("risk_pct"), **plan,
                       "net_pct": round(done.net_pct, 3) if done else None,
                       "exit": done.exit_reason if done else "never filled"})
    account_pct = sum(x["tmn"] * x["net_pct"] for x in trades if x["net_pct"] is not None) / START
    rules = rules_result(t, rows_at, histories, lookup)
    return {"moment": datetime.fromtimestamp(t, UTC).isoformat(timespec="minutes"), "t": t,
            "ai_error": (state.get("ai") or {}).get("error"),
            "tool_calls": len((state.get("ai") or {}).get("steps") or []),
            "plan": state.get("plan"), "review": state.get("review"), "trades": trades,
            "account_pct": round(account_pct, 3), "rules_trades": [round(x, 3) for x in rules],
            "hold_12h_pct": round(hold_result(t, histories, spreads), 3)}


def run(rows: list[dict], histories: dict[str, History], llm, moments: int, days: int, seed: int,
        out: Path, workers: int = 3) -> list[dict]:
    from wx.trades import typical_spreads
    lookup, spreads = lookup_from(rows), typical_spreads(list(histories))
    by_t: dict[int, dict] = {}
    for r in rows:
        by_t.setdefault(r["t"], {})[r["symbol"]] = r["features"]
    end = max(by_t) - 13 * 3600  # leave room for 12-hour trades to play out
    pool = [t for t in by_t if end - days * 86400 <= t <= end]
    times = sorted(random.Random(seed).sample(pool, min(moments, len(pool))))
    out.parent.mkdir(parents=True, exist_ok=True)
    done, lock = [], threading.Lock()

    def one(t):
        rec = replay_moment(t, by_t[t], histories, llm, lookup, spreads)
        with lock:
            done.append(rec)
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
            print(f"  {rec['moment']}: {len(rec['trades'])} buys, account {rec['account_pct']:+.2f}%, "
                  f"hold {rec['hold_12h_pct']:+.2f}%" + (f", AI failed: {rec['ai_error']}" if rec["ai_error"] else ""),
                  flush=True)
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, times))
    return done


def summary(records: list[dict]) -> str:
    if not records:
        return "no moments"
    trades = [x for r in records for x in r["trades"] if x["net_pct"] is not None]
    acc = [r["account_pct"] for r in records]
    rules = [x for r in records for x in r["rules_trades"]]
    hold = [r["hold_12h_pct"] for r in records]
    failed = sum(1 for r in records if r["ai_error"])

    def avg(xs):
        return f"{mean(xs):+.2f}%" if xs else "none"
    return "\n".join([
        f"{len(records)} moments, {failed} with a failed AI cycle, {mean(r['tool_calls'] for r in records):.1f} tool "
        f"calls a moment.",
        f"  agent: {len(trades)} filled buys, {avg([x['net_pct'] for x in trades])} a trade; account result a "
        f"moment {avg(acc)} (up in {sum(a > 0 for a in acc)}, flat in {sum(a == 0 for a in acc)}, down in "
        f"{sum(a < 0 for a in acc)}), worst {min(acc):+.2f}%, best {max(acc):+.2f}%",
        f"  earlier fixed rules at the same moments: {len(rules)} trades, {avg(rules)} a trade",
        f"  hold every market 12 h: {avg(hold)} (worst {min(hold):+.2f}%)",
        "  doing nothing: +0.00%",
    ])
