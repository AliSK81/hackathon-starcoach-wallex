# Discovery: additional agentic / algorithmic trading repos not yet covered
> **Correction (see [05c](05c-wallex-official-mcp.md)):** an official Wallex MCP exists at `https://api.wallex.ir/mcp` (52 tools). Statements below that no official MCP exists refer only to community repos.

**Scope**: new open-source repos beyond the already-covered list (TradingAgents, ai-hedge-fund, Vibe-Trading, AI-Trader, AgenticTrading, FinRobot, TradingAgents-astock, nofx, CloddsBot, Hyper-Alpha-Arena, freqtrade, nautilus_trader, Lean, hummingbot, jesse, OctoBot, lumibot, ccxt, vectorbt, backtesting.py, qlib, FinGPT, FinRL, quant-trading, TA-Lib, Riskfolio-Lib, PyPortfolioOpt, skfolio, tradingview-mcp servers, alpaca-mcp-server, claude-trading-skills repos). Category 12. · **Researched**: 2026-10-21
**Sources**: curated lists `LLMQuant/awesome-trading-agents`, `laplace0x/awesome-agent-trading`, `wilsonfreitas/awesome-quant`, `paperswithbacktest/awesome-systematic-trading` (READMEs fetched with `gh api .../readme`); WebSearch for Nof1 Alpha Arena clones and LLM-trading benchmarks; stars / last push / license verified with `gh api repos/OWNER/REPO` on 2026-10-21 (165 candidate repos from the first two lists checked in one batch). Repos read in more depth (shallow clone, nothing executed): `olaxbt/ai-market-maker@dd71150`, `mnemox-ai/tradememory-protocol@cb599bd`. Others: README only (commit shas from `gh api`: kraken-cli `aa56e59`, okx/agent-trade-kit `c8f7d76`, QuantAgent `2e64c7b`, atlas-gic `cf4349f`, intelligent-trading-bot `0f8748d`).
**Inclusion rule**: >= 300 stars **and** pushed after 2026-04-21, or an official paper repo (flagged "PAPER"). Near-misses are listed separately.

## TL;DR
- The agentic-trading space split into two layers: (1) *brains* (multi-agent debate / swarm: mostly equities, already covered) and (2) *brakes* (policy/guard layers and agent-native exchange CLIs). Layer 2 is where the new, directly reusable work is for our "risk and capital management" and "execution stability" points.
- **Most valuable new find: `mnemox-ai/tradememory-protocol`** (1430 stars, MIT, pushed 2026-10-09): MCP proxy "brake" that enforces a hash-sealed policy (allowed symbols, max order/position notional, daily-loss and drawdown limits, mandatory protective stop, `FULL_HALT`, refuse unclassified tools, deterministic `uuid5` idempotency). Concrete field list is in `src/tradememory/proxy/policy.py:51-110`.
- `olaxbt/ai-market-maker` (2116 stars, AGPL-3.0): LangGraph desks + hard **Risk Guard veto**, backtester that requires an LLM, and **hash-pinned datasets** (`data/MANIFEST.json` with sha256 per CSV) so `--csv-only` reruns match. Best reproducibility pattern seen; AGPL means reuse the idea, not the code.
- `krakenfx/kraken-cli` (769, MIT): exchange CLI built for agents: stable error envelopes (`auth, rate_limit, validation, api, network`), identical **paper-trading** interface without keys, `agents/tool-catalog.json` (174 commands with parameter schemas and safety flags), built-in MCP. A model for how the Wallex tool surface should look.
- `asavinov/intelligent-trading-bot` (1883, MIT, Binance BTCUSDT): production-style ML signal pipeline with strict **offline training vs online prediction feature parity**, periodic retrain backtests, score in [-1, +1]. Best crypto ML-signal template found.
- Nof1 Alpha Arena itself is closed; open clones are `wquguru/nof0` (2754, last push 2025-12-07), `SnowingFox/open-nof1.ai` (807, 2026-04-01), `195440/nof1.ai` (688, 2026-05-15, AGPL) and Hyper-Alpha-Arena (already covered). All trade Hyperliquid perps; none is relevant to a Toman spot account beyond prompt-design ideas.
- LLM-trading **benchmarks** (StockBench `ChenYXxxx/stockbench`, LiveTradeBench `ulab-uiuc/live-trade-bench`, both PAPER repos) report that most LLM agents fail to beat buy-and-hold in their windows (StockBench paper abstract per search summary of arXiv 2510.02209): add a buy-and-hold and a no-LLM baseline to our own evaluation.
- **No Wallex-specific code worth reusing exists.** Best hits: `SajjadKiani/wallex-mcp-server` (2 stars, 2025-05-08), `amiwrpremium/wallex-python` (4 stars, 2022), `MortezaFp/CryptoBasketBot` (0 stars, 2026-07-30, "AI swing" rebalancing bot for Wallex). `ccxt` has no Wallex/Nobitex module (listing of `python/ccxt/` via `gh api`, 105 `.py` files, no `wallex*`/`nobitex*`). Plan to write a thin Wallex client ourselves.
- No TradingAgents crypto fork that meets thresholds changes the architecture materially; the interesting ones are near-misses (below).

