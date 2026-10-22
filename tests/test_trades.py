import pytest

from wx.trades import History, trade

T0 = 1_700_000_000 - 1_700_000_000 % 3600
F = {"price": 100.0, "spread_pct": 0.2, "round_trip_cost_pct": 0.8}  # bid 99.9


def flat(n=3000, price=100.0):
    return [[T0 + i * 60, price, price, price, price, 1.0] for i in range(n)]


def trend(ema_gap_from_hour=None):
    """features_at for the trend setup: the EMA gap turns negative from the given hour on."""
    def at(hour):
        down = ema_gap_from_hour is not None and hour >= T0 + ema_gap_from_hour * 3600
        return {"price": 105.0, "ema20_vs_ema50_pct": -0.1 if down else 0.5}
    return at


def test_stop_on_a_low_and_on_a_gap_open():
    rows = flat()
    rows[100][3] = 94.0  # low touches the 5% stop at 95
    done = trade(History([], rows), "trend", T0, F, 5.0, "taker", trend())
    assert (done.exit_t, done.exit_reason) == (T0 + 6060, "stop")
    assert done.net_pct == pytest.approx(-5.0 - 0.8)
    rows[50][1:5] = [90.0] * 4  # opens below the stop: out at the open
    done = trade(History([], rows), "trend", T0, F, 5.0, "taker", trend())
    assert (done.exit_t, done.net_pct) == (T0 + 3000, pytest.approx(-10.8))


def test_setup_exit_rules():
    h = History([], flat())
    done = trade(h, "trend", T0, F, 5.0, "taker", trend(ema_gap_from_hour=3))
    assert (done.exit_t, done.exit_reason) == (T0 + 3 * 3600, "rule")
    assert done.net_pct == pytest.approx(5.0 - 0.8)  # sold at the hour's price, 105
    done = trade(h, "oversold", T0, F, 5.0, "taker", lambda hour: {"price": 101.0})
    assert done.exit_t == T0 + 24 * 3600  # mean reversion: out after a day


def test_trade_runs_to_the_end_of_the_data_or_stays_open():
    h = History([], flat(600))
    done = trade(h, "trend", T0, F, 5.0, "taker", trend())
    assert (done.exit_t, done.exit_reason) == (T0 + 600 * 60, "end of data")
    still = trade(h, "trend", T0, F, 5.0, "taker", trend(), now=T0 + 7200)
    assert (still.exit_t, still.net_pct, still.entry) == (None, None, 100.0)


def test_limit_buy_fills_only_below_the_bid_and_pays_maker_fees():
    rows = flat()
    assert trade(History([], rows), "trend", T0, F, 5.0, "limit", trend()) is None
    rows[10][3] = 99.8  # trades below the bid in minute 10
    done = trade(History([], rows), "trend", T0, F, 5.0, "limit", trend(ema_gap_from_hour=2))
    assert (done.entry_t, done.entry, done.exit_t) == (T0 + 660, pytest.approx(99.9), T0 + 7200)
    assert done.net_pct == pytest.approx((105 / 99.9 - 1) * 100 - 0.5)  # maker fee in and out
    rows[200][3] = 90.0  # now a stop: maker in, taker plus half the spread out
    done = trade(History([], rows), "trend", T0, F, 5.0, "limit", trend())
    assert done.exit_reason == "stop"
    assert done.net_pct == pytest.approx(-5.0 - 0.25 - 0.3 - 0.1)
    waiting = trade(History([], flat()), "trend", T0, F, 5.0, "limit", trend(), now=T0 + 600)
    assert waiting is None
