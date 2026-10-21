"""A thin client for the public Wallex REST API.

Uses only the standard library. Proxy settings come from the environment.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://api.wallex.ir"
TIMEOUT = 30


class WallexError(Exception):
    """Wallex did not answer, or answered with an error."""


def get_json(path: str, params: dict | None = None) -> dict:
    """GET a path and return the `result` part of the reply."""
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "wx"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise WallexError(f"GET {path} failed: {error}") from error
    if not body.get("success"):
        raise WallexError(f"GET {path}: {body.get('code')} {body.get('message')}")
    return body["result"]


def fetch_markets() -> dict[str, dict]:
    """Every spot market, keyed by symbol (e.g. BTCTMN)."""
    return get_json("/v1/markets")["symbols"]