## Findings

### A. Main table (meets inclusion rule)
Stars/last push verified via `gh api` on 2026-10-21. Focus: C = crypto, S = stocks, M = multi. "Deep-dive" = our recommendation for the team.

| Repo | URL | Stars | Last push | Category | Focus | Why it matters | Worth deep-dive? |
|---|---|---|---|---|---|---|---|
| mnemox-ai/tradememory-protocol | https://github.com/mnemox-ai/tradememory-protocol | 1430 | 2026-10-09 | Guard / memory (MCP) | M (Hyperliquid, Alpaca, MT5, Binance sync) | Sealed-policy broker-MCP proxy, audit chain, at-most-once orders, "recall losing trades before next order" memory tool | **YES**: policy fields and idempotency are copy-ready (MIT) |
| olaxbt/ai-market-maker | https://github.com/olaxbt/ai-market-maker | 2116 | 2026-08-20 | Multi-agent system | C (Binance testnet, Hyperliquid dry-run) | LangGraph desks, hard `RiskGuardAgent` veto (`src/agents/governance/risk_guard.py:106-143`), pinned data + sha256 manifest, LLM-required backtests | **YES** for architecture/reproducibility; AGPL-3.0, read only |
| krakenfx/kraken-cli | https://github.com/krakenfx/kraken-cli | 769 | 2026-10-13 | Agent-native exchange CLI + MCP | C | Error taxonomy, paper trading with same interface, `tool-catalog.json` with safety flags, local DuckDB/JSONL market tape + replay into paper sessions | **YES** as interface-design reference (MIT, Rust; do not depend on it) |
| okx/agent-trade-kit | https://github.com/okx/agent-trade-kit | 483 | 2026-10-19 | Exchange MCP | C | `--read-only`, `--modules` filtering, built-in rate limiter, MCP tool names in snake_case (`swap_place_algo_order`), 70+ indicator tool | **YES (light)**: safety switches and module split; (MIT) |
| asavinov/intelligent-trading-bot | https://github.com/asavinov/intelligent-trading-bot | 1883 | 2026-08-30 | ML signal pipeline | C (Binance) | Offline (train) vs online (stream) parity of derived features; configurable trade frequency; backtest with periodic retraining; service loop with config file | **YES**: structure for our ML signal + backtest (MIT) |
| Y-Research-SBU/QuantAgent | https://github.com/Y-Research-SBU/QuantAgent | 2876 | 2026-08-18 | Multi-agent (LangGraph), PAPER arXiv 2509.09995 | M (price-only, K-line) | Four agents (indicator, pattern, trend, risk) working from OHLC only, so it maps directly to Wallex candles; README claims HFT-oriented | **YES (light)**: architecture only; README-level read (MIT) |
| chrisworsey55/atlas-gic | https://github.com/chrisworsey55/atlas-gic | 2325 | 2026-09-22 | Self-improving agents | S | "Prompts are weights, Sharpe is the loss": worst agent's prompt is rewritten, kept via git commit if rolling Sharpe improves else reverted; Darwinian weights 0.3-2.5; backtest self-reported (30% of 54 prompt edits kept) | NO for code (equities, 25+ agents, long horizon). Idea only: agent score-weighting and git-versioned prompts (license NOASSERTION) |
| LuckyOne7777/LLM-Trading-Lab | https://github.com/LuckyOne7777/LLM-Trading-Lab | 7507 | 2026-06-24 | Live LLM experiment | S (micro-cap) | 6-month real-money ChatGPT portfolio with full logs and a written evaluation paper; example of a decision log users can audit | NO for code; skim `Experiments/` logs for log-format ideas |
| Nunchi-trade/agent-cli | https://github.com/Nunchi-trade/agent-cli | 521 | 2026-07-08 | Agent trading CLI | C (Hyperliquid perps) | "Guard" trailing stops, "Radar" screening, zero-prompt wallet bootstrap | NO: perps/leverage, DEX wallets |
| ginlix-ai/LangAlpha | https://github.com/ginlix-ai/LangAlpha | 1860 | 2026-10-21 | Research agent | S | Self-described "Claude Code for financial market"; not inspected (README fetch timed out) | NO until inspected |
| OpenByteInc/QuantDinger | https://github.com/OpenByteInc/QuantDinger | 12994 | 2026-10-19 | AI strategy dev platform | C+M | Self-hosted platform for AI-assisted strategy writing, backtest, paper/live (per awesome-quant blurb); not inspected | MAYBE: check how LLM-written strategies are sandboxed and backtested (Apache-2.0) |
| microsoft/RD-Agent | https://github.com/microsoft/RD-Agent | 15013 | 2026-10-21 | Autonomous R&D agent | S/M (factor mining) | LLM proposes and evaluates factors/models in a loop | NO: too heavy for a 3-day window |
| AI4Finance-Foundation/FinRL-Trading | https://github.com/AI4Finance-Foundation/FinRL-Trading | 3842 | 2026-09-18 | RL / quant | S | Successor-style repo from FinRL org (FinRL itself already covered); not inspected | NO |
| jarrodwatts/jev-trader | https://github.com/jarrodwatts/jev-trader | 3052 | 2026-10-13 | On-chain LLM trader | C (Monad DEX) | One LLM decision per block; **dry-run by default when no `PRIVATE_KEY`**, event stream `/events` SSE with every decision | NO: DEX; but dry-run-by-absence-of-key pattern is neat |
| TraderAlice/OpenAlice | https://github.com/TraderAlice/OpenAlice | 7351 | 2026-10-11 | Orchestrator app | M | Desktop app coordinating agents with workspaces, scheduled "Issues" | NO: UI product, AGPL |
| 195440/nof1.ai | https://github.com/195440/nof1.ai | 688 | 2026-05-15 | Alpha Arena clone | C (Hyperliquid) | Open re-implementation of the LLM-vs-LLM perp arena | NO: covered by Hyper-Alpha-Arena-like ideas; AGPL |
| ryan-yuuu/crypto-trading-arena | https://github.com/ryan-yuuu/crypto-trading-arena | 130 | 2026-07-08 | Multi-agent arena | C | (below star threshold; see near-misses) | n/a |
| TNT-Likely/PanWatch | https://github.com/TNT-Likely/PanWatch | 2189 | 2026-10-21 | Monitoring agent | S (CN) | Not inspected | NO |
| himself65/finance-skills | https://github.com/himself65/finance-skills | 3434 | 2026-10-19 | Skills | S | Another skills collection (see file 08 for skill anatomy) | NO |

