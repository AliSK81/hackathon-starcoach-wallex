import json
from decimal import Decimal

from wx import prices
from wx.prices import read_prices, watch
from wx.wallex import WallexError


def read_log(data_dir):
    lines = []
    for path in sorted((data_dir / "prices").glob("*.jsonl")):
        lines += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return lines


def test_prices_have_mid_and_spread(monkeypatch):
    monkeypatch.setattr(prices, "fetch_best_prices", lambda s: (Decimal("99"), Decimal("101")))
    got, errors = read_prices(["BTCTMN"])
    assert errors == {}
    assert got["BTCTMN"] == {"bid": "99", "ask": "101", "mid": "100", "spread_bps": "200.00"}


def test_one_bad_market_does_not_stop_the_others(monkeypatch):
    def fetch(symbol):
        if symbol == "ETHTMN":
            raise WallexError("timed out")
        return Decimal("1.2477"), Decimal("1.2478")

    monkeypatch.setattr(prices, "fetch_best_prices", fetch)
    got, errors = read_prices(["BTCTMN", "ETHTMN"])
    assert list(got) == ["BTCTMN"]
    assert errors == {"ETHTMN": "WallexError: timed out"}


def test_loop_survives_a_failed_cycle_and_logs_it(monkeypatch, tmp_path):
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        if len(calls) <= 2:  # the whole first cycle fails
            raise WallexError("network is down")
        return Decimal("99"), Decimal("101")

    sleeps = []
    monkeypatch.setattr(prices, "fetch_best_prices", fetch)
    watch(["BTCTMN", "ETHTMN"], tmp_path, interval=60, cycles=3, sleep=sleeps.append)

    log = read_log(tmp_path)
    assert [r["cycle"] for r in log] == [1, 2, 3]
    assert set(log[0]["errors"]) == {"BTCTMN", "ETHTMN"} and log[0]["prices"] == {}
    assert set(log[2]["prices"]) == {"BTCTMN", "ETHTMN"} and log[2]["errors"] == {}
    assert len(sleeps) == 2 and all(0 < s <= 60 for s in sleeps)


def test_loop_survives_a_log_write_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(prices, "fetch_best_prices", lambda s: (Decimal("99"), Decimal("101")))

    def broken_disk(path, record):
        raise OSError("disk full")

    monkeypatch.setattr(prices, "append_log", broken_disk)
    watch(["BTCTMN"], tmp_path, interval=60, cycles=2, sleep=lambda s: None)
    out = capsys.readouterr().out
    assert out.count("failed: OSError: disk full") == 2
