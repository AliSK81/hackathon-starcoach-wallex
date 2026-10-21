"""Trading rules per market, and helpers that round orders to fit them.

From /v1/markets. `stepSize` and `tickSize` are numbers of decimals, not
step sizes (DECISIONS F7). Rounding never makes an order worse for us:
quantity rounds down, a buy price rounds down, a sell price rounds up.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal


@dataclass(frozen=True)
class MarketRules:
    symbol: str
    base: str
    quote: str
    qty_decimals: int
    price_decimals: int
    min_qty: Decimal
    min_notional: Decimal
    market_orders: bool  # Wallex flag isMarketTypeEnable. Meaning not confirmed yet.

    @classmethod
    def from_wallex(cls, info: dict) -> "MarketRules":
        return cls(
            symbol=info["symbol"],
            base=info["baseAsset"],
            quote=info["quoteAsset"],
            qty_decimals=int(info["stepSize"]),
            price_decimals=int(info["tickSize"]),
            min_qty=Decimal(str(info["minQty"])),
            min_notional=Decimal(str(info["minNotional"])),
            market_orders=bool(info.get("isMarketTypeEnable")),
        )

    def round_qty(self, qty: Decimal) -> Decimal:
        return qty.quantize(Decimal(1).scaleb(-self.qty_decimals), rounding=ROUND_DOWN)

    def round_price(self, price: Decimal, side: str) -> Decimal:
        rounding = {"BUY": ROUND_DOWN, "SELL": ROUND_UP}[side]
        return price.quantize(Decimal(1).scaleb(-self.price_decimals), rounding=rounding)

    def problems(self, qty: Decimal, price: Decimal) -> list[str]:
        """Why Wallex would refuse this order. Empty means it fits the rules."""
        found = []
        if qty <= 0 or price <= 0:
            found.append("quantity and price must be above zero")
        if qty != self.round_qty(qty):
            found.append(f"quantity has more than {self.qty_decimals} decimals")
        if price != price.quantize(Decimal(1).scaleb(-self.price_decimals), rounding=ROUND_DOWN):
            found.append(f"price has more than {self.price_decimals} decimals")
        if qty < self.min_qty:
            found.append(f"quantity is below {self.min_qty:f}")
        if qty * price < self.min_notional:
            found.append(f"order is below {self.min_notional:f} {self.quote}")
        return found