(ryan-yuuu row is shown only for completeness of the crypto arena search; it fails the 300-star rule.)

### B. Official paper repos (included regardless of stars/date; flagged PAPER)
| Repo | URL | Stars | Last push | Focus | Note | Deep-dive? |
|---|---|---|---|---|---|---|
| pipiku915/FinMem-LLM-StockTrading | https://github.com/pipiku915/FinMem-LLM-StockTrading | 963 | 2024-08-18 | S | FinMem: layered memory + character profile; stale 2 years; MIT | NO: idea (layered memory with decay) already echoed in tradememory |
| The-FinAI/FinCon | https://github.com/The-FinAI/FinCon | 69 | 2026-10-08 | S | FinCon (NeurIPS 2024): manager-analyst hierarchy, "conceptual verbal reinforcement" for risk beliefs. Not read | NO (low stars; read the paper if time) |
| Xtra-Computing/CryptoTrade | https://github.com/Xtra-Computing/CryptoTrade | 166 | 2024-12-01 | C | Reflective LLM crypto trader (EMNLP 2024 per search; not read in this pass); license NOASSERTION | MAYBE: only crypto-specific paper repo found; skim prompts/data pipeline |
| TauricResearch/Trading-R1 | https://github.com/TauricResearch/Trading-R1 | 507 | 2025-09-15 | S | Companion to TradingAgents; no language reported by API (likely docs/weights links only) | NO |
| Y-Research-SBU/QuantAgent | (in table A) | 2876 | 2026-08-18 | M | Paper arXiv 2509.09995 | see A |
| ChenYXxxx/stockbench | https://github.com/ChenYXxxx/stockbench | 183 | 2025-10-28 | S | StockBench (arXiv 2510.02209): 20 DJIA stocks, 2025-03-03 to 2025-06-30, 82 trading days; multi-step workflow portfolio -> analysis -> trade; data from Polygon/Finnhub | YES for **evaluation protocol** (baselines, metrics); not for code |
| ulab-uiuc/live-trade-bench | https://github.com/ulab-uiuc/live-trade-bench | 167 | 2026-02-17 | S + Polymarket | LiveTradeBench (arXiv 2511.03628): FastAPI platform that runs many LLM agents on live markets and logs results | NO |
| HKUDS/AI-Trader | (already covered) | | | | benchmark paper arXiv 2512.10971 | covered |
| FinSearchComp | no official repo found with >= 100 stars (`randomtutu/FinSearchComp` 20 stars is unofficial) | | | | information retrieval benchmark, not trading | NO |

