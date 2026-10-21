"""Save Wallex candle history to CSV files in data/candles/.

One file per market and size, e.g. BTCTMN_1m.csv. Each run adds new candles
to the file. The newest candle may still be open; the next run replaces it.
"""

import csv
import time
from pathlib import Path

from wx.wallex import WallexError, fetch_candles

# Our name -> (Wallex resolution, seconds per candle).
SIZES = {"1m": ("1", 60), "1h": ("60", 3600)}

# Wallex returns nothing for 1-minute windows longer than about 46 hours.
# 720 candles per request stays well under that.
CANDLES_PER_REQUEST = 720

# Liquid allowed markets from research file 05. See DECISIONS D12.
DEFAULT_SYMBOLS = ("BTCTMN", "ETHTMN", "SOLTMN", "XRPTMN", "PEPETMN", "USDTTMN")

# Seconds to wait between requests, to be polite to Wallex.
PAUSE = 0.2

COLUMNS = ("t", "o", "h", "l", "c", "v")


def candle_path(data_dir: Path, symbol: str, size: str) -> Path:
    return data_dir / "candles" / f"{symbol}_{size}.csv"


def load_candles(path: Path) -> dict[int, list]:
    """Saved candles keyed by time. A missing file gives an empty dict."""
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {int(row["t"]): [int(row["t"])] + [row[k] for k in COLUMNS[1:]] for row in csv.DictReader(f)}


def save_candles(path: Path, candles: dict[int, list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(candles[t] for t in sorted(candles))
    tmp.replace(path)


def windows(start: int, end: int, span: int) -> list[tuple[int, int]]:
    """Split [start, end] into windows of at most `span` seconds."""
    return [(a, min(a + span, end)) for a in range(start, end, span)]


def update_candles(symbol: str, size: str, data_dir: Path, days: int, now: int | None = None) -> int:
    """Fetch new candles and add them to the file. Returns how many are new.

    Gets everything from `days` back up to now that the file doesn't have:
    - new candles after the last saved one, oldest first;
    - older candles before the first saved one (back-fill), newest first.
    Both orders keep the file without holes. If a request fails, the candles
    so far are saved and the error is raised, so the next run continues.
    If Wallex has no data that far back, each run asks for it again.
    """
    resolution, seconds = SIZES[size]
    now = now or int(time.time())
    path = candle_path(data_dir, symbol, size)
    candles = load_candles(path)
    before = len(candles)
    span = CANDLES_PER_REQUEST * seconds
    want_from = now - days * 86400
    if candles:
        todo = windows(max(candles), now, span)
        if want_from < min(candles):
            todo += windows(want_from, min(candles), span)[::-1]
    else:
        todo = windows(want_from, now, span)
    try:
        for i, (a, b) in enumerate(todo):
            if i:
                time.sleep(PAUSE)
            for row in fetch_candles(symbol, resolution, a, b):
                candles[row[0]] = row
    except WallexError:
        save_candles(path, candles)
        raise
    save_candles(path, candles)
    return len(candles) - before
