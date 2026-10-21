"""Read live prices on a fixed beat and log every cycle.

Log: data/prices/<UTC date>.jsonl, one JSON line per cycle. A cycle where
Wallex fails is logged too, with the error, and the loop goes on.
"""

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from wx.wallex import fetch_best_prices


def read_prices(symbols: list[str]) -> tuple[dict, dict]:
    """Prices and errors, each keyed by symbol. One bad market never stops the rest."""
    prices, errors = {}, {}
    for symbol in symbols:
        try:
            bid, ask = fetch_best_prices(symbol)
        except Exception as error:  # the loop must survive anything a request throws
            errors[symbol] = f"{type(error).__name__}: {error}"
            continue
        mid = (bid + ask) / 2
        prices[symbol] = {
            "bid": str(bid),
            "ask": str(ask),
            "mid": str(mid),
            "spread_bps": str(((ask - bid) / mid * 10_000).quantize(Decimal("0.01"))),
        }
    return prices, errors


def log_path(data_dir: Path, now: datetime) -> Path:
    return data_dir / "prices" / f"{now:%Y-%m-%d}.jsonl"


def append_log(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def run_cycle(cycle: int, symbols: list[str], data_dir: Path) -> dict:
    now = datetime.now(timezone.utc)
    prices, errors = read_prices(symbols)
    record = {"time": now.isoformat(timespec="seconds"), "cycle": cycle, "prices": prices, "errors": errors}
    append_log(log_path(data_dir, now), record)
    return record


def summary(record: dict) -> str:
    line = f"{record['time']} cycle {record['cycle']}: {len(record['prices'])} prices"
    for symbol, error in record["errors"].items():
        line += f"\n  {symbol} failed: {error}"
    return line


def watch(symbols: list[str], data_dir: Path, interval: int, cycles: int | None = None, sleep=time.sleep) -> None:
    """Run a cycle every `interval` seconds, on the beat (e.g. at :00 each minute).

    Stops after `cycles` cycles, or never if None. Ctrl+C stops it too.
    """
    cycle = 0
    while cycles is None or cycle < cycles:
        cycle += 1
        try:
            print(summary(run_cycle(cycle, symbols, data_dir)), flush=True)
        except Exception as error:  # e.g. the disk is full; try again next beat
            print(f"cycle {cycle} failed: {type(error).__name__}: {error}", flush=True)
        if cycles is None or cycle < cycles:
            sleep(interval - time.time() % interval)