### C. Nof1 Alpha Arena open implementations
Alpha Arena (nof1.ai) is not open source; clones differ in rigor (search summary + `gh api`):
- `wquguru/nof0` (Go, 2754 stars, pushed 2025-12-07): "complete open-source recreation" per its description; stale by our date rule.
- `SnowingFox/open-nof1.ai` (807, 2026-04-01): TS clone; 3 weeks outside the date rule.
- `195440/nof1.ai` (688, 2026-05-15, AGPL): in table.
- `AmadeusGB/alpha-arena` (632, 2025-10-20), `oficcejo/alpha-arena-okx` (346, 2026-07-27): OKX variant; stale/no license.
- `etrobot/open-alpha-arena`: paper trading with ccxt quotes (search summary), small.
- Curated list of clones: `kukapay/awesome-alpha-arena` (30 stars, 2025-11-01).
Lesson from all of them: they hand the model account state + indicators and let it emit an action with leverage; **none** has an independent policy layer. The Alpha Arena results are not evidence for our setting (Toman spot, no leverage, 3 days).

### D. TradingAgents crypto forks (architecture-changing?)
- `Tomortec/CryptoTradingAgents` (284 stars, 2025-12-22, Apache-2.0): replaces LLM-only technical interpretation with data pulled from technical-analysis platforms ("reducing unreliable qualitative fluff" per README); below threshold. The one real architectural change is **numbers computed by code, LLM only reasons**: we adopt that anyway.
- `51bitquant/ai-hedge-fund-crypto` (625, 2025-09-05, MIT): LangGraph DAG: data node -> strategy nodes implementing `BaseNode` (trend, mean reversion, momentum, volatility, stat-arb) over multiple timeframes -> adaptive weighted ensemble -> risk node -> LLM portfolio manager. Fails date rule (last push 2025-09-05) but is the cleanest "ensemble of rule signals then LLM PM" layout. README only.
- `auronsun/TradingAgents-crypto` (11 stars): negligible.

