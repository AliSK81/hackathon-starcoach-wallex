from decimal import Decimal

import pytest

from wx import cli
from wx import indicators as ind
from wx.config import Settings
from wx.features import FEATURES, build_features, closed_bars

NOW = 2_000_000_000 - 2_000_000_000 % 3600  # on the hour


def test_ema_starts_from_the_average():
    # Seed (1+2+3)/3 = 2, then alpha 0.5.
    assert ind.ema([1, 2, 3, 4, 5], 3) == [None, None, 2, 3, 4]
    assert ind.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]


def test_rsi_extremes():
    assert ind.rsi(list(range(30)), 14)[-1] == 100.0
    assert ind.rsi(list(range(30, 0, -1)), 14)[-1] == 0.0
    assert ind.rsi(list(range(10)), 14) == [None] * 10


def test_atr_of_a_steady_range():
    highs, lows, closes = [11.0] * 30, [9.0] * 30, [10.0] * 30
    assert ind.atr(highs, lows, closes, 14)[-1] == pytest.approx(2.0)


def test_adx_sees_a_steady_uptrend():
    closes = [100 + i for i in range(60)]
    adx, plus_di, minus_di = ind.adx([c + 1 for c in closes], [c - 1 for c in closes], closes, 14)
    assert adx[26] is None and adx[27] is not None  # first ADX at bar 2n-1
    assert adx[-1] > 90 and plus_di[-1] > minus_di[-1] == 0


def test_zscore_and_percent_rank():
    assert ind.zscore([1, 1, 1, 1], 4) == 0.0
    assert ind.zscore([0, 0, 0, 4], 4) == pytest.approx(3 / 3**0.5)
    assert ind.percent_rank([1, 2, 3, 4, 5], 5) == 1.0
    assert ind.percent_rank([5, 4, 3, 2, 1], 5) == 0.0
    assert ind.percent_rank([1, 2], 5) is None


def hours_uptrend(n=800):
    """Closed hourly candles rising 0.2% an hour, with a jump at the end."""
    rows, price = [], 100.0
    for i in range(n):
        t = NOW - (n - i) * 3600
        price *= 1.002 if i < n - 1 else 1.02
        rows.append([t, price * 0.999, price * 1.001, price * 0.998, price, 10.0])
    return rows


def minutes_flat(price, n=5000):
    return [[NOW - (n - i) * 60, price, price, price, price, 1.0] for i in range(n)]


def test_features_have_every_name_and_see_the_trend():
    hours = hours_uptrend()
    last = hours[-1][4]
    minutes = minutes_flat(last)
    f = build_features(hours, minutes, Decimal(str(last * 0.999)), Decimal(str(last * 1.001)), NOW)
    assert list(f) == list(FEATURES)
    assert f["regime"] == "trend_up"
    assert f["breakout_up"] is True
    assert f["rsi14"] > 70
    assert f["ema20_vs_ema50_pct"] > 0 and f["price_vs_ema200_pct"] > 0
    assert f["typical_24h_move_pct"] == pytest.approx((1.002**24 - 1) * 100, abs=0.01)
    assert f["spread_pct"] == pytest.approx(0.2, abs=0.001)
    assert f["round_trip_cost_pct"] is None
    assert f["ret_15m_pct"] == 0.0
    assert f["data_age_min"] == 1.0


def test_round_trip_cost_is_two_fees_plus_spread():
    hours = hours_uptrend()
    f = build_features(hours, minutes_flat(100.0), Decimal("99.9"), Decimal("100.1"), NOW, taker_fee=0.003)
    assert f["round_trip_cost_pct"] == pytest.approx(0.8)


def test_returns_use_only_candles_that_ended():
    minutes = minutes_flat(100.0)
    minutes[-15] = [*minutes[-15][:4], 50.0, 1.0]  # ended 14 minutes ago
    minutes[-16] = [*minutes[-16][:4], 80.0, 1.0]  # ended exactly 15 minutes ago
    f = build_features(hours_uptrend(), minutes, Decimal("100"), Decimal("100"), NOW)
    assert f["ret_15m_pct"] == 25.0


def test_too_little_history_is_refused():
    with pytest.raises(ValueError):
        build_features(hours_uptrend(100), minutes_flat(100.0), Decimal("1"), Decimal("1"), NOW)


def test_open_candles_are_left_out():
    candles = {NOW - 7200: [NOW - 7200, "1", "2", "0.5", "1.5", "3"], NOW - 3600: [NOW - 3600, "1", "1", "1", "1", "0"],
               NOW: [NOW, "9", "9", "9", "9", "9"]}
    assert closed_bars(candles, 3600, NOW) == [[NOW - 7200, 1, 2, 0.5, 1.5, 3], [NOW - 3600, 1, 1, 1, 1, 0]]


def test_wx_features_prints_a_row_per_feature(monkeypatch, capsys):
    hours = hours_uptrend()
    table = build_features(hours, minutes_flat(hours[-1][4]), Decimal("130"), Decimal("131"), NOW)
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: cls({})))
    monkeypatch.setattr(cli, "pick_markets", lambda symbols: {"BTCTMN": {}, "ETHTMN": {}})

    def fake_market_features(symbol, data_dir, taker_fee=None):
        if symbol == "ETHTMN":
            raise ValueError("need 750 closed 1-hour candles, have 3")
        return table

    monkeypatch.setattr(cli, "market_features", fake_market_features)
    assert cli.main(["features"]) == 1
    out = capsys.readouterr().out
    assert "ETHTMN: failed. need 750" in out
    for name in FEATURES:
        assert name in out
