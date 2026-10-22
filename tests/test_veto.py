import json

from wx.decide import decide
from wx.llm import Reply
from wx.veto import apply

QUIET = {"setups": ["trend"], "zero_volume_hours_24": 0, "spread_pct": 0.1, "data_age_min": 1.0, "ret_24h_pct": 1.0,
         "rsi14": 60.0}


def hold(symbol, veto=""):
    return {"symbol": symbol, "action": "HOLD", "setup": "", "veto": veto, "problems": []}


def test_supported_veto_stops_the_buy():
    table = {"XTMN": {**QUIET, "zero_volume_hours_24": 11}}
    [d] = apply([hold("XTMN", "illiquid")], table, ("trend",))
    assert (d["action"], d["veto"], d["problems"]) == ("HOLD", "illiquid", [])


def test_unsupported_or_missing_veto_is_overruled():
    table = {"XTMN": QUIET, "YTMN": QUIET}
    a, b = apply([hold("XTMN", "illiquid"), hold("YTMN")], table, ("trend",))
    assert (a["action"], a["setup"]) == ("BUY", "trend") and "overruled" in a["problems"][0]
    assert b["action"] == "BUY" and "without a veto" in b["problems"][0]


def test_market_crash_is_checked_on_btc():
    calm = {"BTCTMN": {**QUIET, "ret_24h_pct": -2.0}, "XTMN": QUIET}
    crash = {"BTCTMN": {**QUIET, "ret_24h_pct": -6.0}, "XTMN": QUIET}
    assert apply([hold("XTMN", "market_crash")], calm, ("trend",))[0]["action"] == "BUY"
    assert apply([hold("XTMN", "market_crash")], crash, ("trend",))[0]["action"] == "HOLD"


def test_sell_and_markets_without_an_allowed_setup_are_left_alone():
    table = {"XTMN": QUIET, "YTMN": {**QUIET, "setups": ["oversold"]}}
    sell = {"symbol": "XTMN", "action": "SELL", "setup": "", "veto": "", "problems": []}
    a, b = apply([sell, hold("YTMN")], table, ("trend",))
    assert a["action"] == "SELL" and b["action"] == "HOLD"


def test_veto_role_prompt_lists_the_vetoes_and_code_checks_them():
    seen = {}
    answer = {"decisions": [{"symbol": "XTMN", "action": "HOLD", "veto": "illiquid", "confidence": 0.7,
                             "reason": "thin", "cited": ["zero_volume_hours_24"]}]}

    def ask(messages):
        seen["facts"] = json.loads(messages[1]["content"])
        return Reply(json.dumps(answer), "m1", 1.0)

    record = decide({"XTMN": QUIET}, 5_000_000, {}, ask, "veto")
    assert set(seen["facts"]["veto_meanings"]) == {"illiquid", "stale_data", "market_crash"}
    d = record["decisions"][0]
    assert d["action"] == "BUY" and "veto 'illiquid' overruled" in d["problems"][0]


def test_a_held_market_is_kept_not_bought_again():
    [d] = apply([hold("XTMN")], {"XTMN": QUIET}, ("trend",), held={"XTMN": {}})
    assert (d["action"], d["problems"]) == ("HOLD", [])