### E. Sub-threshold but design-relevant (listed in awesome-quant; not meeting rule; verified stars)
| Repo | Stars | Last push | Why relevant |
|---|---|---|---|
| w2ur/midas-core | 2 | 2026-10-18 | "Safety lives in the broker, not the prompt": LLM agents propose, a separate broker rejects with reason codes (README example: `MAX_ORDER_NOTIONAL` against a 5,000 cap); MIT. Same idea as the brake |
| BijectiveLabs/trading-research-agents | 37 | 2026-10-21 | Crypto linear perps, LLMs only propose (README snippet truncated in list) |
| OnePunchMonk/AgentQuant | 217 | 2026-10-21 | Iterative LLM strategy proposals + backtests + SQLite memory + holdout + walk-forward (blurb) |
| Beltran12138/evidence-deflator | 0 | 2026-10-21 | MCP that checks how much of an LLM trading backtest falls before the model's training cutoff; directly addresses LLM look-ahead contamination |
| backtester-mcp (PyPI) | n/a | n/a | PBO, deflated Sharpe, bootstrap CI, walk-forward checks as an MCP |
| autonomous-audit (PyPI) | n/a | n/a | tamper-evident SHA-256 hash-chain audit log for agent decisions: useful for our mandatory decision log |
| gbeced/basana | 871 | 2026-10-20 | async event-driven crypto-focused algo framework (license NOASSERTION); alternative to hand-rolled loop |
| Drakkar-Software/OctoBot | 6837 | 2026-10-21 | (already covered) |

### F. Wallex-specific code (exhaustive for GitHub repo search "wallex", "wallex trading bot", "wallex api python")
| Repo | Stars | Last push | Notes |
|---|---|---|---|
| SajjadKiani/wallex-mcp-server | 2 | 2025-05-08 | FastMCP; tools `get_markets, get_balance, place_order, get_order_status, cancel_order, health`; no caps; see file 08 |
| amiwrpremium/wallex-python, amiwrpremium/wallex | 4, 4 | 2022-08, 2022-11 | old Python SDK; likely outdated vs current API |
| amirSamanQ/python-wallex | 0 | 2026-08-04 | Python client, unreviewed |
| MortezaFp/CryptoBasketBot | 0 | 2026-07-30 | rebalancing and dip-catching bot for Wallex "with AI swing" (description); unreviewed |
| NabiKAZ/wallex-pump-bot | 7 | 2025-07-22 | Wallex pump-challenge registration automation: **ignore** (account automation, not trading) |
Nothing to reuse; treat official docs https://developers.wallex.ir/docs as the only source.

## Comparison table
Covered by Table A (columns: repo, URL, stars, last push, category, focus, why, deep-dive).

## Top 5 new repos and exactly what to reuse
1. **mnemox-ai/tradememory-protocol@cb599bd** (MIT)
   - `src/tradememory/proxy/policy.py:17-44` load + seal (refuse unsealed or tampered policy), `:51-110` template fields: `allowed_symbols, max_order_notional, max_position_notional, max_leverage, max_daily_loss, max_drawdown, approval_notional, max_state_age_seconds=120, max_market_age_seconds=60, max_price_deviation_bps=100, max_open_orders, require_protective_stop, max/min_stop_distance_bps (500/10), allow_position_reversal`.
   - `src/tradememory/proxy/alpaca.py:117-118,211-212`: `uuid5(INTENT_NAMESPACE, f"{account_id}:{client_order_id}")` for at-most-once.
   - Behaviour contract from README: refuse unknown tools, never block position close, `FULL_HALT`, chained audit log. We reimplement it for Wallex in ~150 lines inside our executor rather than as a proxy.
2. **olaxbt/ai-market-maker@dd71150** (AGPL-3.0: idea only)
   - Veto agent pattern after LLM proposal (`risk_guard.py:106-143`) and drawdown / leverage reasons list (`:210-256`).
   - `data/MANIFEST.json` shape: `{path, rows, since, until, source, sha256}` per dataset + `updated_utc`; ship the same for our Wallex candle CSVs so judges can re-run bit-identically.
   - Backtest API takes `seed` (`src/api/backtest_routes.py:779`), temperature 0.0 for profile agent (`src/agents/profile_agent.py:372`).
