"""`wx agent`: run the agent graph (brain.py) on a beat, with a guard loop between cycles.

- Every `interval` seconds (default 900): one graph cycle. Features, the AI analyst
  and risk officer, the code gate, orders, lessons, the log.
- Every minute, in its own thread: the guard. Stops on the live price, sells that
  did not fill, buys that waited too long, and selling everything before the end.
- `--shadow` trades a fake book. `--live` places real orders on Wallex.
- `--end-at` is when trading ends (UTC). New buys stop 3 hours before it, and
  everything is sold into Toman 30 minutes before it.
"""

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from wx.brain import Brain, build_graph, open_memory
from wx.candles import candle_path, load_candles
from wx.config import Settings
from wx.cycle import collect_features
from wx.decide import code_version, log_decision
from wx.features import HOUR, add_context, closed_bars
from wx.risk import Limits
from wx.wallex_mcp import WallexMCP, microstructure

GUARD_EVERY = 60


def chat_model(settings: Settings):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=settings.get("LLM_MODEL"), base_url=settings.get("LLM_BASE_URL"),
                      api_key=settings.get("LLM_API_KEY"), temperature=0, timeout=180, max_retries=2)


def make_brain(markets: dict[str, dict], settings: Settings, data_dir: Path, executor, end_at: int | None,
               store, officer: bool = True) -> Brain:
    mcp = WallexMCP()

    def features():
        table, errors = collect_features(markets, settings, data_dir)
        return add_context(table), errors

    def closes(symbol: str, hours: int, now: int) -> list[float]:
        bars = closed_bars(load_candles(candle_path(data_dir, symbol, "1h")), HOUR, now)
        return [b[4] for b in bars[-hours:]]

    def log(record: dict) -> None:
        log_decision(data_dir, {"version": code_version(), **record})

    return Brain(llm=chat_model(settings), executor=executor, features=features,
                 micro=lambda s: microstructure(s, mcp), closes=closes, store=store, log=log, end_at=end_at,
                 limits=Limits(), officer=officer)


def report(state: dict) -> str:
    """One cycle in a few lines, for the console."""
    lines = []
    ai = state.get("ai") or {}
    if ai:
        lines.append(f"Analyst: {ai.get('seconds')} s, {len(ai.get('steps') or [])} tool calls, "
                     f"{ai.get('tokens')} tokens." + (f" Failed: {ai['error']}" if ai.get("error") else ""))
    plan = state.get("plan") or {}
    if plan.get("market_view"):
        lines.append(f"View: {plan['market_view']}")
    if not state.get("candidates") and not state.get("positions"):
        lines.append("No candidate and nothing held: the AI was not asked.")
    for d in state.get("decisions", []):
        v = d.get("verdict") or {}
        lines.append(f"  {d['symbol']:<9} {d['action']:<4} {d.get('setup', '')} conv {d.get('conviction', '')} "
                     f"{d.get('veto', '')} {v.get('reason', '')} {v.get('tmn') or ''}  {d.get('reason', '')[:120]}")
        for p in d.get("problems", []):
            lines.append(f"            problem: {p}")
    for o in state.get("orders", []):
        lines.append(f"  order: {o}")
    for c in state.get("closed", []):
        lines.append(f"  closed: {c['symbol']} {c.get('net_pct')}% ({c.get('reason')})")
    for p in state.get("problems", []):
        lines.append(f"Problem: {p}")
    acc = state.get("account") or {}
    lines.append(f"Equity {acc.get('equity'):,} TMN, cash {acc.get('cash'):,}, hours left {state.get('hours_left')}"
                 if acc.get("equity") is not None else "No account.")
    return "\n".join(lines)


def guard_loop(executor, stop: threading.Event) -> None:
    while not stop.wait(GUARD_EVERY - time.time() % GUARD_EVERY):
        try:
            with executor.lock:
                for c in executor.guard(int(time.time())):
                    print(f"[guard] closed {c['symbol']} {c.get('net_pct')}% ({c.get('reason')})", flush=True)
        except Exception as error:  # the guard must never die
            print(f"[guard] failed: {type(error).__name__}: {error}", flush=True)


def run(brain: Brain, data_dir: Path, thread: str, interval: int, cycles: int | None, saver) -> int:
    graph = build_graph(brain, saver)
    config = {"configurable": {"thread_id": thread}}
    stop = threading.Event()
    threading.Thread(target=guard_loop, args=(brain.executor, stop), daemon=True).start()
    cycle = 0
    try:
        while cycles is None or cycle < cycles:
            cycle += 1
            print(f"--- cycle {cycle} at {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC", flush=True)
            try:
                state = graph.invoke({}, config)
                print(report(state), flush=True)
            except Exception as error:  # log it and go on at the next beat
                log_decision(data_dir, {"cycle": cycle, "version": code_version(), "role": "brain",
                                        "error": f"{type(error).__name__}: {error}"})
                print(f"cycle {cycle} failed: {type(error).__name__}: {error}", flush=True)
            if brain.end_at is not None and time.time() > brain.end_at:
                print("Trading has ended.")
                break
            if cycles is None or cycle < cycles:
                time.sleep(interval - time.time() % interval)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        stop.set()
    return 0


def parse_end(text: str | None) -> int | None:
    """An ISO time like 2026-10-23T00:30 (UTC unless it names a zone) as Unix seconds."""
    if not text:
        return None
    t = datetime.fromisoformat(text)
    return int((t if t.tzinfo else t.replace(tzinfo=UTC)).timestamp())


__all__ = ["make_brain", "open_memory", "parse_end", "run"]
