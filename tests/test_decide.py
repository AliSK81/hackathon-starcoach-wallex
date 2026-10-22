import json
from decimal import Decimal

from wx import cli, cycle
from wx.config import Settings
from wx.decide import build_messages, check_answer, decide, holdings, log_decision
from wx.features import FEATURES
from wx.llm import LLMError, Reply
from wx.rules import MarketRules

KEY = "sk-secret-key-value"


def features(price, rsi=50.0, setups=()):
    f = {name: 0.0 for name in FEATURES}
    f.update(price=price, rsi14=rsi, regime="trend_up", setups=list(setups))
    return f


TABLE = {"BTCTMN": features(22_000_000_000.0, rsi=72.2, setups=["sharp_drop"]), "ETHTMN": features(660_000_000.0)}


def rules(symbol, base):
    return MarketRules(symbol, base, "TMN", 8, 0, Decimal("0.00000001"), Decimal("50000"), True)


RULES = {"BTCTMN": rules("BTCTMN", "BTC"), "ETHTMN": rules("ETHTMN", "ETH")}


def item(symbol="BTCTMN", action="BUY", confidence=0.7, cited=("rsi14",), setup="sharp_drop"):
    return {"symbol": symbol, "action": action, "confidence": confidence, "setup": setup, "reason": "r",
            "cited": list(cited), "invalidation": "i"}


def answer(*items, view="up"):
    return {"market_view": view, "decisions": list(items)}


def by_symbol(decisions):
    return {d["symbol"]: d for d in decisions}


def test_good_buy_keeps_real_values_of_cited_features():
    view, decisions, problems = check_answer(answer(item(), item("ETHTMN", "HOLD", 0.5, ())), TABLE, {})
    btc = by_symbol(decisions)["BTCTMN"]
    assert (view, problems) == ("up", [])
    assert (btc["action"], btc["confidence"], btc["cited"], btc["problems"]) == ("BUY", 0.7, {"rsi14": 72.2}, [])
    assert btc["setup"] == "sharp_drop"
    assert by_symbol(decisions)["ETHTMN"]["action"] == "HOLD"


def test_bad_parts_turn_into_hold_with_a_reason():
    cases = {
        "unknown action": item(action="SHORT"),
        "not a number from 0 to 1": item(confidence=1.5),
        "nothing to sell": item(action="SELL"),
        "without any known feature": item(cited=("magic", {"x": 1})),
        "which is not active here (active and allowed: sharp_drop)": item(setup="breakout"),
    }
    for expected, bad in cases.items():
        d = by_symbol(check_answer(answer(bad), TABLE, {})[1])["BTCTMN"]
        assert d["action"] == "HOLD", expected
        assert any(expected in p for p in d["problems"]), (expected, d["problems"])


def test_unknown_cited_names_are_flagged_but_known_ones_kept():
    d = by_symbol(check_answer(answer(item(cited=("rsi14", "moon"))), TABLE, {})[1])["BTCTMN"]
    assert d["action"] == "BUY" and d["cited"] == {"rsi14": 72.2}
    assert d["problems"] == ["cited unknown features: moon"]


def test_buy_needs_an_active_setup_in_that_market():
    d = by_symbol(check_answer(answer(item("ETHTMN")), TABLE, {})[1])["ETHTMN"]
    assert d["action"] == "HOLD" and d["setup"] == ""
    assert d["problems"] == ["BUY through setup 'sharp_drop', which is not active here (active and allowed: none)"]


def test_no_setup_and_nothing_held_means_no_ai_call():
    def ask(messages):
        raise AssertionError("the AI must not be asked")

    quiet = {"ETHTMN": features(660_000_000.0)}
    record = decide(quiet, 5_000_000, {}, ask)
    assert record["driver"] == "rules" and record["decisions"][0]["action"] == "HOLD"
    held = {"ETHTMN": {"qty": "1", "value_tmn": 660_000_000}}
    record = decide(quiet, 5_000_000, held, lambda m: reply(json.dumps(answer(item("ETHTMN", "SELL", setup="")))))
    assert record["driver"] == "ai" and record["decisions"][0]["action"] == "SELL"


def test_sell_is_allowed_when_we_hold_the_coin():
    held = {"BTCTMN": {"qty": "0.01", "value_tmn": 220_000_000}}
    d = by_symbol(check_answer(answer(item(action="sell")), TABLE, held)[1])["BTCTMN"]
    assert d["action"] == "SELL" and d["problems"] == []


def test_missing_extra_and_double_markets():
    _, decisions, problems = check_answer(answer(item(), item(), item("DOGETMN")), TABLE, {})
    assert by_symbol(decisions)["ETHTMN"]["problems"] == ["the AI gave no decision"]
    assert [d["symbol"] for d in decisions] == ["BTCTMN", "ETHTMN"]
    assert problems == ["two decisions for BTCTMN, kept the first",
                        "decision for a market we did not ask about: 'DOGETMN'"]
    assert check_answer({"decisions": "BUY all"}, TABLE, {})[2] == ["no decisions list in the answer"]