3. **krakenfx/kraken-cli@aa56e59** (MIT)
   - Error envelope categories `auth, rate_limit, validation, api, network` plus `retryable`, `suggestion` fields -> copy into our tool results so the LLM can route on `error` instead of parsing prose.
   - Paper mode with identical command surface; `kraken record` tape + replay to paper session: our shadow-test design (record live Wallex tape to JSONL, replay through the same engine).
   - `agents/tool-catalog.json` idea: machine-readable catalog of every tool with schema + safety flags; generate our README tool table from it.
4. **asavinov/intelligent-trading-bot@0f8748d** (MIT)
   - Separation of offline `train` and online `predict` using the *same* feature functions; config-driven pipeline (`configs/config-sample-1h.jsonc`); score in [-1,+1] consumed by a trade rule; backtest that retrains periodically (walk-forward in spirit). Use as skeleton for `get_ml_signal`.
5. **Y-Research-SBU/QuantAgent@2e64c7b** (MIT, PAPER)
   - Price-only agent decomposition (indicator / pattern / trend / risk) with LangGraph; we can mirror as *four evidence sections* in our single LLM call, or as a two-agent propose-critique (see file 08 pattern C). Verify claims in the paper before citing performance (not done here).

## Reusable for our system
- Policy file + hash seal + deterministic intent IDs (tradememory) -> `risk/policy.py`.
- Hash-manifest for datasets (ai-market-maker) -> `data/MANIFEST.json`, `make verify-data`.
- Error taxonomy + paper/replay interface (kraken-cli) -> `tools/errors.py`, `modes/shadow.py`.
- Offline/online feature parity (intelligent-trading-bot) -> `features/` shared by backtest and live.
- Baselines and evaluation protocol (StockBench): buy-and-hold, no-LLM rule baseline, and a random-action baseline reported next to the agent.
- Licenses: MIT for tradememory, kraken-cli, okx, intelligent-trading-bot, QuantAgent; AGPL-3.0 for ai-market-maker (do not copy code); atlas-gic and CryptoTrade have no clear SPDX id.

## Recommended design decisions for the hackathon
1. Build a **policy-sealed gate** (tradememory fields) and mention it explicitly in the MD doc under "capital and risk management" (Risk 30).
2. Ship **pinned data + sha256 manifest + cached LLM decisions** so `make reproduce` is deterministic (Reproducibility 25; Backtest+shadow 20).
3. Implement **shadow mode as record/replay of the live Wallex tape** (kraken-cli idea): same code path, orders simulated, decisions logged (Execution stability 15).
4. Report **baselines** (buy-and-hold, no-LLM rules) in the backtest summary; StockBench's headline finding means judges may ask "does the LLM add value?" (Real AI use 35). Include an ablation: LLM on vs off.
5. Do not spend time on Alpha Arena clones, Chinese A-share forks, or desktop orchestrators; none addresses Toman spot, 3-day horizon or a risk-gated executor.
6. Add one explicit LLM-contamination note: our backtest window must be after the model's training cutoff or else flagged (see `evidence-deflator` idea); unrelated to the live 3-day window.

## Unverified / open questions
- Star/push numbers are from `gh api` on 2026-10-21; they change quickly. Descriptions for repos marked "README only" or "not inspected" come from the first lines of READMEs or awesome-list blurbs, not from reading code.
- LangAlpha README fetch timed out; QuantDinger, PanWatch, FinRL-Trading, OpenAlice, RD-Agent not inspected in depth.
- CryptoTrade, FinCon and Trading-R1 repos were not read; claims about them come from repo descriptions or training knowledge flagged as such, not from code.
- StockBench / LiveTradeBench conclusions ("most agents fail to beat buy-and-hold") come from a web-search summary of arXiv 2510.02209, not from reading the paper in this pass. LiveTradeBench paper content not read.
- No search for Telegram/Discord-based Iranian trading bots (Persian-language sources) was done beyond GitHub name search; Persian-language repos with other keywords (e.g. "نوبیتکس", "بات معاملاتی") could exist.
- The GitHub search API only returned top-by-stars hits per query; low-star but high-quality Wallex clients might be missed.
- awesome-quant and awesome-systematic-trading mostly list classical quant libraries already represented by covered repos; only the AI/crypto lines were scanned with `grep`.
