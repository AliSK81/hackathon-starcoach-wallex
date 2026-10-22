from wx.agent import as_changes, review_tools
from wx.replay import History

T0 = 1_700_000_000 - 1_700_000_000 % 3600


def test_hourly_closes_stop_at_the_moment():
    h = History([[T0 + i * 3600, 1, 1, 1, 100 + i, 1] for i in range(10)], [])
    assert h.hourly_closes(T0 + 5 * 3600, 3) == [102, 103, 104]  # the candle starting at T0+5h is still open
    assert h.hourly_closes(T0, 3) == []


def test_tools_give_features_closes_and_the_setup_record():
    table = {"BTCTMN": {"rsi14": 25.0}, "ETHTMN": {"rsi14": 55.0}}
    asked = []

    def closes(symbol, hours):
        asked.append((symbol, hours))
        return [100.0, 99.0, 101.0]

    tools = review_tools(table, closes, lambda: {"sharp_drop": {"entries": 3}})
    assert tools["get_market"].run(symbol="ETHTMN") == {"rsi14": 55.0}
    assert tools["get_hourly_closes"].run(symbol="BTCTMN", hours=500) == [0.0, -1.0, 1.0]
    assert asked == [("BTCTMN", 72)]  # at most 72 hours
    assert tools["get_setup_record"].run() == {"sharp_drop": {"entries": 3}}
    assert tools["get_market"].parameters["properties"]["symbol"]["enum"] == ["BTCTMN", "ETHTMN"]
    assert "get_setup_record" not in review_tools(table, closes)


def test_as_changes():
    assert as_changes([50.0, 51.0, 49.5]) == [0.0, 2.0, -1.0]
    assert as_changes([]) == []
