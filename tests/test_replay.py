import json

import pytest

from wx.llm import LLMError, Reply
from wx.replay import BEAT, History, pick_times, replay_moment, run_replay, sample_times, summary
from wx.decide import decide
from wx.study import SetupRecord, entries, report, scan

T0 = 1_700_000_000 - 1_700_000_000 % 3600


def history(price=100.0, hours=800, minutes=3000, drop_to=None, after=None):
    """Steady candles up to T0. drop_to: the last day falls to that price. after: later candles at that price."""
    def at(t):
        return drop_to if drop_to is not None and t >= T0 - 86400 else price

    hs = [[t, at(t), at(t) * 1.001, at(t) * 0.999, at(t), 1.0] for t in (T0 - (hours - i) * 3600 for i in range(hours))]
    ms = [[t, at(t), at(t), at(t), at(t), 1.0] for t in (T0 - (minutes - i) * 60 for i in range(minutes))]
    if after is not None:
        hs += [[T0 + i * 3600, after, after, after, after, 9.0] for i in range(30)]
        ms += [[T0 + i * 60, after, after, after, after, 9.0] for i in range(30 * 60)]
    return History(hs, ms)


def test_past_features_never_see_later_candles():
    before = history().features_at(T0, 0.2, 0.003)
    with_future = history(after=500.0).features_at(T0, 0.2, 0.003)
    assert before == with_future
    assert before["price"] == 100.0 and before["spread_pct"] == 0.2


def test_a_sharp_drop_is_an_active_setup():
    f = history(drop_to=90.0).features_at(T0, 0.2, 0.003)
    assert "sharp_drop" in f["setups"]
    assert history().features_at(T0, 0.2, 0.003)["setups"] == []


def test_stop_loss_exit():
    h = History([], [[T0 + i * 60, 100, 100, 100, 100, 1] for i in range(1440)])
    h.minutes[100] = [T0 + 6000, 100, 100, 94, 99, 1]  # low touches 94: a 5% stop at 95 is hit
    assert h.exit_after(T0, 100.0, 5.0) == (pytest.approx(-5.0), T0 + 6060)
    assert h.exit_after(T0, 100.0, 10.0) == (0.0, T0 + 86400)
    assert h.exit_after(T0, 100.0, None) == (0.0, T0 + 86400)
    h.minutes[50] = [T0 + 3000, 90, 90, 90, 90, 1]  # opens below the stop: exit at the open
    assert h.exit_after(T0, 100.0, 5.0) == (pytest.approx(-10.0), T0 + 3000)


def test_moments_are_on_the_beat_repeatable_and_inside_the_window():
    a = sample_times(T0, T0 + 10 * 86400, 20, seed=7)
    assert a == sample_times(T0, T0 + 10 * 86400, 20, seed=7)
    assert a != sample_times(T0, T0 + 10 * 86400, 20, seed=8)
    assert len(set(a)) == 20 and all(t % BEAT == 0 and T0 < t <= T0 + 10 * 86400 for t in a)
    assert len(sample_times(T0, T0 + 3600, 50, seed=7)) == 4
    assert pick_times([5, 1, 3], 2, seed=7) == pick_times([5, 1, 3], 2, seed=7)
    assert pick_times([5, 1, 3], 9, seed=7) == [1, 3, 5]


def buy_reply(messages, *moment):
    answer = {"market_view": "v", "decisions": [
        {"symbol": "BTCTMN", "action": "BUY", "confidence": 0.7, "setup": "sharp_drop", "reason": "r",
         "cited": ["ret_24h_pct"]}]}
    return Reply(text=json.dumps(answer), model="m1", seconds=1.0)


def test_moment_records_what_happened_next():
    histories = {"BTCTMN": history(drop_to=90.0, after=99.0)}
    result = replay_moment(T0, histories, {"BTCTMN": 0.2}, {"BTCTMN": 0.003}, buy_reply)
    assert result["driver"] == "ai" and result["decisions"][0]["action"] == "BUY"
    # 90 -> 99 is +10%. The cost is 2 x 0.3% fee + 0.2% spread = 0.8%. No stop is hit.
    assert result["outcomes"]["BTCTMN"] == {"fwd_24h_pct": 10.0, "net_pct": 9.2, "net_stop_pct": 9.2, "stopped": False}


