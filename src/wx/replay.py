"""Ask the AI about past moments, and see what happened next.

For each moment t, features are rebuilt from saved candles that ended by t,
as `wx decide` would have seen them then. The past order book is not saved,
so bid and ask are the last close plus and minus half of today's spread. The
AI gets no dates. Then we look up the price 24 hours later.

This tests the AI's judgement only. It is not a full backtest: there are no
positions, sizes or stops.
"""

import bisect
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Callable

from wx.candles import candle_path, load_candles
from wx.decide import decide
from wx.features import HOUR, HOURS_USED, MINUTE, build_features, closed_bars
from wx.llm import Reply

HORIZON = 24 * HOUR
BEAT = 900  # moments fall on the same 15-minute beat as `wx run`
CASH_TMN = 5_000_000

# Stop-loss for the test, in 1h ATRs below the entry. Chosen with `wx study` (DECISIONS D23).
STOP_ATR = 4.0


class History:
    """All saved candles for one market, as floats, oldest first."""

    def __init__(self, hours: list[list[float]], minutes: list[list[float]]):
        self.hours, self.minutes = hours, minutes
        self.hour_starts = [h[0] for h in hours]
        self.minute_starts = [m[0] for m in minutes]

    @classmethod
    def load(cls, data_dir: Path, symbol: str, now: int) -> "History":
        return cls(closed_bars(load_candles(candle_path(data_dir, symbol, "1h")), HOUR, now),
                   closed_bars(load_candles(candle_path(data_dir, symbol, "1m")), MINUTE, now))

    def close_at(self, t: int) -> float | None:
        """Close of the last 1-minute candle that ended by t."""
        i = bisect.bisect_right(self.minute_starts, t - MINUTE)
        return self.minutes[i - 1][4] if i else None

    def exit_after(self, t: int, entry: float, stop_pct: float | None) -> tuple[float, bool]:
        """Price change from entry at t to the exit, in %, and whether the stop was hit.

        The exit is the close 24 hours later, or the stop if a 1-minute low
        reaches it first. If a candle opens below the stop, the exit is that open.
        """
        stop = entry * (1 - stop_pct / 100) if stop_pct else None
        if stop is not None:
            first = bisect.bisect_left(self.minute_starts, t)
            last = bisect.bisect_right(self.minute_starts, t + HORIZON - MINUTE)
            for candle in self.minutes[first:last]:
                if candle[1] <= stop:
                    return (candle[1] / entry - 1) * 100, True
                if candle[3] <= stop:
                    return (stop / entry - 1) * 100, True
        return (self.close_at(t + HORIZON) / entry - 1) * 100, False

    def features_at(self, t: int, spread_pct: float, taker_fee: float | None) -> dict:
        """The features as they were at t. Only candles that ended by t are used."""
        h = bisect.bisect_right(self.hour_starts, t - HOUR)
        m = bisect.bisect_right(self.minute_starts, t - MINUTE)
        hours, minutes = self.hours[max(0, h - HOURS_USED) : h], self.minutes[max(0, m - 5000) : m]
        if not minutes:
            raise ValueError("no 1-minute candles before this moment")
        last = Decimal(str(minutes[-1][4]))
        half = last * Decimal(str(spread_pct)) / 200
        return build_features(hours, minutes, last - half, last + half, t, taker_fee)


def outcome(history: History, t: int, features: dict, stop_atr: float | None = STOP_ATR) -> dict:
    """What a buy at t would have made: held 24 hours, and with the stop-loss. Net is after the cost."""
    cost = features["round_trip_cost_pct"] or 0.0
    fwd, _ = history.exit_after(t, features["price"], None)
    stop_pct = stop_atr * features["atr14_pct"] if stop_atr else None
    with_stop, stopped = history.exit_after(t, features["price"], stop_pct)
    return {"fwd_24h_pct": round(fwd, 2), "net_pct": round(fwd - cost, 2),
            "net_stop_pct": round(with_stop - cost, 2), "stopped": stopped}


