import json

from wx import cli, cycle
from wx.beat import every
from wx.config import Settings
from wx.llm import LLMError, Reply

SETTINGS = {"LLM_BASE_URL": "https://ai.example.com/v1", "LLM_MODEL": "m1", "LLM_API_KEY": "sk-secret"}
FEATURES = {"price": 1.0, "rsi14": 25.0, "setups": ["oversold"]}


def test_beat_survives_a_failed_step(capsys):
    done, sleeps = [], []

    def step(cycle):
        if cycle == 2:
            raise OSError("disk full")
        done.append(cycle)

    every(900, step, cycles=3, sleep=sleeps.append)
    assert done == [1, 3]
    assert "cycle 2 failed: OSError: disk full" in capsys.readouterr().out
    assert len(sleeps) == 2 and all(0 < s <= 900 for s in sleeps)


def read_log(data_dir):
    path = next((data_dir / "decisions").glob("*.jsonl"))
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def fake_world(monkeypatch, tmp_path, chat):
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: cls(SETTINGS)))
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli, "pick_markets", lambda symbols: {"BTCTMN": {}})
    monkeypatch.setattr(cli, "every", lambda interval, step, cycles: every(interval, step, cycles, lambda s: None))
    monkeypatch.setattr(cycle, "chat", chat)


def test_run_logs_every_cycle_whatever_happens(monkeypatch, tmp_path, capsys):
    calls = []

    def chat(base_url, model, api_key, messages, json_mode=False):
        calls.append(1)
        if len(calls) == 2:
            raise LLMError("chat failed: timed out")
        answer = {"market_view": "calm", "decisions": [
            {"symbol": "BTCTMN", "action": "HOLD", "confidence": 0.6, "reason": "no edge", "cited": ["rsi14"]}]}
        return Reply(text=json.dumps(answer), model="m1", seconds=1.0)

    features_calls = []

    def collect(markets, settings, data_dir):
        features_calls.append(1)
        if len(features_calls) == 3:
            raise RuntimeError("something unexpected")
        return {"BTCTMN": FEATURES}, {}

    fake_world(monkeypatch, tmp_path, chat)
    monkeypatch.setattr(cycle, "collect_features", collect)
    assert cli.main(["run", "--cycles", "4", "--role", "pick"]) == 0

    log = read_log(tmp_path)
    assert [r["cycle"] for r in log] == [1, 2, 3, 4]
    assert [r["driver"] for r in log] == ["ai", "fallback", "none", "ai"]
    assert log[2]["error"] == "RuntimeError: something unexpected"
    assert all(d["action"] == "HOLD" for r in log for d in r["decisions"])
    assert "cycle 3 failed: RuntimeError" in capsys.readouterr().out
    assert "sk-secret" not in json.dumps(log)


def test_run_needs_the_ai_settings(monkeypatch, capsys):
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: cls({})))
    assert cli.main(["run", "--cycles", "1"]) == 1
    assert "Missing in .env" in capsys.readouterr().out
