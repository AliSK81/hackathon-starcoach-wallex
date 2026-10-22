# Results

Saved outputs behind the facts in [DECISIONS.md](../docs/DECISIONS.md). Each one can be made again with the command shown.

| File | Command | What it shows |
|---|---|---|
| `backtest_6_markets.txt` | `uv run wx backtest` | Policies on our 6 markets, taker and limit orders, whole history, each half, and 3-day windows (F25, F28). |
| `backtest_12_new_markets.txt` | `uv run wx backtest PUMPTMN ARBTMN BNBTMN DOGETMN TRXTMN STMN APETMN SUITMN LTCTMN UNITMN ADATMN SANDTMN` | The same on 12 markets that were not used to pick the strategy. |
| `backtest_12h_6_markets.txt` | `uv run wx backtest --hours 12` | 12-hour windows sold into Toman: the agent's setups, dip setups only, the old trend rule (F45). |
| `all_scenarios_6.txt`, `all_scenarios_12.txt`, `all_scenarios_usdt.txt` | `uv run python scripts/test_all_scenarios.py 6\|12\|usdt` | The current agent rules in every test: whole history (limit, taker), each half, 3-day, 1-day and 12-hour windows, against old limits, the old trend rule and holding (F49). |
| `setup_split.txt` | `uv run python scripts/test_setup_split.py` | The agent rules with dips only, trend_strong only, and both, on every market set and period (F50). |
| `replay_agent_graph.jsonl` | `uv run wx agent-replay --from results/replay_agent_graph.jsonl` | The whole agent graph on 20 past moments: every candidate, the AI's decision and size, and how the trade ended (F51). |
| `study_6_markets.txt` | `uv run wx study` | Each setup on its own, with no stop and with 2, 3 and 4 ATR stops. |
| `replay_trend_free_veto.jsonl` | `uv run wx replay --from results/replay_trend_free_veto.jsonl` | The AI free to stop trend buys. It stopped 70%, and made it worse (F27). |
| `replay_trend_checked_veto.jsonl` | `uv run wx replay --from results/replay_trend_checked_veto.jsonl` | The AI may stop a buy only with a checked veto. Slightly better than no AI (F31). |
| `replay_trend_agent.jsonl` | `uv run wx replay --from results/replay_trend_agent.jsonl` | The default role: checked veto plus tools. Every tool call is in the log. Slightly better than no AI (F33). |
| `shadow_trade_log.md` | `uv run wx tradelog` | The live shadow book's trades: why each was placed, and how it ended. |

Each replay line holds one past moment: all features, the AI's full answer and reasoning, the checked decisions, and how each trade played out. `--from` prints the summary without calling the AI.

The backtest and study depend on the candles you have. A re-run on a later date uses a different 120 days, so the numbers will differ. With the same candles, they are the same every time (fixed spreads, F40).
