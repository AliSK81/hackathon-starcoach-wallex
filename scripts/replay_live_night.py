"""Replay the current agent (code, prompts, owner note, AI model) on the live night, hour by hour (F83).

For each hour since the live start, the agent graph runs on the market features the live agent saw then (from
data/live/decisions/), with the real time left to the end (14:45 UTC), the USDTTMN halt, and the owner note.
Its tools read only candles that ended by then; the past order book is not saved. Each moment starts from a
fresh 5,000,000 TMN book, so it shows which coins the agent picks and how each pick played out, not one account.

Each buy is played on 1-minute closes: a maker buy fills only if the price traded at its limit within its fill
window; then the stop, the target, the time limit and the sell 30 minutes before the end. Not simulated: the
1-hour trend-turn exit. A trade still open at the end of the saved data is valued at the last price, less the
cost of selling. Costs: maker 0.25% or taker 0.30% in, taker 0.30% out, plus half the spread each way.

    uv run python scripts/replay_live_night.py            (uses the AI in .env)
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from langgraph.store.memory import InMemoryStore

from wx.agent_replay import PaperExecutor
from wx.brain import Brain, build_graph
from wx.config import Settings
from wx.runner import chat_model
from wx.trades import History
from wx.wallex_mcp import candle_bars

DATA = Path("data")
START_T = 1792694827  # 2026-10-22 18:47 UTC, the first live cycle
END_T = int(datetime(2026, 10, 23, 14, 45, tzinfo=UTC).timestamp())
HALT = (int(datetime(2026, 10, 22, 20, 0, tzinfo=UTC).timestamp()), int(datetime(2026, 10, 23, 8, 0, tzinfo=UTC).timestamp()))
OUT = DATA / "replay" / "live_night.jsonl"


def records():
    rows = []
    for f in sorted((DATA / "live" / "decisions").glob("*.jsonl")):
        rows += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("role") == "brain" and r.get("markets") and r.get("now", 0) >= START_T]


def hourly(cycles):
    """The first live cycle in each hour, from the start."""
    out, seen = [], set()
    for r in cycles:
        hour = (r["now"] - START_T) // 3600
        if hour not in seen:
            seen.add(hour)
            out.append(r)
    return out


def owner_note() -> str:
    text = (DATA / "owner_note.txt").read_text(encoding="utf-8")
    return text.replace("about 7.5 hours are left and the goal", "the goal")


def play(h: History, t: int, f: dict, plan: dict, verdict: dict) -> dict:
    spread = (f.get("spread_pct") or 0.2) / 100
    stop_pct = (verdict.get("stop_pct") or plan.get("stop_pct") or 6) / 100
    target = (plan.get("target_pct") or 0) / 100
    fill_s = int(plan.get("fill_minutes") or 10) * 60
    last_t = min(t + int((plan.get("max_hours") or 6) * 3600), END_T - 1800)
    mins = [m for m in h.minutes if m[0] >= t]
    if not mins:
        return {"result": None, "exit": "no data"}
    price = f["price"]
    if plan.get("order") == "taker":
        entry, fee_in, t_in = price * (1 + spread / 2), 0.0030, mins[0][0]
    else:
        bid = price * (1 - spread / 2)
        hit = next((m for m in mins if m[0] < t + fill_s and m[3] <= bid), None)
        if hit is None:
            return {"result": None, "exit": "maker buy not filled"}
        entry, fee_in, t_in = bid, 0.0025, hit[0]
    stop, tp = entry * (1 - stop_pct), entry * (1 + target) if target else None
    exit_p, why, end = None, "", t_in
    for m in mins:
        if m[0] <= t_in:
            continue
        end = m[0]
        if m[3] <= stop:
            exit_p, why = stop, "stop"
            break
        if tp and m[2] >= tp:
            exit_p, why = tp, "target"
            break
        if m[0] >= last_t:
            exit_p, why = m[4], "time limit or end of trading"
            break
    if exit_p is None:
        exit_p, why = mins[-1][4], "still open, valued at the last price"
    net = (exit_p * (1 - spread / 2) * (1 - 0.0030)) / (entry * (1 + fee_in)) - 1
    return {"result": round(net * 100, 3), "exit": why, "entry": entry, "held_h": round((end - t_in) / 3600, 1)}


def moment(rec: dict, llm, histories: dict) -> dict:
    t, table = rec["now"], rec["markets"]

    def closes(symbol, hours, now):
        return histories[symbol].hourly_closes(t, hours) if symbol in histories else []

    def candles(symbol, minutes, bars):
        if symbol not in histories:
            return []
        part = histories[symbol].candles(t - (bars + 1) * minutes * 60, t)
        return candle_bars({k: [c[i] for c in part] for i, k in enumerate("tohlcv")}, minutes, bars)

    ex = PaperExecutor()
    brain = Brain(llm=llm, executor=ex, features=lambda: (json.loads(json.dumps(table)), {}),
                  micro=lambda s: {"source": "replay", "error": "the past order book is not saved"},
                  closes=closes, store=InMemoryStore(), log=lambda r: None, end_at=END_T, candles=candles,
                  clock=lambda: t, owner_note=owner_note,
                  market_closes=lambda: {"USDTTMN": HALT[0]} if HALT[0] - 3600 <= t < HALT[1] else {})
    started = time.time()
    try:
        state = build_graph(brain).invoke({})
    except Exception as error:  # noqa: BLE001
        state = {"decisions": [], "ai": {"error": f"{type(error).__name__}: {error}"}}
    buys = []
    for symbol, strategy, tmn, exits in ex.bought:
        d = next((x for x in state.get("decisions", []) if x.get("symbol") == symbol), {})
        out = play(histories[symbol], t, table[symbol], {**exits, "stop_pct": d.get("stop_pct")}, d.get("verdict") or {})
        buys.append({"symbol": symbol, "strategy": strategy, "tmn": tmn, **out})
    account = sum(b["tmn"] * b["result"] for b in buys if b["result"] is not None) / 5_000_000
    return {"moment": rec["time"][:16], "hours_left": round((END_T - t) / 3600, 1), "buys": buys,
            "account_pct": round(account, 3), "ai_error": (state.get("ai") or {}).get("error"),
            "tools": len((state.get("ai") or {}).get("steps") or []), "seconds": round(time.time() - started),
            "approach": (state.get("plan") or {}).get("approach")}


def main():
    settings = Settings.load()
    llm = chat_model(settings, DATA)
    picks = hourly(records())
    symbols = {s for r in picks for s in r["markets"]}
    now = int(time.time())
    histories = {s: History.load(DATA, s, now) for s in symbols}
    print(f"{len(picks)} moments, {len(symbols)} markets, model {settings.get('LLM_MODEL')}", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = []
    with ThreadPoolExecutor(3) as pool:
        for rec in pool.map(lambda r: moment(r, llm, histories), picks):
            done.append(rec)
            with OUT.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
            print(f"{rec['moment'][11:]} ({rec['hours_left']} h left): account {rec['account_pct']:+.2f}%, "
                  + ", ".join(f"{b['symbol']} {b['tmn']:,.0f} {b['result'] if b['result'] is not None else '-'}% "
                              f"({b['exit']})" for b in rec["buys"])
                  + (f" AI failed: {rec['ai_error']}" if rec["ai_error"] else ""), flush=True)
    print("\nsum of moment results:", round(sum(r["account_pct"] for r in done), 2), "% (each moment a fresh book)")


if __name__ == "__main__":
    sys.exit(main())
