# Research Index and Design Synthesis

**Researched**: 2026-10-21 · 13 files, about 2,100 lines · Each file ends with an "Unverified / open questions" section. Every claim cites `repo@sha:file:line` or a URL.

## Files

| File | Topic | Drives scoring criterion |
|---|---|---|
| [01-agentic-architecture.md](01-agentic-architecture.md) | Agent topology, prompts, schemas, call budget | Real AI use (35), Strategy logic (40) |
| [02-crypto-llm-trading.md](02-crypto-llm-trading.md) | nofx, CloddsBot, Hyper-Alpha-Arena, Alpha Arena failures | Real AI use, Strategy logic |
| [03-risk-capital-management.md](03-risk-capital-management.md) | Risk gate spec, sizing, stops, drawdown breakers | Risk (30), Loss control (30) |
| [04-backtesting-shadow-mode.md](04-backtesting-shadow-mode.md) | Backtest and shadow fills, Broker interface, LLM replay | Backtest + shadow (20) |
| [05-wallex-api-integration.md](05-wallex-api-integration.md) | Wallex endpoints, auth, markets, candles, MCP quality | Execution stability (15) |
| [05b-execution-engine-patterns.md](05b-execution-engine-patterns.md) | Order state machine, retries, reconciliation, final liquidation | Execution stability |
| [05c-wallex-official-mcp.md](05c-wallex-official-mcp.md) | **Official Wallex MCP** (`https://api.wallex.ir/mcp`, 52 tools); supersedes "no official MCP" in 05/08/12 | Real AI use, Execution stability |
| [06-signals-strategies.md](06-signals-strategies.md) | Features, regimes, fee break-even maths | Profit (90), Strategy logic |
| [07-ml-rl-models.md](07-ml-rl-models.md) | ML/RL verdict, LightGBM tool, paper evidence | Real AI use |
| [08-skills-mcp-agent-patterns.md](08-skills-mcp-agent-patterns.md) | Guarded write tools, agent frameworks, skill rules | Real AI use, Risk |
| [09-decision-logging-observability.md](09-decision-logging-observability.md) | Hash-chained per-trade log, replay, verification | Deliverables, Reproducibility |
| [10-repo-structure-reproducibility.md](10-repo-structure-reproducibility.md) | Repo layout, CLI, config, required MD doc outline | Reproducibility (25) |
| [11-evaluation-metrics.md](11-evaluation-metrics.md) | Metric formulas, "not one lucky trade" checks | Backtest + shadow, Strategy logic |
| [12-discovery-additional-repos.md](12-discovery-additional-repos.md) | Extra repos worth reading | Coverage |

## Consolidated design (what the research supports)

1. **Pipeline per cycle (about 1 decision per hour on 1h bars):** code features → code data-health gate and shortlist → one LLM Strategist call (typed JSON) → one LLM Critic call on entries only → **deterministic Risk Gate** → code Executor → LLM Reflector per closed trade. (01, 06)
2. **The LLM never outputs a Toman amount.** It outputs an action enum, conviction, a `size_bucket`, cited `feature_id`s and an invalidation condition. Code maps buckets to size and clamps. (01, 08)
3. **Risk Gate is fail-closed and outside the LLM.** Ten ordered checks: 0.75% risk per trade, 25% max single position, 60% max exposure, drawdown ladder at 2.5% / 4% / 6%, 2% daily-loss halt, cooldowns, minimum edge versus round-trip cost, kill switch with flatten to Toman. (03)
4. **Reproducibility comes from record/replay, not seeds.** Cache LLM responses by prompt hash (`--llm live|record|replay`), log everything to a hash-chained JSONL, and make the executor refuse any order without a logged `decision_id`. (04, 09)
5. **One `Broker` interface with three implementations:** `BacktestBroker`, `ShadowBroker` (live data, order-book-walk fills) and `WallexBroker`. Decisions at candle t see data to its close and fill at t+1's open; stop wins ties. (04)
6. **Signals:** deterministic features (EMA 20/50/200, ADX and ATR regime gate, Donchian-20 breakout with `shift(1)`, RSI/z-score pullbacks in an uptrend). The LLM chooses among pre-validated setups. Skip RL; at most add one calibrated LightGBM probability as a tool. (06, 07)
7. **Wallex access.** An official MCP exists (`https://api.wallex.ir/mcp`, 52 tools; see 05c), but it has no server-side order caps. The LLM gets read tools via MCP plus one guarded `propose_order`; execution goes through our own thin client and risk gate. The community MCPs are broken and ccxt has no Wallex module. (05, 05c, 08)
8. **Execution:** persist intent, send with a unique `client_id`, query by `client_id` after any timeout, poll open orders and balances (the private WebSocket needs a website-login cookie), and liquidate in stages before the end. (05b)

## Cross-file conflicts and gaps (reconcile before building)

| Issue | Detail | Action |
|---|---|---|
| **Fees disagree** | File 03 assumes 0.35% + 0.1% slippage per side. File 06 cites a third-party source at 0.10% (TMN) and 0.05% (USDT). File 05 saw only a 0.15% example, and Wallex's own fee page was not readable. | Day 0: call `GET /v1/account/fee` with the real key and recompute every fee-dependent number in 03, 04, 06. |
| BUY fee may be taken in the base asset | File 05 saw one sample (`feeCurrency` equal to the bought coin). Sellable quantity is then less than `executedQty`. | Ledger must track net quantity; verify in the day-1 smoke test. |
| Fill model in file 04 uses placeholder costs | It was written before the real Wallex details were found. | Replace its fee/spread defaults with file 05 and 06 values. |
| Candle history is shallow | About 19 days of 1m, 29 days of hourly, 800 days daily. `resolution` behaves inconsistently. | Start a data collector at once; backtests are limited to about 4 weeks of hourly data. |
| USDT/TMN drift | USDTTMN rose about 16% in 30 days (file 06). TMN-quoted coin gains can be FX drift. | Evaluate signals in USDT terms and TMN terms. |
| Vibe-Trading backtest module not read | Agent a4 could not clone it. | Optional follow-up. |
| LLM paper evidence is weak | FINSABER and look-ahead studies (file 07) show agents' edge shrinks out of sample. | Show shadow-run evidence and a rules-only baseline in parallel. |

## Scope decisions (set by the team)

- **End-agnostic:** the system does not know the hackathon end time or what counts as final holdings. The staged liquidation in 05b and the flatten step in 03 are an optional operator command / kill switch (`flatten`), not a built-in schedule.
- **LLM provider:** custom, chosen later. Keep the client behind an OpenAI-compatible `base_url`.
- **API key:** supplied later via a gitignored `.env` (`WALLEX_API_KEY`). A read-only key is available for research if needed.

## Still open (not blocking)

1. Whether margin/OTC markets are allowed; default to spot long-only until confirmed.
2. Real fee rates: read with `wallex_basic_get_account_fees` once a key is set.

## Licenses to respect

- freqtrade is GPL and nofx is AGPL: re-implement from the ideas, do not copy code.
- Nautilus is LGPL.
- Hummingbot is Apache: port with attribution.
- AgenticTrading's OpenMDW-1.0 license is unreviewed, and AI-Trader has no LICENSE file: ideas only.

## Suggested next steps

1. When the API key is available, run the day-0 checks (`/v1/account/fee`, `/v1/markets`, a minimum-notional order test on USDTTMN), and start the candle collector.
2. Freeze the repo layout from file 10 and the Broker interface from file 04.
3. Build in this order: Wallex client → logging → risk gate → feature pipeline → backtest/shadow brokers → LLM agent.
