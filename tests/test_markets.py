import json
from datetime import datetime, timezone

from wx import cli
from wx.markets import allowed_markets, load_inactive, save_snapshot, top_by_volume
from wx.wallex import WallexError


def market(volume: str | None) -> dict:
    return {"stats": {"24h_tmnVolume": volume}} if volume is not None else {}


MARKETS = {
    "BTCTMN": market("900"),
    "USDTTMN": market("1000"),
    "TONTMN": market("5000"),
    "NEWTMN": market(None),
}


def test_inactive_list_uses_wallex_symbols():
    inactive = load_inactive()
    assert len(inactive) == 345
    assert "TONTMN" in inactive
    assert "BTCTMN" not in inactive
    assert not any("/" in symbol for symbol in inactive)


def test_forbidden_markets_are_removed():
    allowed = allowed_markets(MARKETS, {"TONTMN"})
    assert set(allowed) == {"BTCTMN", "USDTTMN", "NEWTMN"}


def test_top_by_volume_handles_missing_stats():
    assert top_by_volume(MARKETS, 3) == ["TONTMN", "USDTTMN", "BTCTMN"]


def test_snapshot_is_saved(tmp_path):
    now = datetime(2026, 10, 22, 8, 30, tzinfo=timezone.utc)
    path = save_snapshot(MARKETS, tmp_path, now)
    assert path.name == "20261022T083000Z.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["markets"] == MARKETS


def test_markets_command_reports_network_error(monkeypatch, capsys):
    def fail():
        raise WallexError("GET /v1/markets failed: timed out")

    monkeypatch.setattr(cli, "fetch_markets", fail)
    assert cli.main(["markets"]) == 1
    assert "Could not read markets" in capsys.readouterr().out


def test_markets_command_saves_and_reports(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "fetch_markets", lambda: MARKETS)
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    assert cli.main(["markets"]) == 0
    out = capsys.readouterr().out
    assert "Allowed: 3. Forbidden: 1." in out
    assert len(list((tmp_path / "markets").iterdir())) == 1
