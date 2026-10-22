"""Real Wallex orders: place, read, cancel. Standard library only, like wallex.py.

Only code calls this, after the risk check. The AI never does. Every order
carries our own client_id, so after a timeout or a restart we can ask Wallex
what happened to it instead of sending it twice.

Endpoints (research file 05): POST /v1/account/orders, GET and DELETE
/v1/account/orders/{client_id}, GET /v1/account/openOrders.
"""

import json
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

from wx.wallex import BASE_URL, TIMEOUT, WallexError

DONE = ("FILLED", "CANCELED", "CANCELLED", "EXPIRED", "REJECTED")


def new_client_id(tag: str) -> str:
    """Letters, digits and underscores only (the documented charset), at most 32 characters."""
    return f"wx_{tag}_{int(time.time())}_{secrets.token_hex(3)}"[:32]


@dataclass
class OrderState:
    """What Wallex says about one order."""
    client_id: str
    symbol: str
    side: str
    status: str
    active: bool
    price: Decimal
    qty: Decimal
    filled_qty: Decimal  # coin quantity filled so far
    filled_tmn: Decimal  # quote amount filled so far
    fee_coin: Decimal  # fee taken in the coin (the base asset)
    fee_quote: Decimal  # fee taken in the quote asset

    @property
    def done(self) -> bool:
        return not self.active or self.status.upper() in DONE

    @property
    def avg_price(self) -> Decimal | None:
        return self.filled_tmn / self.filled_qty if self.filled_qty else None

    @classmethod
    def from_wallex(cls, r: dict) -> "OrderState":
        def dec(x) -> Decimal:
            try:
                return Decimal(str(x)) if x not in (None, "") else Decimal(0)
            except ArithmeticError:
                return Decimal(0)
        symbol = r.get("symbol", "")
        fee_coin = fee_quote = Decimal(0)
        for fill in r.get("fills") or []:
            fee, asset = dec(fill.get("fee")), str(fill.get("feeAsset") or "")
            if asset and symbol.startswith(asset):
                fee_coin += fee
            else:
                fee_quote += fee
        return cls(
            client_id=r.get("clientOrderId") or r.get("client_id") or "",
            symbol=symbol, side=r.get("side", ""), status=str(r.get("status", "")),
            active=bool(r.get("active", False)), price=dec(r.get("price")), qty=dec(r.get("origQty")),
            filled_qty=dec(r.get("executedQty")), filled_tmn=dec(r.get("executedSum")),
            fee_coin=fee_coin, fee_quote=fee_quote,
        )


class Trader:
    """Wallex spot orders with our key. The key goes only in the header, never in a log or an error."""

    def __init__(self, api_key: str):
        self._key = api_key

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(BASE_URL + path, data=data, method=method, headers={
            "x-api-key": self._key, "Content-Type": "application/json", "User-Agent": "wx"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                reply = json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                reply = json.loads(error.read())
            except (OSError, json.JSONDecodeError):
                reply = {}
            raise WallexError(f"{method} {path}: HTTP {error.code} {reply.get('code')} {reply.get('message')}"
                              ) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise WallexError(f"{method} {path} failed: {error}") from error
        if not reply.get("success", True):
            raise WallexError(f"{method} {path}: {reply.get('code')} {reply.get('message')}")
        return reply.get("result") or {}

    def place(self, symbol: str, side: str, qty: Decimal, price: Decimal, client_id: str,
              kind: str = "LIMIT") -> OrderState:
        """Send one order. On a timeout, ask Wallex for it by client_id before giving up."""
        body = {"symbol": symbol, "side": side, "type": kind, "quantity": f"{qty:f}", "price": f"{price:f}",
                "client_id": client_id}
        try:
            return OrderState.from_wallex(self._call("POST", "/v1/account/orders", body))
        except WallexError as error:
            if "failed" not in str(error):  # Wallex answered with an error: the order was refused
                raise
            found = self.get(client_id)  # the answer was lost: did the order arrive?
            if found is None:
                raise
            return found

    def get(self, client_id: str) -> OrderState | None:
        try:
            return OrderState.from_wallex(self._call("GET", f"/v1/account/orders/{client_id}"))
        except WallexError as error:
            if "HTTP 404" in str(error):
                return None
            raise

    def cancel(self, client_id: str) -> OrderState | None:
        try:
            return OrderState.from_wallex(self._call("DELETE", f"/v1/account/orders/{client_id}"))
        except WallexError as error:
            if "HTTP 404" in str(error):
                return None
            raise

    def open_orders(self) -> list[OrderState]:
        """Every open order. Wallex returns them grouped by market."""
        result = self._call("GET", "/v1/account/openOrders")
        groups = result.values() if isinstance(result, dict) else [result]
        return [OrderState.from_wallex(o) for group in groups if isinstance(group, list) for o in group]
