from pathlib import Path

from wx.cli import status
from wx.config import KEYS, Settings, read_env_file

ROOT = Path(__file__).parent.parent


def test_missing_env_file_is_fine(tmp_path, monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    settings = Settings.load(tmp_path / "no-such.env")
    assert not any(settings.is_set(name) for name in KEYS)


def test_env_file_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("WALLEX_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text('# comment\nWALLEX_API_KEY="abc"\nLLM_API_KEY=\n', encoding="utf-8")
    settings = Settings.load(env)
    assert settings.get("WALLEX_API_KEY") == "abc"
    assert not settings.is_set("LLM_API_KEY")


def test_status_never_shows_key_values():
    settings = Settings({"WALLEX_API_KEY": "secret-value"})
    text = status(settings) + repr(settings)
    assert "secret-value" not in text
    assert "WALLEX_API_KEY: set" in text


def test_env_example_lists_every_key():
    assert set(read_env_file(ROOT / ".env.example")) == set(KEYS)
