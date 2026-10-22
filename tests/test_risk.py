import pytest

from wx.backtest import START_TMN, run, setups_policy
from wx.replay import History
from wx.risk import Account, Limits, check_buy

FEATURES = {"atr14_pct": 1.0, "data_age_min": 1.0}  # stop 4 x 1% = 4% below the entry
FRESH = Account(equity=5_000_000, cash=5_000_000, exposure=0, peak=5_000_000, day_start=5_000_000)


def test_size_risks_a_fixed_share_of_equity():
    # 0.75% of 5,000,000 = 37,500 at risk. With a 4% stop that is 937,500 TMN.
    v = check_buy(FEATURES, FRESH)
    assert (v.tmn, v.stop_pct, v.rule) == (937_500, 4.0, "approved")


def test_limits_shrink_the_buy():
    tight = {"atr14_pct": 0.5, "data_age_min": 1.0}  # 2% stop would want 1,875,000
    assert check_buy(tight, FRESH).rule == "max per coin"
    assert check_buy(tight, FRESH).tmn == 1_250_000
    busy = Account(5_000_000, 600_000, 2_400_000, 5_000_000, 5_000_000)
    v = check_buy(FEATURES, busy)
    assert (v.tmn, v.rule) == (600_000, "max in coins")
    assert check_buy(FEATURES, FRESH, held_tmn=1_000_000).tmn == 250_000


def test_rejections():
    assert check_buy(FEATURES, Account(5_000_000, 40_000, 0, 5_000_000, 5_000_000)).rule == "free cash"
    assert check_buy(FEATURES, Account(4_890_000, 5e6, 0, 5_000_000, 5_000_000)).rule == "daily loss"
    assert check_buy(FEATURES, Account(4_690_000, 5e6, 0, 5_000_000, 4_700_000)).rule == "drawdown"
    stale = check_buy({"atr14_pct": 1.0, "data_age_min": 30.0}, FRESH)
    assert (stale.tmn, stale.rule) == (0, "stale data")
    assert check_buy(FEATURES, FRESH, limits=Limits(min_order_tmn=1e7)).tmn == 0


def test_backtest_trades_a_setup_and_pays_the_cost():
    t0 = 1_700_000_000 - 1_700_000_000 % 3600
    minutes = [[t0 + i * 60, 100.0, 100.0, 100.0, 100.0 if i < 600 else 110.0, 1.0] for i in range(1500)]
    for m in minutes[600:]:
        m[1:5] = [110.0] * 4
    history = History([], minutes)
    features = {"price": 100.0, "atr14_pct": 1.0, "data_age_min": 1.0, "round_trip_cost_pct": 1.0,
                "setups": ["sharp_drop"]}
    rows = [{"symbol": "BTCTMN", "t": t0, "features": features},
            {"symbol": "BTCTMN", "t": t0 + 3600, "features": {**features, "setups": []}}]
    result = run(rows, {"BTCTMN": history}, setups_policy(("sharp_drop",)))
    [trade] = result.trades
    assert trade.tmn == 937_500 and trade.net_pct == pytest.approx(9.0)  # +10% move, 1% cost
    assert result.final == pytest.approx(START_TMN + 937_500 * 0.09)
    assert run(rows, {"BTCTMN": history}, setups_policy(("breakout",))).trades == []
