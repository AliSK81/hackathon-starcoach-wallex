"""A thin client for the public Wallex REST API.

Uses only the standard library. Proxy settings come from the environment.
"""

import json
import urllib.error
from decimal import Decimal
import urllib.parse
import urllib.request

BASE_URL = "https://api.wallex.ir"
TIMEOUT = 30


class WallexError(Exception):
    """Wallex did not answer, or answered with an error."""


def get_raw(path: str, params: dict | None = None) -> dict:
    """GET a path and return the whole JSON reply."""
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "wx"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise WallexError(f"GET {path} failed: {error}") from error


def get_json(path: str, params: dict | None = None) -> dict:
    """GET a path and return the `result` part of the reply."""
    body = get_raw(path, params)
    if not body.get("success"):
        raise WallexError(f"GET {path}: {body.get('code')} {body.get('message')}")
    return body["result"]


def fetch_markets() -> dict[str, dict]:
    """Every spot market, keyed by symbol (e.g. BTCTMN)."""
    return get_json("/v1/markets")["symbols"]


def fetch_candles(symbol: str, resolution: str, start: int, end: int) -> list[list]:
    """Candles between two Unix times, as rows [t, o, h, l, c, v].

    t is an int. Prices and volume stay strings, as Wallex sends them.
    This endpoint has no success/result wrapper. It says "ok" or "no_data".
    """
    params = {"symbol": symbol, "resolution": resolution, "from": start, "to": end}
    body = get_raw("/v1/udf/history", params)
    if body.get("s") == "no_data":
        return []
    if body.get("s") != "ok":
        raise WallexError(f"candles {symbol} {resolution}: {body}")
    columns = [body[k] for k in ("o", "h", "l", "c", "v")]
    return [[int(t), *values] for t, *values in zip(body["t"], *columns)]


def fetch_best_prices(symbol: str) -> tuple[Decimal, Decimal]:
    """Best bid and best ask from the order book.

    The book sends prices as JSON numbers. str() of the float gives back the
    short form Wallex sent, so the Decimal is exact.
    """
    book = get_json("/v1/depth", {"symbol": symbol})
    bids = [Decimal(str(level["price"])) for level in book.get("bid") or []]
    asks = [Decimal(str(level["price"])) for level in book.get("ask") or []]
    if not bids or not asks:
        raise WallexError(f"order book for {symbol} is empty on one side")
    return max(bids), min(asks)
