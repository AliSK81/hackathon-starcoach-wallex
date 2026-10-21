import io
import json
import urllib.error
import urllib.request

import pytest

from wx import cli, wallex
from wx.account import fee_groups, nonzero_balances
from wx.config import Settings
from wx.wallex import WallexError, fetch_balances

KEY = "secret-key-value"

BALANCES = {
    "TMN": {"value": "5000000", "locked": "250000"},
    "BTC": {"value": "0", "locked": "0"},
    "ETH": {"value": "0.5", "locked": None},
}

FEES = {
    "BTCTMN": {"makerFeeRate": "0.00250000", "takerFeeRate": "0.00300000"},
    "ETHTMN": {"makerFeeRate": "0.00250000", "takerFeeRate": "0.00300000"},
    "BTCUSDT": {"makerFeeRate": "0.00100000", "takerFeeRate": "0.00130000"},
}


def test_only_held_assets_with_free_amount():
    held = nonzero_balances(BALANCES)
    assert held == {
        "TMN": {"value": "5000000", "locked": "250000", "free": "4750000"},
        "ETH": {"value": "0.5", "locked": "0", "free": "0.5"},
    }


def test_fees_grouped_by_quote():
    groups = fee_groups(FEES)
    assert sorted((q, str(m), str(t), n) for (q, m, t), n in groups.items()) == [
        ("TMN", "0.00250000", "0.00300000", 2),
        ("USDT", "0.00100000", "0.00130000", 1),
    ]


def test_key_goes_in_header_only(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"], seen["key"] = request.full_url, request.get_header("X-api-key")
        return io.BytesIO(json.dumps({"success": True, "result": {"balances": {}}}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    fetch_balances(KEY)
    assert seen["key"] == KEY
    assert KEY not in seen["url"]


def test_fees_drop_entries_that_are_not_markets(monkeypatch):
    reply = {**FEES, "default": [], "metaData": {"levels": [0, 100000000]}}
    monkeypatch.setattr(wallex, "get_json", lambda path, params=None, api_key=None: reply)
    assert wallex.fetch_fees(KEY) == FEES


def test_http_error_shows_wallex_code_not_key(monkeypatch):
    body = io.BytesIO(b'{"code": 1201, "message": "invalid API key format", "success": false}')

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(WallexError) as error:
        wallex.fetch_balances(KEY)
    assert "HTTP 401 1201 invalid API key format" in str(error.value)
    assert KEY not in str(error.value)


def test_account_command_needs_key(capsys):
    assert cli.run_account(Settings({})) == 1
    assert "WALLEX_API_KEY is missing" in capsys.readouterr().out


def test_account_command_reports_and_saves(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "fetch_balances", lambda key: BALANCES)
    monkeypatch.setattr(cli, "fetch_fees", lambda key: FEES)
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    assert cli.run_account(Settings({"WALLEX_API_KEY": KEY})) == 0
    out = capsys.readouterr().out
    assert "TMN   markets: 0.25% / 0.30%  (2 markets)" in out
    assert "USDT  markets: 0.10% / 0.13%  (1 markets)" in out
    assert KEY not in out
    saved = next((tmp_path / "account").iterdir()).read_text(encoding="utf-8")
    assert KEY not in saved
