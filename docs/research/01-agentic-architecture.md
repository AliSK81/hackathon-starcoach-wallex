# Agentic Decision Architecture: what 7 open-source agentic trading repos actually do

**Scope**: how LLM-agent trading systems are wired (roles, graph, schemas, risk, logging, determinism, cost) and what to copy for a Wallex hackathon engine. · **Researched**: 2026-10-21 · **Method**: shallow clones read with Read/Grep only (nothing executed).

**Repos + commits (all read at HEAD of default branch)**
| Repo | Commit | License (verified from LICENSE file unless noted) |
|---|---|---|
| TauricResearch/TradingAgents | `e8f5503` | Apache-2.0 |
| virattt/ai-hedge-fund (new "v2", `hedge_fund/` package) | `4e1657d` | MIT |
| HKUDS/Vibe-Trading | `9081946` | MIT |
| HKUDS/AI-Trader | `d03ff6c` | README badge says MIT; **no LICENSE file in repo root** (ls) |
| Open-Finance-Lab/AgenticTrading | `0cf397c` | OpenMDW-1.0 (LICENSE header; terms not analysed) |
| AI4Finance-Foundation/FinRobot | `2717499` | Apache-2.0 |
| simonlin1212/TradingAgents-astock | `e3981af` | Apache-2.0 (fork of TradingAgents `7e9e7b8`) |

Citation form: `repo@sha:path:LINE`. Where I cite a file without a line, I read the file but did not record the line.

## TL;DR

- **Only two repos have a real "LLM proposes, deterministic code disposes" boundary**: ai-hedge-fund (`risk/limits.py`, `portfolio/construction.py`, `pipeline/stages.py`) and Vibe-Trading live mode (`live/enforcement.py` `check_mandate`, fail-closed). TradingAgents/FinRobot/AgenticTrading-research stop at a text/enum rating and have **no executable sizing, no portfolio, no fee model** (TradingAgents `backtest.py` docstring says it "must not grow" a portfolio simulator). We must build the gate ourselves; ai-hedge-fund's is the cleanest template to re-implement.
- **Best structured-decision patterns**: TradingAgents `TraderProposal`/`PortfolioDecision` Pydantic enums (`schemas.py:76-90,146-265`) with a `_coerce_optional_float` guard that drops "15%", "N/A", ranges instead of failing the whole decision (`schemas.py:33-58`); AgenticTrading `LLMTradingDecision` (`validator.py` ~L80-150) with confidence in [0,1], reasoning 5..500 chars, int size, and a **hard reject of any response containing "tool_calls"/"invoke"** (JSON-only boundary).
- **Real AI + explainability in one trick (FinRobot desktop)**: bull/bear agents may *only cite `evidence_id`s from a deterministic evidence set and may not write numbers*; render layer fills values (`finrobot_desktop/.../agents/instructions/bull_agent.md`, judge: `judge_agent.md`). This is a hallucination guard that is cheap to port: LLM cites feature IDs, code verifies they exist and prints the real values into the decision log.
- **Determinism is weak everywhere**: none of the repos seeds anything. ai-hedge-fund sets no temperature (`llm/client.py make_llm`, grep found none) but gets reproducibility from a **prompt-hash cache that stores exact prompt+response per decision** (`llm/cache.py:25-48`) and a **hash-chained append-only ledger** (`paper/ledger.py`, `pipeline/session.py:108 compute_hash`). AgenticTrading's own script admits "providers are not deterministic at temperature 0" (`dashboard/scripts/diff_backtest_runs.py` docstring). => Reproducibility for judges = record/replay of LLM I/O, not seeds.
- **Debate is expensive and its value is unproven**: TradingAgents default = 4 analysts (tool loops) + bull/bear (2 calls) + research mgr + trader + 3 risk debaters + PM; ~20-32 LLM calls per ticker per decision (my estimate from graph shape, see table). For a 15-30 min cadence on 3-5 TMN/USDT pairs this is unaffordable and slow; a single structured call + one adversarial critic call is the sane budget.
- **Only AgenticTrading's `decision_tape.py` logs both raw LLM intent and post-gate actions, with a `driver` field** (`llm` / `llm_fallback` / `rule_based`, L47-49): exactly what our per-trade decision log needs to prove "AI genuinely drives decisions" and that fallbacks are labelled.
- **Anti-overfit idea worth stealing (FinRobot `strategy_agent.py`)**: LLM tunes parameters in 3 iterations on a 70% in-sample window, final result reported once on 30% OOS (L34-39). Good story for the "backtest + shadow" criterion.
- **Mandate/halting patterns (Vibe-Trading live)**: pinned mandate re-injected every turn, kill-switch file, daily trade count, token/cost budget per day (`live/runtime/decision_budget.py`), abort-never-resend on ambiguous order state (`runner.py` docstring). Cheap to port as plain files.
- **AI-Trader is a marketplace, not an agent**: no LLM logic inside; it defines a REST contract (`POST /api/signals/realtime {action,symbol,price,quantity,content}`) and a flat 0.1% fee (`service/server/fees.py:5`). Low value for us beyond the signal payload shape.
- **Hallucination guards are mostly missing**: TradingAgents relies on prompt text ("treat verified snapshot as source of truth", `market_analyst.py`) plus a `get_verified_market_snapshot` tool; astock adds an LLM+hard-check "Quality Gate" over analyst reports. No repo verifies LLM-cited numbers against data except FinRobot desktop's evidence-id scheme.

