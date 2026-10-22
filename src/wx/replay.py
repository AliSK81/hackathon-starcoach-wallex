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


def sample_times(start: int, end: int, count: int, seed: int) -> list[int]:
    """`count` different moments on the beat between start and end, picked at random but repeatable."""
    beats = range(start - start % BEAT + BEAT, end - end % BEAT + 1, BEAT)
    return sorted(random.Random(seed).sample(beats, min(count, len(beats))))


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
    outcomes = {}
    for symbol, features in table.items():
        later = histories[symbol].close_at(t + HORIZON)
        fwd = round((later / features["price"] - 1) * 100, 2)
        cost = features["round_trip_cost_pct"] or 0.0
        outcomes[symbol] = {"fwd_24h_pct": fwd, "net_pct": round(fwd - cost, 2)}
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
    """How often the AI bought, and how BUY and HOLD did over the next 24 hours, after costs."""
    rows = [(d, r["outcomes"][d["symbol"]]) for r in results for d in r["decisions"] if d["symbol"] in r["outcomes"]]
    lines = [
        f"Moments: {len(results)}. AI failures: {sum(r['driver'] != 'ai' for r in results)}. "
        f"Market decisions: {len(rows)}. Problems found: {sum(len(d['problems']) for d, _ in rows)}.",
        "Next 24 hours, per action (net = after the round-trip cost):",
    ]
    for action in ("BUY", "SELL", "HOLD"):
        picked = [o for d, o in rows if d["action"] == action]
        if picked:
            lines.append(
                f"  {action:<4} {len(picked):>4} decisions. Average move {mean(o['fwd_24h_pct'] for o in picked):+.2f}%, "
                f"average net {mean(o['net_pct'] for o in picked):+.2f}%, net above 0 in "
                f"{sum(o['net_pct'] > 0 for o in picked) / len(picked):.0%}."
            )
    if rows:
        lines.append(
            f"  If we had bought every market every time: average net {mean(o['net_pct'] for _, o in rows):+.2f}%, "
            f"net above 0 in {sum(o['net_pct'] > 0 for _, o in rows) / len(rows):.0%}."
        )
    buys = {}
    for d, _ in rows:
        if d["action"] == "BUY":
            buys[d["symbol"]] = buys.get(d["symbol"], 0) + 1
    lines.append("BUYs per market: " + (", ".join(f"{s} {n}" for s, n in buys.items()) or "none"))
    return "\n".join(lines)