def reply(text):
    return Reply(text=text, model="m1", seconds=1.0, reasoning="because", usage={"total_tokens": 9})


def test_ai_failure_means_hold_everywhere():
    def ask(messages):
        raise LLMError("chat failed: refused")

    record = decide(TABLE, 5_000_000, {}, ask, "pick")
    assert record["driver"] == "fallback" and record["ai"] is None
    assert [d["action"] for d in record["decisions"]] == ["HOLD", "HOLD"]


def test_bad_json_is_logged_and_means_hold():
    record = decide(TABLE, 5_000_000, {}, lambda messages: reply("I think BUY"), "pick")
    assert record["driver"] == "fallback" and "no JSON object" in record["error"]
    assert record["ai"]["answer"] == "I think BUY" and record["ai"]["reasoning"] == "because"
    assert all(d["action"] == "HOLD" for d in record["decisions"])


def test_good_answer_record():
    record = decide(TABLE, 5_000_000, {}, lambda messages: reply(json.dumps(answer(item()))), "pick")
    assert record["driver"] == "ai" and record["error"] is None and record["market_view"] == "up"
    assert by_symbol(record["decisions"])["BTCTMN"]["action"] == "BUY"


def test_prompt_has_meanings_markets_and_cash():
    system, user = build_messages(TABLE, None, {})
    facts = json.loads(user["content"])
    assert system["role"] == "system" and "JSON" in system["content"]
    assert facts["feature_meanings"] == FEATURES and facts["markets"] == TABLE
    assert set(facts["setup_meanings"]) == {"trend", "sharp_drop", "oversold"}
    assert facts["market_names"] == ["BTCTMN", "ETHTMN"]
    assert facts["cash_tmn"] == "unknown" and facts["held"] == {}


def test_holdings_skip_amounts_too_small_to_sell():
    balances = {
        "TMN": {"value": "5000000", "locked": "1000000"},
        "BTC": {"value": "0.001", "locked": "0"},  # 22,000,000 TMN
        "ETH": {"value": "0.00005", "locked": "0"},  # 33,000 TMN, below 50,000
    }
    cash, held = holdings(balances, RULES, TABLE)
    assert cash == 4_000_000
    assert held == {"BTCTMN": {"qty": "0.001", "value_tmn": 22_000_000}}


def test_log_is_one_json_line_per_decision(tmp_path):
    path = log_decision(tmp_path, {"driver": "ai", "decisions": []})
    log_decision(tmp_path, {"driver": "fallback", "decisions": []})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["driver"] for line in lines] == ["ai", "fallback"]
    assert path.parent.name == "decisions"


def test_wx_decide_end_to_end_without_internet(monkeypatch, tmp_path, capsys):
    settings = {"LLM_BASE_URL": "https://ai.example.com/v1", "LLM_MODEL": "m1", "LLM_API_KEY": KEY,
                "WALLEX_API_KEY": "wallex-secret"}
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: cls(settings)))
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli, "pick_markets", lambda symbols: {
        "BTCTMN": {"symbol": "BTCTMN", "baseAsset": "BTC", "quoteAsset": "TMN", "stepSize": 8, "tickSize": 0,
                   "minQty": "0.00000001", "minNotional": "50000"}})
    monkeypatch.setattr(cycle, "collect_features", lambda symbols, s, d: ({"BTCTMN": TABLE["BTCTMN"]}, {}))
    monkeypatch.setattr(cycle, "fetch_balances", lambda key: {"TMN": {"value": "5000000", "locked": "0"}})
    seen = {}

    def fake_chat(base_url, model, api_key, messages, json_mode=False):
        seen["messages"] = json.dumps(messages)
        return reply(json.dumps(answer(item())))

    monkeypatch.setattr(cycle, "chat", fake_chat)
    assert cli.main(["decide", "--role", "pick"]) == 0
    out = capsys.readouterr().out
    assert "BTCTMN    BUY  0.70" in out and "cited: rsi14=72.2" in out
    record = json.loads(next((tmp_path / "decisions").glob("*.jsonl")).read_text(encoding="utf-8"))
    assert record["cash_tmn"] == 5_000_000 and record["driver"] == "ai" and record["version"]
    assert KEY not in seen["messages"] and "wallex-secret" not in seen["messages"]
    assert KEY not in json.dumps(record) and "wallex-secret" not in json.dumps(record)


def test_tool_calls_are_kept_in_the_record():
    steps = [{"tool": "get_market", "args": {"symbol": "BTCTMN"}, "result": {"rsi14": 72.2}}]
    r = Reply(text=json.dumps(answer(item())), model="m1", seconds=1.0, steps=steps)
    record = decide(TABLE, 5_000_000, {}, lambda messages: r, "pick")
    assert record["ai"]["steps"] == steps