def sample_times(start: int, end: int, count: int, seed: int) -> list[int]:
    """`count` different moments on the beat between start and end, picked at random but repeatable."""
    beats = range(start - start % BEAT + BEAT, end - end % BEAT + 1, BEAT)
    return sorted(random.Random(seed).sample(beats, min(count, len(beats))))


def pick_times(candidates: list[int], count: int, seed: int) -> list[int]:
    """`count` of the candidate moments, picked at random but repeatable."""
    return sorted(random.Random(seed).sample(candidates, min(count, len(candidates))))


def replay_moment(t: int, histories: dict[str, History], spreads: dict[str, float],
                  fees: dict[str, float], ask: Callable[[list[dict]], Reply]) -> dict:
    """One past moment: features, the checked AI decision, and what happened in the next 24 hours."""
    table, feature_errors = {}, {}
    for symbol, history in histories.items():
        try:
            table[symbol] = history.features_at(t, spreads[symbol], fees.get(symbol))
        except ValueError as error:
            feature_errors[symbol] = str(error)
    record = decide(table, CASH_TMN, {}, ask) if table else {"driver": "none", "decisions": []}
    outcomes = {symbol: outcome(histories[symbol], t, features) for symbol, features in table.items()}
    moment = datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="minutes")
    return {"moment": moment, "markets": table, "feature_errors": feature_errors, **record, "outcomes": outcomes}


def run_replay(times: list[int], histories: dict[str, History], spreads: dict[str, float],
               fees: dict[str, float], ask: Callable[[list[dict]], Reply], log: Path, workers: int = 4) -> list[dict]:
    """Replay every moment, a few at a time. Each result is logged as soon as it is ready."""
    log.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    results = []

    def one(t: int) -> None:
        result = replay_moment(t, histories, spreads, fees, ask)
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
    """The AI's buys, every active setup, and doing nothing, over the next 24 hours.

    Results use the stop-loss (STOP_ATR) and are net of the round-trip cost.
    """
    rows = [(r, d) for r in results for d in r["decisions"] if d["symbol"] in r["outcomes"]]
    buys = [r["outcomes"][d["symbol"]]["net_stop_pct"] for r, d in rows if d["action"] == "BUY"]
    setups = [(r["outcomes"][d["symbol"]]["net_stop_pct"], d["action"] == "BUY")
              for r, d in rows if r["markets"][d["symbol"]]["setups"]]
    skipped = [net for net, bought in setups if not bought]
    counts = {a: sum(d["action"] == a for _, d in rows) for a in ("BUY", "SELL", "HOLD")}

    def line(name: str, nets: list[float]) -> str:
        if not nets:
            return f"  {name:<34} none"
        return (f"  {name:<34} {len(nets):>4}  average net {mean(nets):+.2f}%, "
                f"net above 0 in {sum(n > 0 for n in nets) / len(nets):.0%}, total {sum(nets):+.1f}%")

    per_setup = {}
    for r, d in rows:
        if d["action"] == "BUY":
            per_setup[d["setup"]] = per_setup.get(d["setup"], 0) + 1
    return "\n".join([
        f"Moments: {len(results)}. AI failures: {sum(r['driver'] == 'fallback' for r in results)}. "
        f"Market decisions: {len(rows)} ({counts['BUY']} BUY, {counts['SELL']} SELL, {counts['HOLD']} HOLD). "
        f"Problems found: {sum(len(d['problems']) for _, d in rows) + sum(len(r.get('problems', [])) for r in results)}.",
        f"Next 24 hours, with a stop {STOP_ATR:g} ATR below the entry, net of the round-trip cost:",
        line("AI buys", buys),
        line("every active setup (no AI)", [net for net, _ in setups]),
        line("setups the AI skipped", skipped),
        "  doing nothing                         0  average net +0.00%",
        "AI buys per setup: " + (", ".join(f"{k} {v}" for k, v in per_setup.items()) or "none"),
    ])