def test_replay_logs_each_moment_and_survives_ai_failures(tmp_path):
    calls = []

    def flaky(messages, *moment):
        calls.append(1)
        if len(calls) == 2:
            raise LLMError("chat failed: timed out")
        return buy_reply(messages)

    histories = {"BTCTMN": history(drop_to=90.0, after=99.0)}
    log = tmp_path / "replay" / "run.jsonl"
    results = run_replay([T0, T0 + 900], histories, {"BTCTMN": 0.2}, {"BTCTMN": 0.003}, flaky, log, workers=1)
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2
    assert sorted(r["driver"] for r in results) == ["ai", "fallback"]
    text = summary(results)
    assert "Moments: 2. AI failures: 1." in text and "(1 BUY, 0 SELL, 1 HOLD)" in text
    assert "AI buys                               1  average net +9.20%" in text
    assert "Role: pick" in text
    assert "every setup this role may take        2" in text
    assert "of those, the ones the AI skipped     1" in text
    assert "every active setup                    2" in text
    assert "AI buys per setup: sharp_drop 1" in text


def test_study_counts_one_entry_per_market_per_day():
    rows = [{"symbol": "BTCTMN", "t": T0 + h * 3600, "features": {"setups": ["oversold"]}} for h in range(30)]
    rows += [{"symbol": "ETHTMN", "t": T0, "features": {"setups": []}}]
    assert [r["t"] for r in entries(rows, "oversold")] == [T0, T0 + 24 * 3600]
    assert entries(rows, "breakout") == []
    assert len(entries(rows, None)) == 2


def test_setup_record_only_counts_entries_that_are_over():
    histories = {"BTCTMN": history(drop_to=90.0, after=99.0)}
    rows = [{"symbol": "BTCTMN", "t": T0, "features": histories["BTCTMN"].features_at(T0, 0.2, 0.003)}]
    record = SetupRecord(rows, histories)
    assert record.at(T0 + 86399)["sharp_drop"] == {"entries": 0, "average_net_pct": None, "made_money_pct": None}
    assert record.at(T0 + 86400)["sharp_drop"] == {"entries": 1, "average_net_pct": 9.2, "made_money_pct": 100}
    assert record.at(T0 + 86400)["breakout"]["entries"] == 0


def test_informed_role_sends_the_setup_record_to_the_ai():
    seen = {}

    def ask(messages, *moment):
        seen["facts"] = json.loads(messages[1]["content"])
        seen["system"] = messages[0]["content"]
        return buy_reply(messages)

    histories = {"BTCTMN": history(drop_to=90.0, after=99.0)}
    result = replay_moment(T0, histories, {"BTCTMN": 0.2}, {"BTCTMN": 0.003}, ask, "informed",
                           lambda t: {"sharp_drop": {"entries": 3}})
    assert result["role"] == "informed" and result["decisions"][0]["action"] == "BUY"
    assert seen["facts"]["setup_history"] == {"sharp_drop": {"entries": 3}}
    assert "setup_history gives each setup's past results" in seen["system"]


def test_veto_role_may_not_buy_through_a_trend_setup():
    f = history(drop_to=90.0).features_at(T0, 0.2, 0.003)
    trend = {**f, "setups": ["trend_momentum"]}
    answer = {"decisions": [{"symbol": "BTCTMN", "action": "BUY", "confidence": 0.6, "setup": "trend_momentum",
                             "cited": ["rsi14"]}]}
    record = decide({"BTCTMN": trend}, 5_000_000, {}, lambda m: Reply(json.dumps(answer), "m1", 1.0), "veto")
    assert record["driver"] == "rules"  # nothing the veto role may take, so the AI is not asked
    both = {**f, "setups": ["sharp_drop", "trend_momentum"]}
    record = decide({"BTCTMN": both}, 5_000_000, {}, lambda m: Reply(json.dumps(answer), "m1", 1.0), "veto")
    assert record["driver"] == "ai" and record["decisions"][0]["action"] == "HOLD"
    assert "active and allowed: sharp_drop" in record["decisions"][0]["problems"][0]


def test_study_report_runs_on_a_small_history():
    histories = {"BTCTMN": history(hours=780, minutes=60 * 24 * 33, after=100.0)}
    rows = scan(histories, {"BTCTMN": 0.2}, {"BTCTMN": 0.003})
    assert rows and all(r["t"] % 3600 == 0 for r in rows)
    text = report(rows, histories, [4.0])
    assert "sharp_drop: 0 entries" in text and "Every hour, no stop" in text
