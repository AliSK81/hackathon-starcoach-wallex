import json

from wx.llm import LLMError, Reply
from wx.replay import BEAT, History, replay_moment, run_replay, sample_times, summary

T0 = 1_700_000_000 - 1_700_000_000 % 3600


def flat_history(price=100.0, hours=800, minutes=3000, after=None):
    """Steady candles up to T0, and optional later candles at another price."""
    hs = [[T0 - (hours - i) * 3600, price, price * 1.001, price * 0.999, price, 1.0] for i in range(hours)]
    ms = [[T0 - (minutes - i) * 60, price, price, price, price, 1.0] for i in range(minutes)]
    if after is not None:
        hs += [[T0 + i * 3600, after, after, after, after, 9.0] for i in range(30)]
        ms += [[T0 + i * 60, after, after, after, after, 9.0] for i in range(30 * 60)]
    return History(hs, ms)


def test_past_features_never_see_later_candles():
    before = flat_history().features_at(T0, 0.2, 0.003)
    with_future = flat_history(after=500.0).features_at(T0, 0.2, 0.003)
    assert before == with_future
    assert before["price"] == 100.0 and before["spread_pct"] == 0.2


def test_moments_are_on_the_beat_repeatable_and_inside_the_window():
    a = sample_times(T0, T0 + 10 * 86400, 20, seed=7)
    assert a == sample_times(T0, T0 + 10 * 86400, 20, seed=7)
    assert a != sample_times(T0, T0 + 10 * 86400, 20, seed=8)
    assert len(set(a)) == 20 and all(t % BEAT == 0 and T0 < t <= T0 + 10 * 86400 for t in a)
    assert len(sample_times(T0, T0 + 3600, 50, seed=7)) == 4


def buy_reply(messages):
    answer = {"market_view": "v", "decisions": [
        {"symbol": "BTCTMN", "action": "BUY", "confidence": 0.7, "reason": "r", "cited": ["rsi14"]}]}
    return Reply(text=json.dumps(answer), model="m1", seconds=1.0)


def test_moment_records_what_happened_next():
    histories = {"BTCTMN": flat_history(after=110.0)}
    result = replay_moment(T0, histories, {"BTCTMN": 0.2}, {"BTCTMN": 0.003}, buy_reply)
    assert result["driver"] == "ai" and result["decisions"][0]["action"] == "BUY"
    # 100 -> 110 is +10%. The cost is 2 x 0.3% fee + 0.2% spread = 0.8%.
    assert result["outcomes"]["BTCTMN"] == {"fwd_24h_pct": 10.0, "net_pct": 9.2}


def test_replay_logs_each_moment_and_survives_ai_failures(tmp_path, capsys):
    calls = []

    def flaky(messages):
        calls.append(1)
        if len(calls) % 2:
            raise LLMError("chat failed: timed out")
        return buy_reply(messages)

    histories = {"BTCTMN": flat_history(after=110.0)}
    log = tmp_path / "replay" / "run.jsonl"
    times = [T0, T0 + 900]
    results = run_replay(times, histories, {"BTCTMN": 0.2}, {"BTCTMN": 0.003}, flaky, log, workers=1)
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2
    assert sorted(r["driver"] for r in results) == ["ai", "fallback"]
    text = summary(results)
    assert "Moments: 2. AI failures: 1." in text
    assert "BUY     1 decisions" in text and "HOLD    1 decisions" in text
    assert "BUYs per market: BTCTMN 1" in text
