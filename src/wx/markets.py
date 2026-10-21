"""Which Wallex markets we may trade, and saved snapshots of them.

Rule (DECISIONS D3): a market is allowed if Wallex lists it now and it is not
in inactive_markets.txt.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from importlib.resources import files
from pathlib import Path


def load_inactive() -> set[str]:
    """Forbidden symbols, written like Wallex writes them (BTC/TMN -> BTCTMN)."""
    text = files("wx").joinpath("inactive_markets.txt").read_text(encoding="utf-8")
    return {line.strip().replace("/", "") for line in text.splitlines() if line.strip()}


def allowed_markets(markets: dict[str, dict], inactive: set[str]) -> dict[str, dict]:
    return {symbol: info for symbol, info in markets.items() if symbol not in inactive}


def tmn_volume(info: dict) -> Decimal:
    """24h volume in Toman. Missing stats count as zero."""
    return Decimal(info.get("stats", {}).get("24h_tmnVolume") or 0)


def top_by_volume(markets: dict[str, dict], n: int) -> list[str]:
    return sorted(markets, key=lambda s: tmn_volume(markets[s]), reverse=True)[:n]


def save_snapshot(markets: dict[str, dict], data_dir: Path, now: datetime | None = None) -> Path:
    """Write the raw market list to data/markets/<UTC time>.json."""
    now = now or datetime.now(timezone.utc)
    path = data_dir / "markets" / f"{now:%Y%m%dT%H%M%SZ}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {"fetched_at": now.isoformat(), "markets": markets}
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return path
