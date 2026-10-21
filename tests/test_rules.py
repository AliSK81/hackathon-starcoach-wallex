from decimal import Decimal as D

import pytest

from wx import cli
from wx.rules import MarketRules

# Real /v1/markets entries, trimmed (2026-10-22).
BTCTMN = {
    "symbol": "BTCTMN", "baseAsset": "BTC", "quoteAsset": "TMN", "stepSize": 8, "tickSize": 0,
    "minQty": 1e-08, "minNotional": 50000, "isMarketTypeEnable": True,
}
PEPETMN = {
    "symbol": "PEPETMN", "baseAsset": "PEPE", "quoteAsset": "TMN", "stepSize": 0, "tickSize": 4,
    "minQty": 1, "minNotional": 50000, "isMarketTypeEnable": False,
}


@pytest.fixture
def btc():
    return MarketRules.from_wallex(BTCTMN)


@pytest.fixture
def pepe():
    return MarketRules.from_wallex(PEPETMN)


def test_rules_from_wallex(btc, pepe):
    assert (btc.qty_decimals, btc.price_decimals, btc.min_qty, btc.min_notional) == (8, 0, D("0.00000001"), D(50000))
    assert btc.market_orders and not pepe.market_orders


def test_quantity_always_rounds_down(btc, pepe):
    assert btc.round_qty(D("0.123456789")) == D("0.12345678")
    assert pepe.round_qty(D("40000.99")) == D("40000")


def test_price_rounds_in_our_favour(btc, pepe):
    assert btc.round_price(D("22480860330.7"), "BUY") == D("22480860330")
    assert btc.round_price(D("22480860330.2"), "SELL") == D("22480860331")
    assert pepe.round_price(D("1.24785"), "BUY") == D("1.2478")
    assert pepe.round_price(D("1.24781"), "SELL") == D("1.2479")


def test_rounded_order_fits_the_rules(btc):
    qty, price = btc.round_qty(D("0.0001234567891")), btc.round_price(D("22480860330.5"), "BUY")
    assert btc.problems(qty, price) == []


def test_problems_are_found(btc, pepe):
    assert btc.problems(D("0.000000001"), D("22480860330")) == [
        "quantity has more than 8 decimals",
        "quantity is below 0.00000001",
        "order is below 50000 TMN",
    ]
    assert pepe.problems(D("100"), D("1.24785")) == [
        "price has more than 4 decimals",
        "order is below 50000 TMN",
    ]
    assert pepe.problems(D("0"), D("1.2")) == [
        "quantity and price must be above zero",
        "quantity is below 1",
        "order is below 50000 TMN",
    ]


def test_rules_command_prints_table(monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_markets", lambda: {"BTCTMN": BTCTMN, "PEPETMN": PEPETMN})
    assert cli.main(["rules", "btctmn", "pepetmn"]) == 0
    out = capsys.readouterr().out
    assert "0.00000001" in out and "50000 TMN" in out
    assert out.splitlines()[1].endswith("on") and out.splitlines()[2].endswith("off")
