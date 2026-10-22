"""`wx agent`: run the agent graph (brain.py) on a beat, with a guard loop between cycles.

- Every `interval` seconds (default 900): one graph cycle. Features, the AI analyst
  and risk officer, the code gate, orders, lessons, the log.
- Every minute, in its own thread: the guard. Stops on the live price, sells that
  did not fill, buys that waited too long, and selling everything before the end.
- `--shadow` trades a fake book. `--live` places real orders on Wallex.
- `--end-at` is when trading ends (UTC). New buys stop 3 hours before it, and
  everything is sold into Toman 30 minutes before it.
- Halt: after HALT_AFTER failed cycles or guard rounds in a row, no new buys until
  a clean cycle. Kill file: if data/KILL exists, the guard sells everything and
  the run stops.
- Live decisions are logged in data/live/decisions/, shadow ones in data/decisions/,
  so the two runs never share one hash chain.
- Every AI call and answer is saved in data/brain/llm_cache.sqlite. With
  WX_LLM_REPLAY=1, saved answers are used again, so a past cycle re-runs exactly.
"""

import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from wx.brain import Brain, build_graph, open_memory
from wx.candles import candle_path, load_candles
from wx.closures import market_closes
from wx.config import Settings
from wx.decide import code_version, log_decision
from wx.features import HOUR, add_context, closed_bars, market_features
from wx.horizon import profile
from wx.llm_cache import SQLiteLLMCache
from wx.markets import tmn_volume
from wx.risk import ENVELOPE
from wx.universe import liquid, tradable_tmn
from wx.wallex import WallexError
from wx.wallex_mcp import WallexMCP, candle_bars, microstructure

GUARD_EVERY = 60
HALT_AFTER = 3


def fixed_temperature(model: str) -> bool:
    """OpenAI's reasoning models (GPT-5, o1, o3, o4) take only their default temperature: sending 0 is an error."""
    name = (model or "").split("/")[-1].lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def chat_model(settings: Settings, data_dir: Path | None = None):
    from langchain_openai import ChatOpenAI
    cache = None
    if data_dir is not None:
        cache = SQLiteLLMCache(data_dir / "brain" / "llm_cache.sqlite", replay=os.environ.get("WX_LLM_REPLAY") == "1")
    model = settings.get("LLM_MODEL")
    return ChatOpenAI(model=model, base_url=settings.get("LLM_BASE_URL"), api_key=settings.get("LLM_API_KEY"),
                      temperature=None if fixed_temperature(model) else 0, timeout=180, max_retries=2, cache=cache)


def parallel_features(markets: dict[str, dict], settings: Settings, data_dir: Path) -> tuple[dict, dict]:
    """Features of many markets at once (sprint decides every 5 minutes: the data must come fast)."""
    from concurrent.futures import ThreadPoolExecutor

    from wx.cycle import taker_fees
    fees = taker_fees(settings)

    def one(symbol):
        try:
            return symbol, market_features(symbol, data_dir, fees.get(symbol)), None
        except Exception as error:  # one bad market never stops the rest
            return symbol, None, str(error)
    table, errors = {}, {}
    with ThreadPoolExecutor(8) as pool:
        for symbol, f, error in pool.map(one, markets):
            if f is not None:
                table[symbol] = f
            else:
                errors[symbol] = error
    return table, errors


def log_dir(data_dir: Path, name: str) -> Path:
    """Where a run's decision log lives: data/live/decisions/ for live, data/decisions/ for shadow."""
    return data_dir / "live" if name == "live" else data_dir


def make_brain(markets: dict[str, dict], settings: Settings, data_dir: Path, executor, end_at: int | None,
               store, officer: bool = True, env=ENVELOPE, universe: bool = False) -> Brain:
    """With universe, the markets are picked again every cycle: every liquid allowed TMN market (universe.py)."""
    mcp = WallexMCP()
    logs = log_dir(data_dir, executor.kind)

    def features():
        pick = markets
        if universe:
            try:
                pick = liquid(tradable_tmn(), executor.held())
            except WallexError as error:  # keep the full list we started with
                print(f"Could not refresh the market list: {error}")
                pick = liquid(markets, executor.held())
            print(f"  {len(pick)} liquid markets: {' '.join(pick)}", flush=True)
        table, errors = parallel_features(pick, settings, data_dir)
        return add_context(table), errors

    def closes(symbol: str, hours: int, now: int) -> list[float]:
        bars = closed_bars(load_candles(candle_path(data_dir, symbol, "1h")), HOUR, now)
        return [b[4] for b in bars[-hours:]]

    def log(record: dict) -> None:
        log_decision(logs, {"version": code_version(), **record}, chain=True)

    def candles(symbol: str, minutes: int, bars: int) -> list:
        now = int(time.time())
        try:
            raw = mcp.call("wallex_basic_candle_history", {"symbol": symbol, "resolution": "1",
                                                            "from": now - (bars + 1) * minutes * 60, "to": now})
        except Exception as error:  # the agent sees the error and can use get_hourly_closes instead
            return [{"error": f"{type(error).__name__}: {error}"[:200]}]
        return candle_bars(raw, minutes, bars)

    def market_list() -> list[dict]:
        """Every allowed TMN market with Wallex's 24h stats, most traded first."""
        try:
            markets_now = tradable_tmn()
        except WallexError as error:
            return [{"error": str(error)}]
        rows = [{"symbol": s, "volume_24h_tmn": round(float(tmn_volume(i))),
                 "change_24h_pct": (i.get("stats") or {}).get("24h_ch")} for s, i in markets_now.items()]
        return sorted(rows, key=lambda r: -r["volume_24h_tmn"])

    def any_market(symbol: str) -> dict:
        if symbol not in markets:  # markets holds every allowed TMN market in universe mode
            raise ValueError(f"{symbol} is not an allowed market")
        return market_features(symbol, data_dir, 0.003)

    return Brain(llm=chat_model(settings, data_dir), executor=executor, features=features,
                 micro=lambda s: microstructure(s, mcp), closes=closes, store=store, log=log, end_at=end_at,
                 env=env, officer=officer, candles=candles, market_list=market_list, market_features=any_market,
                 market_closes=lambda: market_closes(data_dir))


