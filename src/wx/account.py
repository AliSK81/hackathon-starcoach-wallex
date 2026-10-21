"""Our Wallex account: balances and fee rates.

Free balance = value - locked (research file 05, section 5).
"""

import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def nonzero_balances(balances: dict[str, dict]) -> dict[str, dict]:
    """Assets we hold, with value, locked and free as strings."""
    held = {}
    for asset, info in balances.items():
        value, locked = Decimal(info.get("value") or 0), Decimal(info.get("locked") or 0)
        if value or locked:
            held[asset] = {"value": str(value), "locked": str(locked), "free": str(value - locked)}
    return held


def quote_of(symbol: str) -> str:
    return "USDT" if symbol.endswith("USDT") else "TMN" if symbol.endswith("TMN") else "other"


def fee_groups(fees: dict[str, dict]) -> Counter:
    """How many markets have each (quote, maker rate, taker rate)."""
    return Counter(
        (quote_of(symbol), Decimal(rates["makerFeeRate"]), Decimal(rates["takerFeeRate"]))
        for symbol, rates in fees.items()
    )


def save_account(held: dict, fees: dict, data_dir: Path, now: datetime | None = None) -> Path:
    """Write balances and fees to data/account/<UTC time>.json."""
    now = now or datetime.now(timezone.utc)
    path = data_dir / "account" / f"{now:%Y%m%dT%H%M%SZ}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": now.isoformat(), "balances": held, "fees": fees}), encoding="utf-8")
    return path
