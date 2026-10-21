"""A thin client for the Wallex REST API. Read-only for now.

Uses only the standard library. Proxy settings come from the environment.
The API key goes only into the request header. It is never in a URL, an
error message, or a log.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

BASE_URL = "https://api.wallex.ir"
TIMEOUT = 30


class WallexError(Exception):
    """Wallex did not answer, or answered with an error."""


def get_raw(path: str, params: dict | None = None, api_key: str | None = None) -> dict:
    """GET a path and return the whole JSON reply."""
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": "wx"}
    if api_key:
        headers["x-api-key"] = api_key
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        # Wallex puts its error code and message in the body, e.g. 401 code 1201.
        try:
            body = json.loads(error.read())
        except (OSError, json.JSONDecodeError):
            body = {}
        raise WallexError(f"GET {path}: HTTP {error.code} {body.get('code')} {body.get('message')}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise WallexError(f"GET {path} failed: {error}") from error


def get_json(path: str, params: dict | None = None, api_key: str | None = None) -> dict:
    """GET a path and return the `result` part of the reply."""
    body = get_raw(path, params, api_key)
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


def fetch_balances(api_key: str) -> dict[str, dict]:
    """Every asset, keyed by name (e.g. TMN). `value` is the total, `locked` is in orders."""
    return get_json("/v1/account/balances", api_key=api_key)["balances"]


def fetch_fees(api_key: str) -> dict[str, dict]:
    """Fee rates keyed by symbol, e.g. {"makerFeeRate": "0.0025", "takerFeeRate": "0.003"}.

    Wallex also sends entries that are not markets ("default", "metaData" with
    volume tiers). Only entries with both rates are kept.
    """
    fees = get_json("/v1/account/fee", api_key=api_key)
    return {
        symbol: rates
        for symbol, rates in fees.items()
        if isinstance(rates, dict) and "makerFeeRate" in rates and "takerFeeRate" in rates
    }