def report(state: dict) -> str:
    """One cycle in a few lines, for the console."""
    lines = []
    ai = state.get("ai") or {}
    if ai:
        lines.append(f"Analyst: {ai.get('seconds')} s, {len(ai.get('steps') or [])} tool calls, "
                     f"{ai.get('tokens')} tokens ({ai.get('cached_tokens', 0)} read from the cache), largest prompt "
                     f"{ai.get('largest_prompt_tokens')}."
                     + (f" Failed: {ai['error']}" if ai.get("error") else ""))
    plan = state.get("plan") or {}
    if plan.get("market_view"):
        lines.append(f"View: {plan['market_view']}")
    if plan.get("approach"):
        lines.append(f"Approach: {plan['approach']}")
    for d in state.get("decisions", []):
        v = d.get("verdict") or {}
        if d["action"] == "SELL":
            lines.append(f"  {d['symbol']:<9} SELL {d.get('reason', '')[:120]}")
            continue
        plan_text = (f"risk {d.get('risk_pct')}% stop {d.get('stop_pct')}% target {d.get('target_pct') or '-'} "
                     f"max {d.get('max_hours')}h {d.get('order')}")
        lines.append(f"  {d['symbol']:<9} {d['action']:<4} {d.get('strategy', '')} {plan_text} -> "
                     f"{v.get('reason', '')} {v.get('tmn') or ''}  {d.get('reason', '')[:100]}"
                     + (f"  judge: {d['judge'][:80]}" if d.get("judge") else ""))
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


def guard_loop(brain: Brain, data_dir: Path, stop: threading.Event) -> None:
    executor, failures = brain.executor, 0
    while not stop.wait(GUARD_EVERY - time.time() % GUARD_EVERY):
        try:
            with executor.lock:
                if (data_dir / "KILL").exists():  # the kill file: sell everything and stop
                    now = int(time.time())
                    done = executor.kill(now) if hasattr(executor, "kill") else executor.flatten({}, now)
                    print(f"[guard] KILL file found, sold everything: {done}", flush=True)
                    stop.set()
                    return
                for c in executor.guard(int(time.time())):
                    print(f"[guard] closed {c['symbol']} {c.get('net_pct')}% ({c.get('reason')})", flush=True)
            failures = 0
        except Exception as error:  # the guard must never die
            failures += 1
            print(f"[guard] failed: {type(error).__name__}: {error}", flush=True)
        brain.halted = brain.halted if failures < HALT_AFTER else True


def run(brain: Brain, data_dir: Path, thread: str, interval: int, cycles: int | None, saver) -> int:
    graph = build_graph(brain, saver)
    config = {"configurable": {"thread_id": thread}}
    stop = threading.Event()
    threading.Thread(target=guard_loop, args=(brain, data_dir, stop), daemon=True).start()
    cycle, failures, logs = 0, 0, log_dir(data_dir, thread)
    try:
        while (cycles is None or cycle < cycles) and not stop.is_set():
            cycle += 1
            print(f"--- cycle {cycle} at {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC", flush=True)
            try:
                state = graph.invoke({}, config)
                print(report(state), flush=True)
                failures, brain.halted = 0, False
            except Exception as error:  # log it and go on at the next beat
                failures += 1
                brain.halted = failures >= HALT_AFTER
                log_decision(logs, {"cycle": cycle, "version": code_version(), "role": "brain",
                                        "error": f"{type(error).__name__}: {error}", "halted": brain.halted},
                             chain=True)
                print(f"cycle {cycle} failed: {type(error).__name__}: {error}"
                      + (" HALTED: no new buys until a clean cycle." if brain.halted else ""), flush=True)
            if brain.end_at is not None and time.time() > brain.end_at:
                print("Trading has ended.")
                break
            if cycles is None or cycle < cycles:
                # The pace follows the time left (horizon.py): every 5 minutes in sprint, slower with more time.
                pace = profile(None if brain.end_at is None else (brain.end_at - time.time()) / 3600).cycle_seconds
                step = min(interval, pace) if interval else pace
                time.sleep(step - time.time() % step)
    except KeyboardInterrupt:
        print("Stopped by Ctrl+C.", flush=True)
    except BaseException as error:  # log why the agent ends, whatever it is, then let the supervisor restart it
        import traceback
        print(f"The agent is stopping: {type(error).__name__}: {error}", flush=True)
        print(traceback.format_exc(), flush=True)
        log_decision(logs, {"role": "brain", "version": code_version(),
                                "error": f"agent stopped: {type(error).__name__}: {error}"}, chain=True)
        raise
    finally:
        stop.set()
        print(f"Agent loop ended at {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC.", flush=True)
    return 0


def parse_end(text: str | None) -> int | None:
    """An ISO time like 2026-10-23T00:30 (UTC unless it names a zone) as Unix seconds."""
    if not text:
        return None
    t = datetime.fromisoformat(text)
    return int((t if t.tzinfo else t.replace(tzinfo=UTC)).timestamp())


__all__ = ["make_brain", "open_memory", "parse_end", "run"]