## Findings

### 1. TradingAgents (TauricResearch) `e8f5503`
- **Framework/graph**: LangGraph `StateGraph(AgentState)` built in `tradingagents/graph/setup.py:142` (`GraphSetup.setup_graph`). Analysts run **in parallel** (edges START -> each analyst, L160-166, fan-in to Bull Researcher), each as its own sub-graph with private message history and a tool loop capped by `max_tool_rounds` (default 20, `default_config.py`; `setup.py:53-90`), after which a WRAP_UP human message forces a report.
- **Roles (nodes)**: Market, Sentiment (social), News, Fundamentals analysts (`quick_think_llm`) -> Bull Researcher <-> Bear Researcher (quick) -> Research Manager (`deep_think_llm`) -> Trader (quick) -> Aggressive / Conservative / Neutral risk debaters (quick, round-robin) -> Portfolio Manager (deep) -> END (`setup.py:132-185`). A "Memory Log" node settles old decisions in parallel with analysts (`setup.py:161-163`).
- **Inputs per agent**: analyst tool calls (yfinance / alpha_vantage / sec_edgar / fred / polymarket per `data_vendors` in `default_config.py`); researchers and risk debaters get all four text reports + instrument context + portfolio context (`bull_researcher.py:18-22`, `aggressive_debator.py:23-28`); Trader gets research plan + technical market report (`trader.py:32-44`); PM gets research plan, trader plan, full risk-debate history, and `past_context` lessons (`portfolio_manager.py:35-62`).
- **Prompt excerpts**: Bull: "You are a Bull Analyst advocating for investing in the {target}... Engage... debating effectively rather than just listing data" (`bull_researcher.py:31`). PM: "Conflict alone is not a reason to Hold. Commit to the stronger case, sized by how decisively it wins." (`portfolio_manager.py:66`). Trader system: "State entry price and stop-loss as absolute price levels... never a percentage or a range" (`trader.py:56-59`).
- **Output schema**: Pydantic via `llm.with_structured_output` (`structured.py bind_structured/invoke_structured`): `ResearchPlan{recommendation: PortfolioRating, rationale, strategic_actions}`, `TraderProposal{action: Buy|Hold|Sell, reasoning, entry_price?, stop_loss?, position_sizing: str?}`, `PortfolioDecision{rating: Buy|Overweight|Hold|Underweight|Sell, executive_summary, investment_thesis, price_target?, time_horizon?}` (`schemas.py:66-265`). **No numeric quantity anywhere**; sizing is free text ("5% of portfolio"). Fallback: if the structured call fails, retry as free text and regex-parse the rating (`structured.py:59-95`, `portfolio_manager.py:81-86`).
- **Final decision**: PM rating = `final_rating`; rendered to markdown with fixed headers (`render_pm_decision`, `schemas.py:268`).
- **Debate**: Bull/Bear alternate until `count >= 2*max_debate_rounds` (default 1 -> 2 turns) then Research Manager judges; risk debate 3 turns each `max_risk_discuss_rounds` (default 1 -> 3 turns) then PM (`conditional_logic.py`). All path maps are exhaustive to avoid LangGraph crashes (`setup.py:31-45`, issue #1088).
- **Memory/reflection**: append-only markdown log `[date | ticker | rating | pending]` + `DECISION:` / `REFLECTION:` blocks (`memory/log.py:11-60`); idempotent per (ticker,date). On the next run, due decisions are settled with raw and alpha return vs a regional benchmark (`holding_period_days: 5`), and one LLM call writes a 2-4 sentence lesson (`memory/reflection.py:13-34`); PM reads lessons. No vector store.
- **Provider abstraction**: `llm_clients/factory.py` with clients for OpenAI, Anthropic, Google, Azure, Bedrock, etc.; two tiers `deep_think_llm` / `quick_think_llm`, each may override provider+URL; `temperature` is forwarded only if set (`factory.py:114-119`, default `None` in `default_config.py:116`).
- **Cost per decision (estimate)**: fixed nodes = 2 (bull/bear) + 1 + 1 + 3 + 1 = 8 calls, plus analysts: each >= 2 calls (tool-call turn + report), realistically 3-6 with tool rounds => about 20-32 calls and large prompts (4 long reports re-sent to ~9 downstream agents). +1 reflection call per settled decision.
- **Risk handling**: only LLM debate (aggressive/neutral/conservative) -> PM prose. No numeric limits in code.
- **Logging**: `write_report_tree` markdown/HTML tree + `_log_state` JSON of full state + `run_settings()` allowlist (models, rounds, vendors; no keys) (`trading_graph.py:255-290`); checkpoint/resume via LangGraph checkpointer keyed by a settings hash (`trading_graph.py:141-151`).
- **Reproducibility**: no seed; `data_cache_dir` caches data; checkpoint thread-id includes config hash. Backtest module runs a (ticker,date) grid and scores ratings, explicitly *not* a portfolio sim (`backtest.py` docstring).
- **Weaknesses**: no sizing/execution; prose reports can contain invented numbers (mitigated only by a verified-snapshot tool + prompt); "Hold" bias handled via prompt; cost/latency high; five-tier rating is not an order.

### 2. ai-hedge-fund (virattt) `4e1657d` (new architecture)
- **Not LangGraph anymore.** A plain-Python pipeline: `assess_fund` -> `execute_decision` (`pipeline/stages.py:40-152`). Persona agents (`signals/buffett.py`, `graham.py`, `lynch.py`, `munger.py`, `druckenmiller.py`) are **one LLM call each, per ticker, per session**, returning a `Signal` in [-1,1]; quant models (`pead.py`) share the same `AlphaModel` interface (`signals/base.py:17-43`).
- **Schema**: model must return JSON `{"signal": "bullish|bearish|neutral", "confidence": 0-100, "reasoning": "..."}` (prompt end in `buffett.py:54-56`); parsed by `extract_json` (fence -> whole -> first balanced braces, `llm/client.py:333`) and validated in `LLMAgent._parse` (`llm_agent.py:158-176`); value = sign * confidence/100 (`llm_agent.py:187`). **Failure contract**: LLM/parse failure -> `Signal(value=0, abstained=True)`, data errors propagate (fail loud) (`llm_agent.py:15-18, 103-123`).
- **Decision -> size**: `blend_signals` (`portfolio/construction.py:29-103`): weighted average per ticker, abstentions excluded, long-only analysts cannot create short evidence, scores normalised to `gross_target`; modes `long_only | long_short | dollar_neutral`.
- **Risk (deterministic, outside LLM)**: `apply_limits` (`risk/limits.py:51-102`) clamps `max_position_pct` per ticker then scales to `max_gross_exposure`; "Conviction requests, risk disposes... no clamp is ever negotiable"; removed exposure stays in cash (not redistributed); every clamp emits a `ClampEvent`. `validate_targets` (`portfolio/validation.py:16-80`) **recomputes** the blend from the recorded signals and refuses orders if the recorded weights do not match the evidence. `execute_decision` re-checks projected weights vs limits before placing any order (`stages.py:130-139`).
- **Time discipline**: assess at close of session N, execute at close of N+1 using exact prices; execution refreshes the assessment (`stages.py:105-152`); `clock.is_complete(as_of)` prevents look-ahead.
- **Reproducibility/logging (best in class)**: `PromptCache` stores exact `{agent, model, system, user, response, parsed, snapshot_hash}` per decision under `sha256(agent|model|system|user)[:24]` (`llm/cache.py`, `llm_agent.py:93-125`) - re-running an unchanged snapshot costs $0 and returns the identical answer. Paper trading ledger is hash-chained (`paper/ledger.py`: `prev_hash`, `compute_hash`, replay refuses edited/gapped records), kill switch `control.json`, halt on any failure so cron cannot retry into a broken book (`paper/tick.py` docstring). `blind=True` prompts withhold ticker/dates/$ values for backtests to defeat LLM memory leakage (`llm_agent.py:58-64`).
- **Provider abstraction**: `LLMClient` Protocol with `complete(system,user)->str`; `make_llm` maps model id -> provider via `llm/api_models.json` registry (Anthropic, OpenAI, DeepSeek, Google, xAI, Kimi, TypeSafe/Jev), `max_tokens=4096`, `max_retries=1`, timeout 60s (`client.py:225-286`). No temperature set.
- **Cost**: N_agents x N_tickers calls per session; cache makes backtest re-runs free; no debate.
- **Weaknesses**: persona prompts are fundamentals-based (equities), useless for crypto as-is; no stop-loss/intraday risk; no fees/slippage in the shown stages (broker sim files exist: `brokers/sim.py`, not analysed).

### 3. Vibe-Trading (HKUDS) `9081946`
- **Orchestration**: (a) single ReAct agent loop `agent/src/agent/loop.py` (`max_iterations=50`, wrap-up nudge at 80% of iterations L524/597, 5-layer context compaction); (b) **Swarm** DAG runtime `swarm/runtime.py` - topological layers, parallel within a layer, YAML presets (~30) under `swarm/presets/`, each worker a full ReAct agent with tools (`bash, read_file, write_file, load_skill, get_market_data`), `max_iterations: 50`, `timeout_seconds: 1800`, `max_retries: 1`.
- **Closest preset to us: `crypto_trading_desk.yaml`**: 3 parallel analysts (`funding_basis_analyst`, `liquidation_analyst`, `flow_analyst`; perp/OKX-oriented) -> `desk_risk_manager`, with `depends_on` and `input_from` wiring. Risk manager prompt: signal weights "on-chain flow (40%) > funding/basis (35%) > liquidation levels (25%)", "Risk per trade: max 2% of portfolio", output sections: direction long/short/neutral/wait, conviction high/medium/low, entry zone, TP1-3, stop-loss, sizing %, risk gates "X%" that "YOU must set from measurement" using `src.quantlib.risk.historical_var/cvar`, `max_drawdown_analysis`, `fit_gpd_tail`. **Output is free-form markdown, not a validated schema** - no structured action enum in the swarm path.
- **Live-trading governance (the valuable part)**: `live/mandate/model.py` `HardCaps{account_funding_usd, max_order_notional_usd, max_total_exposure_usd, max_leverage, allowed_instruments, max_trades_per_day}` + `UniverseConstraint`; `live/enforcement.py check_mandate` is a pure fail-closed function: exclude-list -> instrument -> asset-class -> single-order notional -> total exposure -> leverage -> daily count -> funding; structural breach = DENY, quantitative breach = pause for re-authorisation. Mandate is read-only to the agent. Runner tick order: `halt -> proactive expiry -> reconciliation -> autonomous turn -> audit` (`live/runtime/runner.py` docstring); mandate pinned inline in every turn prompt; never auto-resend a mutating call after ambiguous state; `decision_budget.py` caps `max_daily_turns` (26), `max_daily_tokens` (1M), optional USD cap; hash-chained audit ledger (`governance/ledger.py`) and run manifests with prompt/skill/tool hashes (`governance/manifest.py`).
- **Memory/reflection**: separate memory subsystem and "shadow account" (extracts a user's journal into rules - unrelated to the hackathon's "shadow testing" meaning).
- **Provider abstraction**: `providers/llm.py` (75 KB) + `llm_providers.json`, ~25 providers; auto-retry without `temperature` for models that reject it (`llm.py:606-621`).
- **Cost**: swarm preset = 4 workers x up to 50 ReAct iterations => easily 50-200 LLM calls and minutes-to-30-min latency per run. Not usable at 15-min cadence.
- **Weaknesses**: heavyweight (10k+ lines in swarm/trading alone), perps/US-broker oriented, free-text outputs, thresholds left to the LLM.

### 4. AI-Trader (HKUDS) `d03ff6c`
- A FastAPI + SQLite **agent social/paper-trading marketplace** (`service/server/*`, `skills/*/SKILL.md`). External agents register (`POST /api/claw/agents/selfRegister`), poll heartbeat (`POST /api/claw/agents/heartbeat`, 30-60 s), publish signals. **There is no internal LLM decision logic** (grep for llm/anthropic in `service/server` returned only unrelated hits).
- Signal contract (`skills/tradesync/SKILL.md` ~L84-115): `POST /api/signals/realtime {action: buy|sell|short|cover, symbol, price, quantity, content}`; `content` = free-text rationale. Fees: fixed `TRADE_FEE_RATE = 0.001` applied in `routes_signals.py:240-244`. `research/schemas/*.schema.json` define exported trade/position schemas for reproducible paper datasets.
- Use for us: only as a reference for a minimal trade-record schema (action, symbol, price, quantity, rationale, fee). No architecture to copy.

### 5. AgenticTrading / "Agentic Trading Lab" (Open-Finance-Lab) `0cf397c`
Two loosely coupled subsystems (`CLAUDE.md`): **`dashboard/`** (the shipping product) and **`orchestration/FinAgents`** (NeurIPS-2025 research framework, "not wired into the dashboard").
- **Dashboard LLM path** (what matters): one LLM call per decision bar (or a user-defined multi-step "pipeline" of sub-agents, `infrastructure/llm/pipeline_runner.py _build_step_prompt` L138-209: step prompt + required output format + market snapshot only in step 0 + upstream outputs; last step adds EXECUTION RULES "Trade ONLY symbols listed in the snapshot / Only SELL symbols in current_holdings / Respect available cash / integer share quantities").
- **Schema + gate**: `LLMTradingDecision` {action: buy|sell|hold, symbol (regex), confidence 0..1, reasoning 5..500 chars, position_size int <= `MAX_ORDER_SHARES=10000`, stop_loss_price?, take_profit_price?} (`validator.py` ~L80-150). `PortfolioConstraints{cash_available, max_position_size=5000, max_daily_trades=20, max_position_value=50000, min_confidence=0.3}` (L158-165); decisions below `min_confidence` are skipped (L248), cost > cash or > max_position_value are rejected (L263-282). Rejects any response containing `tool_use|tool_calls|function_calls|invoke` before JSON parsing (CRITICAL CHECK 1). `fix_json_formatting` repairs missing commas / trailing commas (`decision_parsing.py`).
- **Agent-Environment Protocol** (`domain/runs/protocol.py`): `DecisionIn{idempotency_key (1-200), orders[{symbol, side, quantity_type: shares|notional|weight, quantity (finite, 0 <= q < 1e12), order_type: market}], confidence, rationale, trace}`; `resolve_order_quantity` converts `weight` -> shares via `equity * w // price`. Idempotency key and finite-number guards are worth copying.
- **Decision log**: `domain/backtesting/decision_tape.py` (TAPE_VERSION=1): per bar `decision_recorded` + `execution_result`, keeps raw model orders (`intent`) AND post-gate `actions`, pre-decision portfolio, fill plan, fills and rejections, allow-listed fields only, `driver` in {`llm`, `llm_fallback`, `rule_based`} (L47-49), 60 KiB payload cap, observational only.
- **Determinism**: temperature optional (omitted unless configured, `backtest_harness.py:221`; custom algo uses 0.3, `dashboard/scripts/backtest_custom_algo.py:159`); explicit statement that outputs are non-deterministic even at T=0 and errors compound because "each bar's prompt embeds the previous bar's answer" (`diff_backtest_runs.py` docstring).
- **Orchestration (research code)**: `FinAgents/orchestrator/core/dag_planner.py` `DAGPlanner.plan_strategy_from_description` (L286): LLM turns a NL strategy into a networkx DAG over agent pools (data, alpha, risk, portfolio, execution, transaction-cost, backtest), falls back to a template DAG on failure (L672); `rl_policy_engine.py`; memory agent on Neo4j + vectors. Heavy infra (MCP/A2A servers, Neo4j); not suitable for 3 days.
- **Weaknesses**: equities (DJIA) hard-coded; sizing in integer shares; in the orchestration code the "backtest simulation" is internal simulation, and dual codebases diverge.

### 6. FinRobot (AI4Finance) `2717499`
- Three generations: V0 AutoGen (`finrobot_autogen`, educational), V1 OpenAI Agents SDK (`finrobot_equity`), **V2 PydanticAI (`finrobot_desktop`, "production")**. It is an **equity-research** system, not a trader; trading appears only in `engine/backtest/strategy_agent.py`.
- **V0 roles** (`agent_library.py`): Market_Analyst (FinnHub/yfinance tools), Expert_Investor (report building), etc.; AutoGen group chats with "Reply TERMINATE". No action schema.
- **V2 pipeline**: sub-agents `data, analysis, modeling, synthesis, report` each from `engine/agents/instructions/{role}_agent.md` (`agents/factory.py`, `SUB_AGENT_ROLES`); only `data` gets `query_financial_data` tool, tickers validated (`validate_ticker`) and `data_type` enum errors raised as `ModelRetry` so the model self-corrects (factory.py comments). Deterministic compute (DCF/DDM/LBO/comps) is pure Python; README principle: "Numbers are code-calculated. Narratives are LLM-assisted. Every output is provenance-tracked."
- **Bull/Bear/Judge (IC debate) with grounding**: bull/bear emit `SideCase{side, arguments[{claim, evidence_ids}]}` and "may not write any number yourself - cite its evidence_id and the render layer fills in the real value"; judge outputs `call: BUY|HOLD|SELL`, `conviction 0..1`, `swing_factor`, `change_my_mind`, and "Never refuse to call... express weak evidence as LOW conviction" (`bull_agent.md`, `judge_agent.md`). Pipeline validators in `engine/pipelines/validators.py` (sanity bounds on multiples etc.).
- **LLM-tuned backtest with OOS**: `MAX_ITERATIONS=3`, `IN_SAMPLE_FRACTION=0.70`, `_MIN_OOS_DAYS=60`; LLM picks strategy + params (`BacktestConfig` structured output), gets Sharpe/drawdown/win-rate fed back, best IS params evaluated once on the OOS tail; degrades to a default SMA strategy with a visible warning when the LLM fails (`strategy_agent.py` L1-60).
- **Weaknesses for us**: equity fundamentals/SEC focus, heavyweight desktop app; trading logic is a demo (SMA crossover via Backtrader).

### 7. TradingAgents-astock (fork) `e3981af`
- Fork of TradingAgents for China A-shares (`CHANGES_FROM_UPSTREAM.md`): swaps data vendors to mootdx/Tencent/akshare, adds 3 analysts (policy, hot-money/dragon-tiger, lock-up watcher) -> 7 analysts, **sequential** analyst chain (`graph/setup.py:154-175`) instead of upstream's parallel fan-out, adds A-share market constraints (T+1, limit up/down, lot size, trading hours, ST) into PM/Trader prompts, per-role LLM routing (`ROLE_KEYS`, `llm_for(role)`), and `performance.py` (win-rate/alpha stats over the memory log; refuses Sharpe on overlapping decisions, `MIN_MEANINGFUL_SAMPLE = 20`).
- **Quality Gate** node between last analyst and Bull Researcher (`agents/quality_gate.py`): layer 1 deterministic grading A-F (empty / <200 chars / failure-marker strings like "I cannot retrieve" / missing table / count of "[数据缺失" markers), layer 2 one LLM review -> `data_quality_summary` consumed by the debaters. Cheap pattern to port as a *code-only* data-health check.
- Also still prose-first; `SignalProcessor` now just regex-parses the PM rating with no extra LLM call (`graph/signal_processing.py`).
- **Cost**: 7 analysts + gate + debate => more than upstream (~30-45 calls, my estimate).
- Lesson: market-specific hard rules (T+1, lot size) are placed in *prompts*, i.e. unenforced. For Wallex, put exchange rules (min notional, tick/step size, fee) in code.

## Comparison table
| Repo | Framework | Roles / LLM calls per decision (est.) | Output | Sizing | Debate | Memory | Deterministic risk gate | Decision log | Reproducibility |
|---|---|---|---|---|---|---|---|---|---|
| TradingAgents | LangGraph | 4 analysts + bull/bear + RM + trader + 3 risk + PM = ~20-32 | Pydantic enums, 5-tier rating | free text only | bull/bear 1 round; 3-way risk 1 round | markdown log + 1 LLM reflection per settled trade | none | md/HTML tree + state JSON + settings allowlist | checkpoint by config hash; no seed |
| ai-hedge-fund | plain Python | N personas x N tickers (1 call each) | JSON signal/confidence | code: blend -> weights | none | none | **yes**: position/gross clamps, validate_targets | per-call prompt+response cache, hash-chained ledger | prompt-hash cache, blind mode, clock gating |
| Vibe-Trading | custom ReAct + DAG swarm | 4 workers x up to 50 iterations = 50-200 | markdown | LLM text (risk mgr 2%/trade) | none (DAG synth) | memory subsystem | **yes (live)**: mandate caps, fail-closed | hash-chained audit ledger, run manifests | manifest hashes; no seeds |
| AI-Trader | FastAPI platform | 0 internal | REST signal | caller-supplied qty | n/a | n/a | n/a | DB + research schemas | exported datasets |
| AgenticTrading | FastAPI + pipeline runner (+ research DAG) | 1 per bar (or N-step pipeline) | JSON decision (strict Pydantic) | int shares, validator caps | n/a | Neo4j (research code) | **partial**: validator + constraints + stop/TP | decision tape (intent vs post-gate, driver) | admits non-determinism |
| FinRobot V2 | PydanticAI | ~5 pipeline + bull/bear/judge | typed SideCase/Verdict | none (research) | bull/bear/judge with evidence ids | artifact store | validators on numbers | audit transcripts, provenance | deterministic compute separated |
| TradingAgents-astock | LangGraph | 7 analysts + gate + debate = ~30-45 | as upstream | free text | as upstream | as upstream | none (rules in prompt) | as upstream | as upstream |

## Reusable for our system
| What | Source | How to port | License |
|---|---|---|---|
| Strict decision schema + float coercion | `TradingAgents@e8f5503:tradingagents/agents/schemas.py:33-58,146-190` | Re-implement as Pydantic `Decision`; drop "15%", "N/A", ranges to `None` rather than failing; enums only | Apache-2.0 (keep NOTICE if copying) |
| Structured-call-with-fallback | `TradingAgents@e8f5503:agents/structured.py:59-95` | On parse failure: one retry, then `HOLD/abstain`, never free-text guess | Apache-2.0 |
| Abstain-on-failure + fail-loud data errors | `ai-hedge-fund@4e1657d:hedge_fund/signals/llm_agent.py:15-18,103-123` | Same contract: LLM/parse fail -> no trade; data errors -> halt cycle | MIT |
| Prompt-hash cache storing exact prompt/response | `ai-hedge-fund@4e1657d:hedge_fund/llm/cache.py:25-48` | Key = sha256(role+model+system+user); same store used for backtest replay, shadow mode and judge re-run | MIT |
| Risk clamps + ClampEvent audit | `ai-hedge-fund@4e1657d:hedge_fund/risk/limits.py:51-102` | Port the logic to Toman: per-pair cap, gross cap; excess stays in cash | MIT |
| Recompute-and-compare validation | `ai-hedge-fund@4e1657d:hedge_fund/portfolio/validation.py:16-80` | Gate recomputes target from recorded LLM output + config and refuses on mismatch | MIT |
| Hash-chained ledger + halt on failure | `ai-hedge-fund@4e1657d:hedge_fund/paper/ledger.py`, `paper/tick.py` | JSONL decision log with `prev_hash`; any unhandled failure sets `halted` and flattens or stops | MIT |
| Fail-closed mandate check, kill-switch file, daily trade count, token budget | `Vibe-Trading@9081946:agent/src/live/enforcement.py`, `live/runtime/decision_budget.py`, `live/halt.py` | Re-implement ~100 lines: ordered checks returning first breach; `HALT` file read each tick | MIT |
| JSON-only boundary (reject tool_calls) + MAX caps + min_confidence | `AgenticTrading@0cf397c:dashboard/backend/infrastructure/llm/validator.py` | Copy the checks conceptually | OpenMDW-1.0 (verify before copying code; ideas are free) |
| Idempotency key + finite-number guards | `AgenticTrading@0cf397c:dashboard/backend/domain/runs/protocol.py` | Use `client_order_id` derived from cycle id | OpenMDW-1.0 |
| Decision tape with intent vs post-gate + `driver` | `AgenticTrading@0cf397c:dashboard/backend/domain/backtesting/decision_tape.py:47-49` | Our per-trade log row: raw LLM output, gate verdict, final order, fill, driver | OpenMDW-1.0 |
| Evidence-id grounding for bull/bear | `FinRobot@2717499:finrobot_desktop/finrobot/engine/agents/instructions/bull_agent.md` | LLM must cite `feature_id`s from the packet; code verifies ids and inlines real values into the log | Apache-2.0 |
| IS/OOS split for LLM param tuning | `FinRobot@2717499:finrobot_desktop/finrobot/engine/backtest/strategy_agent.py:34-39` | Day-1 data tune, report on held-out tail | Apache-2.0 |
| Data-health pre-gate | `TradingAgents-astock@e3981af:tradingagents/agents/quality_gate.py:34-64` | Code-only: stale candle, missing orderbook, spread too wide -> skip cycle | Apache-2.0 |
| Reflection log with benchmark-relative outcome | `TradingAgents@e8f5503:tradingagents/memory/log.py`, `memory/reflection.py:13-34` | Append closed-trade outcome (net of fees, in TMN) + 2-3 sentence lesson; feed last K lessons back | Apache-2.0 |

## Recommended design decisions for the hackathon
Constraint recap: 5,000,000 TMN, 3 days, end in TMN, fees/slippage matter, judges re-run, LLM must visibly drive decisions, deterministic gate outside LLM.

**Recommended topology: "Quant screen -> one LLM Strategist (structured) -> one LLM Critic (only on entries) -> deterministic Risk Gate -> deterministic Executor -> Reflector".**

| Stage | Type | Inputs | Output |
|---|---|---|---|
| 0. Data + features | **code** | Wallex ticker/orderbook/trades/klines for 3-6 liquid pairs (TMN and USDT quotes), fee schedule, balances, open positions | `FeaturePacket` per symbol with stable ids: `f01 ret_15m`, `f02 ret_1h`, `f03 rsi14`, `f04 atr_pct`, `f05 spread_bps`, `f06 depth_1pct_tmn`, `f07 vol_z`, `f08 regime`, `f09 est_roundtrip_cost_bps`, `f10 pos_pnl_pct`, `f11 age_min`... |
| 1. Data-health gate | **code** | packet freshness, spread, depth | skip symbol/cycle with reason code (astock quality-gate idea, code-only) |
| 2. Candidate screen | **code** | packets | shortlist <= 3 symbols (rules: liquidity, cost-to-edge ratio) + "must-evaluate" open positions |
| 3. Strategist | **LLM, 1 call/cycle** (deep tier) | shortlist packets, portfolio state, last K reflection lessons, risk budget remaining (read-only numbers), mandate text | JSON below |
| 4. Critic | **LLM, 1 call only when Strategist proposes ENTER/ADD** (quick tier) | proposal + same packets | `{verdict: approve\|reject\|reduce, objections[], cited_feature_ids[]}`; reject => no trade |
| 5. Risk Gate | **code, authoritative** | proposal, critic verdict, account state, config | ALLOW/REDUCE/DENY + `ClampEvent`s; computes final TMN size |
| 6. Executor | **code** | allowed order | limit/market order via Wallex API, idempotent `client_order_id`, status polling, cancel-on-timeout |
| 7. Position manager | **code** | open positions each tick | stop-loss, trailing stop, time stop, take-profit, forced flatten to TMN before deadline - these exits do NOT need the LLM; the LLM may *additionally* propose EXIT |
| 8. Reflector | **LLM, 1 call per closed trade** (quick tier) | trade record with net P&L TMN | 2-3 sentence lesson appended to memory file |

**Strategist output JSON (validate with Pydantic; enums only; unknown keys forbidden):**
```json
{
  "cycle_id": "2026-10-22T10:15:00Z#0042",
  "market_view": {"regime": "trend_up|range|trend_down|high_vol", "summary": "<=300 chars", "cited": ["f02","f04"]},
  "decisions": [
    {
      "symbol": "BTCTMN",
      "action": "ENTER_LONG|ADD|HOLD|REDUCE|EXIT|NO_TRADE",
      "conviction": 0.0,
      "size_bucket": "none|small|medium",
      "horizon_min": 120,
      "thesis": "<=400 chars, must reference feature ids",
      "cited_feature_ids": ["f01","f03","f09"],
      "invalidation": "<=200 chars",
      "proposed_stop_pct": 1.5,
      "proposed_take_profit_pct": 3.0
    }
  ],
  "abstain_reason": null
}
```
Rules: no spot shorting on Wallex spot (do not emit SHORT; unverified whether margin exists -> see open questions); the LLM never outputs a Toman amount or order type. Code maps `size_bucket`+`conviction` to a fraction (e.g. small=5%, medium=10% of equity), then clamps.

**What must be deterministic code (judges: 30 pts risk, 15 execution, 25 reproducibility):**
- Order size cap per trade (e.g. <= 10-15% equity), max gross exposure (e.g. <= 50% equity, rest TMN), max concurrent positions (<= 3), no all-in (explicit scoring item).
- Hard stop-loss attached at entry (code-computed from ATR or LLM proposal *clamped* to [min,max]), trailing stop, time stop, daily loss limit and max drawdown circuit breaker (halt + flatten to TMN), min net edge test (expected move > 2x round-trip fee+spread), min notional and step/tick rounding from exchange metadata, cooldown after a loss, trade-frequency cap, forced TMN flatten N hours before end, kill-switch file, API-error halt, idempotent orders, balance reconciliation each tick (Vibe-Trading "reconcile, never auto-resend").
- Verification that every `cited_feature_ids` exists in the packet, `symbol` is in the Wallex-approved list, JSON schema valid, no tool-call text; otherwise `NO_TRADE` with reason `invalid_llm_output` (ai-hedge-fund abstain pattern).
- Backtest runner, shadow mode switch, logging, hashing.

**What must be LLM (35 pts "real AI use"):** regime interpretation from heterogeneous features, choosing *whether* and *what* to trade among the shortlist, conviction and size bucket, thesis + invalidation text, critic objections, post-trade reflection that changes later prompts. Make influence demonstrable: log the LLM's raw output next to the gate's verdict for every cycle (decision-tape pattern), and run an ablation in the README ("same gate, rule-only baseline vs LLM" shown in backtest).

**Call budget** (cadence 10-15 min, 3 days ~ 288-432 cycles): 1 Strategist call per cycle always; Critic only on entries (~10-20% of cycles); Reflector per closed trade (~10-40 total). => ~1.2 calls/cycle, ~400-600 calls over 3 days, each prompt <= ~3-4k tokens (compact JSON packets, not prose reports). Latency per cycle 5-20 s. Cache hits make backtest replays free. Use a cheap/fast model for Critic+Reflector, stronger model for Strategist. Skip LLM entirely (log `driver="rule_based"`) only for mandatory stop/flatten exits.

**Determinism/reproducibility plan:** `temperature=0` (or minimal) but do not claim determinism; store `{prompt, response, model, params, feature_hash}` in a prompt-hash cache; backtest replays against recorded/historical klines using blind-ish prompts (no calendar dates in text if the model could recall the market) - copy ai-hedge-fund's `blind` idea; log is a hash-chained JSONL; seed everything else (random, numpy); pin dependency versions; one `make backtest` / `make shadow` / `make live` command; shadow mode = identical code path with `Executor` replaced by a paper broker that models fee + slippage from live orderbook.

**Per-trade decision log row (required by rules):** `ts, cycle_id, symbol, features_hash, cited_feature_ids+values, llm_raw_json, llm_model, critic_verdict, gate_verdict+clamps, final_order{side,qty,price,type,client_order_id}, exchange_response, fill{price,qty,fee}, driver(llm|rule_based|llm_fallback), prev_hash, hash`.

**Do not copy:** multi-round debates or 4+ prose analysts per symbol (cost, latency, no proven edge); LangGraph dependency (adds failure modes; a ~200-line sequential pipeline is easier for judges to audit; if the team wants a "framework" story, LangGraph from TradingAgents is the reference but costs time); persona prompts; Neo4j/MCP/A2A infrastructure; exchange rules in prompts.

## Unverified / open questions
- Actual LLM-call counts, token counts and latencies are **estimates from graph structure**; I did not run anything or measure.
- Whether TradingAgents' `get_verified_market_snapshot` meaningfully reduces hallucinated numbers: not evaluated; no repo contains an eval of hallucination rates.
- Vibe-Trading: I did not read `swarm/worker.py` output handling beyond summary extraction, nor `live/order_guard.py` internals; `check_mandate` order is from its docstring (`enforcement.py` top), not a line-by-line read. The `quantlib.risk` functions named in the prompt were not opened.
- AgenticTrading `orchestration/` runs on "hardcoded absolute conda paths" per CLAUDE.md and was not traced end to end; whether its backtest uses real fills/fees was not verified (`_run_backtest_simulation` at `finagent_orchestrator.py:442` only skimmed).
- OpenMDW-1.0 license terms (AgenticTrading) not analysed; AI-Trader has no LICENSE file despite MIT badge: treat both as "ideas only, do not copy code".
- ai-hedge-fund broker sim (`brokers/sim.py`) fee/slippage model not read.
- Wallex-specific facts (fee schedule, min notional, order types, whether margin/shorting or testnet exists, rate limits, kline endpoints) are **outside this file's scope** and were not verified here; the topology above assumes long-only spot with limit/market orders.
- No repo tests agentic debate vs a single call on performance; the claim "debate adds cost without proven edge" is my judgement from the absence of evidence in these repos, not a measured result.
