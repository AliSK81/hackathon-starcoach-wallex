import pytest

from wx import candles, cli
from wx.candles import candle_path, load_candles, update_candles, windows
from wx.wallex import WallexError

DAY = 86400
NOW = 1_800_000_000


def fake_wallex(calls, fail_after=None):
    """A fake fetch_candles that returns one 1-minute candle per minute."""

    def fetch(symbol, resolution, start, end):
        if fail_after is not None and len(calls) >= fail_after:
            raise WallexError("timed out")
        calls.append((start, end))
        first = start - start % 60
        return [[t, "100", "101", "99", str(t), "1"] for t in range(first, end + 1, 60)]

    return fetch


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(candles, "PAUSE", 0)


def test_windows_cover_the_range():
    assert windows(0, 250, 100) == [(0, 100), (100, 200), (200, 250)]
    assert windows(5, 5, 100) == []


def test_first_run_fetches_days_back_and_saves(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(candles, "fetch_candles", fake_wallex(calls))
    added = update_candles("BTCTMN", "1m", tmp_path, days=1, now=NOW)
    saved = load_candles(candle_path(tmp_path, "BTCTMN", "1m"))
    assert added == len(saved) == 1441
    assert calls[0][0] == NOW - DAY
    assert len(calls) == 2  # 1440 minutes in windows of 720


def test_next_run_continues_and_replaces_open_candle(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(candles, "fetch_candles", fake_wallex(calls))
    update_candles("BTCTMN", "1m", tmp_path, days=1, now=NOW)
    last = max(load_candles(candle_path(tmp_path, "BTCTMN", "1m")))
    calls.clear()
    added = update_candles("BTCTMN", "1m", tmp_path, days=1, now=NOW + 600)
    assert calls == [(last, NOW + 600)]
    assert added == 10


def test_failure_keeps_candles_so_far(tmp_path, monkeypatch):
    monkeypatch.setattr(candles, "fetch_candles", fake_wallex([], fail_after=1))
    with pytest.raises(WallexError):
        update_candles("BTCTMN", "1m", tmp_path, days=1, now=NOW)
    saved = load_candles(candle_path(tmp_path, "BTCTMN", "1m"))
    assert len(saved) == 721
    assert min(saved) <= NOW - DAY


def test_more_days_back_fills_older_candles(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(candles, "fetch_candles", fake_wallex(calls))
    update_candles("BTCTMN", "1m", tmp_path, days=1, now=NOW)
    calls.clear()
    added = update_candles("BTCTMN", "1m", tmp_path, days=2, now=NOW)
    saved = load_candles(candle_path(tmp_path, "BTCTMN", "1m"))
    assert added == 1440
    assert min(saved) == NOW - 2 * DAY
    assert list(saved) == sorted(saved) and len(saved) == 2 * 1440 + 1  # no holes
    assert [a for a, b in calls] == [NOW - DAY - 43200, NOW - 2 * DAY]  # newest first


def test_failed_back_fill_leaves_no_hole_and_continues(tmp_path, monkeypatch):
    monkeypatch.setattr(candles, "fetch_candles", fake_wallex([]))
    update_candles("BTCTMN", "1m", tmp_path, days=1, now=NOW)
    # Nothing new forward. The first back-fill window works, the second fails.
    monkeypatch.setattr(candles, "fetch_candles", fake_wallex([], fail_after=1))
    with pytest.raises(WallexError):
        update_candles("BTCTMN", "1m", tmp_path, days=2, now=NOW)
    saved = sorted(load_candles(candle_path(tmp_path, "BTCTMN", "1m")))
    assert all(b - a == 60 for a, b in zip(saved, saved[1:]))
    assert saved[0] == NOW - DAY - 43200
    monkeypatch.setattr(candles, "fetch_candles", fake_wallex([]))
    update_candles("BTCTMN", "1m", tmp_path, days=2, now=NOW)
    assert min(load_candles(candle_path(tmp_path, "BTCTMN", "1m"))) == NOW - 2 * DAY


def test_candles_command_refuses_forbidden_symbol(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "fetch_markets", lambda: {"BTCTMN": {}, "TONTMN": {}})
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    assert cli.main(["candles", "tontmn"]) == 1
    assert "Not allowed or not on Wallex: TONTMN" in capsys.readouterr().out
    assert not (tmp_path / "candles").exists()
