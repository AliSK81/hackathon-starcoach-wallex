# Agent skills, MCP tool design and agent-framework patterns for a trading agent

**Scope**: (a) how trading "skills" are structured and which rule sets/formulas are reusable; (b) MCP/function-tool design for read vs write tools and how to constrain writes; (c) tool-calling loop patterns and a 4-framework comparison for a reproducible, cheap, structured-output agent. Category 8. · **Researched**: 2026-10-21
**Repos+commits read** (shallow clones, read-only, nothing executed): `agiprolabs/claude-trading-skills@981e1d7` (this is the repo behind the local `trading-skills` plugin: same skill names; no `trading-skills` files exist under `C:\Users\alieb\.claude`, Glob returned nothing), `tradermonty/claude-trading-skills@cb0f3aa`, `staskh/trading_skills@b71a74f`, `atilaahmettaner/tradingview-mcp@16ba255`, `tradesdontlie/tradingview-mcp@c05b8f5`, `alpacahq/alpaca-mcp-server@2a973a0`, `SajjadKiani/wallex-mcp-server@3b64501`, `olaxbt/ai-market-maker@dd71150`, `mnemox-ai/tradememory-protocol@cb599bd`.
**Docs read**: Anthropic structured outputs (platform.claude.com/docs/en/build-with-claude/structured-outputs), Claude Agent SDK custom tools + hooks (code.claude.com/docs/en/agent-sdk/custom-tools, /hooks), PydanticAI output (pydantic.dev/docs/ai/core-concepts/output/), OpenAI Agents SDK home + models (openai.github.io/openai-agents-python/, /models/), OpenAI function calling (developers.openai.com/api/docs/guides/function-calling), LangGraph interrupts (docs.langchain.com/oss/python/langgraph/interrupts), smolagents index + secure execution (huggingface.co/docs/smolagents/...).
Wallex API details are covered by another researcher; here only tool-design quality of the Wallex MCPs. The **official** Wallex MCP (`https://api.wallex.ir/mcp`, 52 tools) is documented in [05c](05c-wallex-official-mcp.md).

## TL;DR
- A skill = `SKILL.md` (YAML `name`, `description`) + `references/` (loaded on demand) + `scripts/` (CLI, JSON out). They are *prompt/knowledge packages for a human-in-loop assistant*, not an execution engine. Reuse them as **rule sets and formulas to hard-code in our risk gate**, not as runtime dependencies (`tradermonty/.../CLAUDE.md` "Progressive Loading"; `agiprolabs/.../skills/position-sizing/SKILL.md`).
- Best directly reusable rules: sizing ladder `final = min(kelly, fixed-fractional, vol-adjusted, liquidity cap)` (position-sizing/SKILL.md:202); exit priority `hard stop > ATR trail > TP > time stop` (exit-strategies/SKILL.md:259); drawdown response table 0-5/5-10/10-15/15-20/>20% (risk-management/SKILL.md:87); fail-closed circuit-breaker contract with `TRADING_ALLOWED / COOLDOWN / HALTED` (tradermonty drawdown-circuit-breaker/SKILL.md:56).
- **No trading MCP we read enforces a server-side order cap.** Alpaca MCP has only paper/live switch (`ALPACA_PAPER_TRADE`, default true, server.py:117), toolset allowlist (`ALPACA_TOOLSETS`, server.py:129) and annotations; the official Wallex MCP also has no server-side caps (its state-changing tools only say "requires explicit user confirmation"; see 05c), and the community Wallex MCP has no limits at all and a probable bug in `place_order` (order.py:11). We must put caps in code we own, between LLM and exchange.
- Strongest pattern found for constraining writes: `mnemox-ai/tradememory-protocol` "brake" proxy: forwards read tools unchanged, evaluates every order tool against a **sealed (hash-verified) policy** (allowed symbols, max order/position notional, max daily loss, max drawdown, require protective stop, max open orders, staleness bounds, `FULL_HALT`), refuses unclassified tools, uses deterministic `uuid5(account:client_order_id)` for at-most-once (proxy/policy.py:51-110; alpaca.py:117-118,211-212).
- Counter-example for "Real AI use" (35 pts): `atilaahmettaner/tradingview-mcp` `multi_agent_analysis` is advertised as an "AI debate" but is three fixed rule sets summed into a score (multi_agent_service.py:160+); the author even relabelled roles to "(rule set)". Judges will check for exactly this; our LLM must genuinely choose among actions from evidence.
- Framework pick (opinionated): **PydanticAI or a thin custom loop on the raw provider SDK for the decision step; deterministic risk gate and executor outside the LLM; LangGraph only if we need checkpoint/replay**. Claude Agent SDK is strong for tool hooks but is a coding-agent runtime (heavier, Anthropic-model-bound); smolagents `CodeAgent` is rejected for the money path (executes LLM-written code locally by default).
- Determinism: temperature 0 + schema-constrained output + **our own decision cache keyed by `sha256(canonical_inputs + prompt_version + model_id)`**; provider-side seed support is unverified (see open questions). Log every call (inputs, raw output, gate verdict) to JSONL: that is also the mandatory per-trade decision log.
- LLM provider is custom and chosen later: design the LLM client behind an OpenAI-compatible `base_url` interface (OpenAI Agents SDK documents `AsyncOpenAI(base_url=...)`, models page).

## Findings

### 1. Skill anatomy (what the repos actually do)
| Aspect | agiprolabs | tradermonty | staskh |
|---|---|---|---|
| Layout | `skills/<name>/{SKILL.md,references/,scripts/}`, 70 skills, Solana/crypto-centric | `skills/<name>/{SKILL.md,references/,scripts/,assets/}`, ~75 skills, US-equity centric, plus `workflows/*.yaml`, `agents/*.md`, `commands/` | `.claude/skills/<name>/SKILL.md` wrapping `src/trading_skills/*.py`; **also** an MCP server `mcp_server/server.py` exposing the same functions as ~35 `@mcp.tool()` |
| Frontmatter | `name`, `description` only | `name` (must equal dir), `description` | `name`, `description`, `dependencies` |
| Progressive loading | Not stated | Explicit: metadata -> SKILL.md body -> references on demand -> scripts on demand (CLAUDE.md "Progressive Loading") | Skills call `uv run python scripts/x.py`, JSON out |
| Output contract | Mostly prose + code snippets, `--demo` flags | JSON + MD report with `schema_version`, `recommendation`, `triggered_rules[]`, `metrics{}` (drawdown-circuit-breaker/SKILL.md "Output Format") | JSON with mandatory `generated_at`, `data_delay` fields (risk-assessment SKILL.md tail) |
| Gating | None | Workflow manifests name ONE skill per step, with `decision_gate` steps and artifacts flowing between (workflows/README.md) | None |
| Relevance to us | Rule sets/formulas | **Gate/handoff pattern** (JSON verdict artifacts consumed by next step) | **MCP wrapper pattern**, dry-run default for write tools |

Take-away: a skill is documentation the model reads. Judges want "AI genuinely drives decisions", so the equivalent for us is: the LLM receives a compact, schema-bound evidence packet (features + ML probability + regime + portfolio state) and returns a typed decision; the *rules in these skills become code* in the gate.

### 2. Reusable rule sets and formulas (exact, with source)
All are conventions of the cited repos, not validated results; numbers tagged "ours" in section "Recommended design" are our adaptation.

**Sizing** (agiprolabs `position-sizing/SKILL.md`)
- Fixed fractional: `risk_amount = equity * risk_pct; units = risk_amount / |entry - stop|; value = units * entry` (l.30-35). Tiers: conservative 0.5-1%, standard 1-2%, aggressive 3-5% (l.39-43).
- Vol-adjusted: `size = base_size * target_vol / current_vol`; ATR form `units = (equity * 0.02) / ATR14` (l.69-86).
- Kelly: `f* = (p*b - q)/b`, `b = avg_win/avg_loss`; if `f* <= 0` do not trade; use 0.25x default, 0.5x only with well-measured edge (l.96-135). `kelly-criterion/SKILL.md`: need >= 50 trades for any Kelly (l.94), >= 100 for half-Kelly; use **Wilson lower bound** of win rate (l.113-125); fractions: 0.10x if < 30 trades, 0.25x for 30-100, 0.50x for 100+ (table "Recommended Fractions"); edge classes: <0 no trade, 0-0.02 no edge, 0.02-0.10 marginal, 0.10-0.20 good, >0.20 suspicious/overfit; for high-uncertainty assets cap at 5% when Kelly suggests >30%; correlated bets: `n_eff = n/(1+(n-1)*rho); scale = n_eff/n`.
- Ladder: compute Kelly, fixed-fractional, vol-adjusted, liquidity cap; **final = min of all four; the binding constraint is reported** (l.202-216). Liquidity rule of thumb: single trade <= 2% of pool liquidity, position <= 5% (l.152-158; for us read as order-book depth, see slippage).
- Portfolio caps: single position 10%, correlated exposure 25%, total exposure 50-80%, 5-10 positions (l.220-229).
- Anti-martingale multiplier: `1 - losses*0.25` floor 0.5 after losses, `1 + wins*0.25` cap 2.0 after wins (l.181-196). Opinion: skip the win-streak increase in a 3-day contest (loss control is 30 pts).

**Exits** (agiprolabs `exit-strategies/SKILL.md`)
- Every trade defines stop, take-profit and trailing before entry (l.20-22).
- ATR stop `entry - ATR14 * m`; m = 1.5 tight, 2.0 standard, 3.0 wide (l.37-50). Targets `entry + R * k` for k = 2,3,5. Chandelier `max(high[-22:]) - ATR*2.5`. Percent trail `highest*(1-trail_pct)` default 10%. Time stop: exit if `bars_since_entry > max_hold_bars and pnl <= 0`.
- Plan template with priority 1 hard stop (-20%), 2 ATR trail (2.5x, 14), 3 scaled TP at 2R/4R/8R (25% each), 4 time stop 50 bars if not profitable; "hard stop is always active and never overridden"; stop-trail activates after first TP (l.224-262).
- Mistakes table: never widen stops, avoid round-number stops, scale out (l.264+).

**Portfolio risk** (agiprolabs `risk-management/SKILL.md`)
- Drawdown halt: conservative -15%, moderate -20%, aggressive -25% (l.22-30). Daily loss stop: -3/-4/-5% (l.34-41). Weekly: -5% halve size, -7% minimum size, -10% halt.
- Response framework by drawdown: 0-5% normal; 5-10% cut size 25-50%; 10-15% minimum size; 15-20% halt new trades; >20% full stop (l.87-95). Recovery math: -20% needs +25%, -50% needs +100%.
- Loss-streak breakers: 3 losses -> size x0.5; 5 -> minimum; 7 -> halt 24 h. Volatility breaker: portfolio vol > 2x rolling average -> exposure x0.5 (l.111-130).
- Concentration: blue chip 10%, mid-cap 5%, small-cap 2%, micro 0.5%; exposure normal 50-80% deployed; drawdown >10% -> 20-30% deployed.
- Metrics code: historical VaR/CVaR 95%, max drawdown `(peak-v)/peak` (l.140-190).

**Fail-closed circuit breaker** (tradermonty `drawdown-circuit-breaker/SKILL.md`)
- Defaults: daily loss 2.0% -> HALTED until next ET weekday; 2 consecutive losing exits -> COOLDOWN 24 h; weekly drawdown 5% -> HALTED; monthly 8% -> HALTED (table l.54-59). Missing state dir => `TRADING_ALLOWED data_quality: EMPTY_STATE`; **partial/conflicting state => `HALTED`, i.e. fail closed** (l.46-48). Deterministic evaluation via `--as-of`. Output JSON with `triggered_rules[].{rule,threshold,observed,active_until}`.
- `pre-trade-discipline-gate` blocks when: entry not in written plan, stop not predefined, `actual_risk_dollars > planned_risk_dollars`, revenge window after a loss, exposure-coach says REDUCE_ONLY, breaker says COOLDOWN/HALTED; missing upstream artifacts => REVIEW_REQUIRED (l.91+). Every verdict is journaled as a JSONL row. That is the right shape for our decision log.

**Regime** (agiprolabs `regime-detection/SKILL.md`; tradermonty `crypto-regime-analyzer/SKILL.md`)
- 2x2 model: trending vs ranging x low vs high vol (l.20-28). Vol percentile: ATR14 rank over 100 bars, <25 low, >75 high. ADX > 25 trend, < 20 range. Hurst (R/S): <0.4 mean-reverting, 0.4-0.6 random, >0.6 trending (l.124+). BB-width percentile for squeezes.
- Crypto regime score 0-100 from 6 weighted components (BTC trend 25, alt breadth 20, dominance 15, funding 15, drawdown/vol 15, momentum thrust 10); zones 80-100 RISK_ON, 40-79 NEUTRAL, 0-39 RISK_OFF (l.36-55); missing components re-weighted proportionally; its own VALIDATION.md says these are "heuristic descriptive bands, not validated allocation rules". Needs CoinGecko/Binance, likely not reachable for Wallex TMN markets; reuse the idea with Wallex-only data.

**Validation** (agiprolabs `walk-forward-validation/SKILL.md`; `strategy-framework/SKILL.md`)
- Rolling vs expanding walk-forward; purge samples whose label window overlaps test; embargo >= 2x label horizon (l.60-90). Crypto windows: scalping train 3-7 d / test 1 d / embargo 2-4 h; intraday train 14-30 d / test 3-7 d / embargo 12-24 h (l.169-176). CPCV yields `C(N,k)` paths (N=6,k=2 -> 15). Deflated Sharpe: DSR < 0.95 suggests overfitting (l.110+); caveat: their `deflated_sharpe_ratio` snippet is a simplified/non-standard form, verify against Bailey and Lopez de Prado before quoting a DSR to judges.
- Strategy lifecycle: hypothesis -> template definition -> backtest (>= 100 trades, 70/30 walk-forward, include fees+slippage, report IS and OOS; l.126) -> paper >= 2 weeks or 30 trades, divergence > 25% from backtest => investigate (l.131) -> small live -> scale. Our 3-day window compresses this to: backtest -> shadow (live, no orders) -> live with small caps.

### 3. MCP tool-design patterns observed
| Server | Tools | Annotations / safety | Output shape | Verdict |
|---|---|---|---|---|
| Alpaca MCP (`src/alpaca_mcp_server`) | Auto-generated from OpenAPI via FastMCP `from_openapi()`; hand-written `place_stock_order`, `place_crypto_order`, `place_option_order` (overrides.py); generic `postOrder` deliberately excluded (toolsets.py:30) | `readOnlyHint/destructiveHint/idempotentHint/openWorldHint` set on order tools (overrides.py:65,195-200); paper default; `ALPACA_TOOLSETS` allowlist; **TrustBoundaryMiddleware** wraps every result in `{_alpaca_mcp_security:{trust,tool_name,risk,instructions}, data}` and marks news-like tools `external_text` (security.py:18-104; AGENTS.md) | structured dict; `client_order_id` documented as idempotency key for safe retry (overrides.py:107,226) | Best-in-class for injection hygiene and idempotency. **No max notional/qty, no confirm flag, no dry-run** (grep for max_order/max_notional/confirm/dry in src: no hits) |
| tradingview-mcp (atila) | ~55 read tools: `top_gainers`, `coin_analysis`, `multi_timeframe_analysis`, `backtest_strategy`, `walk_forward_backtest_strategy`, ... | All tools `ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)`; server.py is "routing layer only: validate -> delegate to service -> return" (server.py:1-8) | Stable `ErrorCode` enum (`SYMBOL_NOT_FOUND`, `UPSTREAM_RATE_LIMIT`, `NO_DATA`, `PARTIAL_DATA`, ...) and `make_error()` envelope (core/errors.py:28-80); `exception_to_envelope` | Great read-only/analysis template. Backtest tool signature is a model for our own `run_backtest` (`commission_pct=0.1`, `slippage_pct=0.05` defaults, `include_trade_log`, `n_splits<=10`, `train_ratio=0.7`; server.py:792-880). Not an execution server. The "multi-agent" tool is rule-based (see TL;DR) |
| tradesdontlie/tradingview-mcp | 84 tools controlling TradingView Desktop via Chrome DevTools Protocol | CLAUDE.md has a "Decision Tree - Which Tool When" section and `summary: true` option on `data_get_ohlcv` for compact output; README disclaims ToS risk (README l.192, 369-390) | JSON | Pattern worth copying: ship a tool-selection decision tree and compact-summary modes to save tokens. Not usable for us (needs TradingView Desktop, ToS risk) |
| staskh `mcp_server/server.py` | Same functions as skills, `@mcp.tool()` with docstring Args | Write tools default **dry-run**: `execute: bool = False` ("Default mode is dry-run - no orders are placed unless execute=True", server.py:777,791,820) | dict | Simple dry-run flag pattern; but flag is model-controllable, so enforce at gate |
| SajjadKiani/wallex-mcp-server | `get_markets`, `get_balance`, `place_order`, `get_order_status`, `cancel_order`, `health` (wallex_mcp/tools, server.py:8) | **None**: no annotations, no caps, no confirm, no dry-run, no allowlist | Pydantic models with `extra="allow"`; `OrderRequest` has `extra="forbid"` and `client_order_id` max 36 (schemas.py:149-164) | Weak reference. Issues: `place_order(order: OrderRequest)` then reads `order.get('order')` (order.py:7-11) so the declared schema and the body used disagree (likely broken as written); bare `except:` returns raw dict (order.py:15,26); new `httpx.AsyncClient` per call; header `X-API-Key` (client.py:23); only `/markets` for market data (no orderbook, trades, candles, open orders). Last push 2025-05-08, 2 stars, no license seen via `gh api` (`license` null). The hackathon's "Wallex MCP" is the official one at `https://api.wallex.ir/mcp` (05c); this community server is superseded |
| tradememory-protocol proxy ("brake") | Wraps broker MCP; forwards reads; intercepts order tools | Sealed `PolicyBundle` (`content_hash`, refuses to load if tampered; policy.py:17-44); fields at policy.py:57-109; `unclassified tool => refuse`; `FULL_HALT`; "closing a position is never blocked"; audit chain; at-most-once by `uuid5` | Verdict + reason codes | **The pattern to copy** for server-side caps |
| ai-market-maker | LangGraph agents + `RiskGuardAgent` "veto power (final say)" (src/agents/governance/risk_guard.py:106-143: `risk_score > 0.8 => VETOED`), dd stop and max leverage checks (l.210-256) | Pinned data with `sha256` manifest (`data/MANIFEST.json`) so `--csv-only` reruns match | n/a | Good reproducibility idea: ship the exact OHLCV CSVs + manifest with hashes |

### 4. What tools a trading agent needs
**Read-only (parallel-safe, `readOnlyHint=true`, no gate)**
| Tool | Args | Returns (compact) |
|---|---|---|
| `get_market_snapshot` | `symbols: list[str]` (enum of allowed) | last, bid, ask, spread_bps, 24h vol, min_notional, tick/step, data timestamp |
| `get_orderbook_depth` | `symbol`, `depth<=20` | cumulative TMN depth at +/-0.5%, +/-1%, est. slippage for 3 order sizes |
| `get_candles` | `symbol`, `tf in {1m,5m,15m,1h}`, `n<=200` | OHLCV + precomputed ATR/RSI/EMA so the LLM does not do arithmetic |
| `get_features` | `symbol`, `asof` | our engineered feature vector (same code used in backtest) |
| `get_ml_signal` | `symbol`, `asof` | `{p_up, horizon, model_version, calibration_bucket}` from our classifier |
| `get_regime` | `symbol` or market | `{trend, vol_pctile, adx, hurst, label}` |
| `get_portfolio_state` | none | equity_tmn, cash_tmn, positions[{symbol, qty, avg_cost, unrealized, stop, age}], open_orders, drawdown_pct, daily_pnl_pct, breaker_state |
| `get_risk_limits` | none | the sealed policy values in force (lets the LLM size within them) |
| `get_trade_history` | `n<=50` | last decisions + outcomes (memory; cf. tradememory `recall_memories(order="losses_first")`) |
| `run_backtest` | `strategy_id`, `from`, `to`, `fees_bps`, `slippage_bps` | metrics + `n_trades`; read-only, offline |

**Write (side effects; only reachable through the gate)**
| Tool | Constraint design |
|---|---|
| `propose_order` (what the LLM sees) | Args: `symbol` (enum), `side` (enum BUY/SELL), `order_type` (enum LIMIT/MARKET), `size_bucket` (enum {XS,S,M} mapping to risk %), `limit_price?`, `stop_price` (required for BUY), `reason`, `evidence_ids[]`, `client_order_id`. **LLM never passes absolute TMN amounts**; gate converts bucket -> qty from equity and risk limits. Returns `{verdict: APPROVED|REJECTED|RESIZED, reasons[], final_qty, order_id?}` |
| `cancel_order` | `order_id` only for orders created by this process |
| `close_position` | always allowed (cf. brake "never blocked: closing") but still logged; supports end-of-contest liquidation to TMN |
| `halt_trading` | LLM may *engage* a halt; only a human (CLI) may release it |

**Constraining write tools (ordered by strength)**
1. **Do not expose raw `place_order` to the model at all.** Alpaca does this partly: generic `postOrder` excluded, replaced by typed overrides (toolsets.py:30). We go further: model calls `propose_order`; a separate executor places the order.
2. **Server-side policy file, sealed by hash**, loaded at start; refuse to start if hash mismatch (tradememory policy.py:17-44). Fields to copy: `allowed_symbols`, `max_order_notional`, `max_position_notional`, `max_daily_loss`, `max_drawdown`, `max_open_orders`, `require_protective_stop`, `max/min_stop_distance_bps`, `max_price_deviation_bps` (default 100), `max_state_age_seconds` (120), `max_market_age_seconds` (60), `allow_position_reversal`.
3. **Unclassified tool => deny** (brake behaviour) and **fail closed on stale/missing state** (tradermonty breaker).
4. **Idempotency**: `client_order_id` mandatory; derive deterministic intent id (`uuid5`) so retry after timeout cannot double-fill (alpaca.py:117,211; Alpaca doc strings overrides.py:107). Wallex `OrderRequest` already carries `client_order_id` max 36 chars (wallex-mcp schemas.py:155-158; verify against Wallex docs).
5. **Dry-run / shadow flag at process level, not tool level** (env `MODE=backtest|shadow|live`), because a model-controlled `execute=False` argument (staskh pattern) can be set by the model. In shadow mode the executor writes the would-be order to the decision log and a simulated fill.
6. **Tool annotations are metadata, not enforcement** (Claude Agent SDK docs: "Annotations are metadata, not enforcement"; custom-tools page). Use them for parallelism/UX only.
7. **Untrusted-output envelope** for anything text from outside (news, social): Alpaca's `external_text` wrapper pattern (security.py:27-39).

### 5. Exposing our risk gate and ML model as tools
- Risk gate = a pure function `gate(proposal, portfolio_state, market_state, policy) -> Verdict` in our package. Expose it twice: (i) inside `propose_order` (authoritative), (ii) as read-only `check_order` so the LLM can pre-validate and self-correct (returns the same reasons). Same code runs in backtest, shadow and live, which is the reproducibility story.
- ML model: `get_ml_signal` returns calibrated probability + model hash + feature timestamp. Wrap with an on-disk model registry (`model_id = sha256(weights)`). In backtests, precompute signals for the whole window using walk-forward-trained models (purge+embargo above) and serve them from a table keyed by `(symbol, asof)` so LLM backtests do not leak future info.
- Claude Agent SDK route: in-process tools via `@tool(name, description, schema, annotations=...)` + `create_sdk_mcp_server(...)`, names become `mcp__{server}__{tool}`; `allowed_tools=[...]` pre-approves, `tools=[]` removes all built-ins so the model can only use ours; handlers return `{"content":[...], "is_error": True}` to compose error text (Python `@tool` forwards only `content` and `is_error`, not `structuredContent`) (custom-tools docs). A `PreToolUse` hook with `matcher="mcp__trader__propose_order"` can `deny` with `permissionDecisionReason`; "deny takes priority over defer > ask > allow" (hooks docs). Hook timeout => tool call blocked, which fails closed.
- Function-calling route (OpenAI-style): `strict: true` requires `additionalProperties: false` and every property in `required` (optional = nullable union); `tool_choice` supports `auto`, `required`, forced function, `allowed_tools`, `none`; `parallel_tool_calls=false` forces 0 or 1 tool per turn (developers.openai.com function-calling guide). Use `parallel_tool_calls=false` on the write step.
- Anthropic route: `output_config.format = {type: json_schema, schema}` for the final decision and/or `strict: true` on tools; constrained decoding => syntactically valid; limits: no `minimum/maximum`, no string length, `additionalProperties:false` required, recursive schemas unsupported, 20 strict tools max, `stop_reason: "refusal"` or `"max_tokens"` can break the schema, enum casing may change so compare case-insensitively; first call per schema pays grammar-compile latency (cached 24 h); changing `output_config.format` invalidates the prompt cache (structured-outputs doc). So: enforce numeric ranges in our gate, not in the schema.

### 6. Tool-calling loop patterns
| Pattern | Loop | When |
|---|---|---|
| A. Single-shot structured decision ("tool-less") | Code gathers evidence -> one LLM call returns `Decision` JSON -> gate -> executor | **Cheapest, most deterministic.** 1 call per symbol per cycle. Good default |
| B. ReAct tool loop (bounded) | LLM may call read tools (<= N=4 rounds), then emits `Decision` | Needed when evidence is large; cap rounds and tokens; log every call |
| C. Propose-critique (2 agents) | Analyst proposes; Risk-officer LLM critiques; gate decides | Shows "agentic" depth to judges; doubles cost; critic cannot loosen limits |
| D. Plan-execute with interrupt | LangGraph node with `interrupt()` before executor; resume with `Command(resume=...)` | Only for shadow review UX; requires checkpointer + `thread_id`; node re-executes from start on resume so pre-interrupt side effects must be idempotent (LangGraph interrupts docs) |
| E. Code-as-action (smolagents `CodeAgent`) | LLM writes Python | **Reject** for money path: local executor runs LLM code in our environment by default; docs say no local sandbox is fully secure (secure_code_execution page) |

### 7. Agent-framework comparison (for reproducible, cheap, structured-output)
All claims from the docs listed in the header; items not on the fetched pages are "not documented" and repeated in open questions.

| Criterion | Raw provider SDK loop (Anthropic/OpenAI) | PydanticAI | OpenAI Agents SDK | Claude Agent SDK | LangGraph | smolagents |
|---|---|---|---|---|---|---|
| Structured output | Anthropic `output_config.format` / strict tools; OpenAI `strict:true` | `ToolOutput` (default, schema as special output tool, `max_retries`), `NativeOutput` (model-native, not all models), `PromptedOutput` (schema in prompt; "often the least reliable") | `output_type` (not on fetched home page) | Custom tools return `content` blocks; final-answer schema not the focus | Whatever the node calls | `ToolCallingAgent` JSON or `CodeAgent` code |
| Validation + retry | Our code | `agent.output_validator` + raise `ModelRetry`; output retry budget default 1; `Agent(retries={'output': N})` or per run | Guardrails (input/output) | Hooks (`PreToolUse` deny/modify) | Conditional edges | Agent step loop |
| Determinism knobs | temperature (OpenAI doc not fetched for seed); Anthropic temperature/seed not on fetched pages | Pass model settings through to provider (not verified on fetched page) | `ModelSettings(temperature=0.1)` documented; `seed` not documented, `extra_args` may pass provider fields | Not documented on fetched pages | Checkpointer = replay of state, not of LLM randomness | Model-dependent |
| Provider flexibility | Single vendor each | Multi-provider (provider list not fetched: verify) | Responses API default; `OpenAIChatCompletionsModel(model=..., openai_client=AsyncOpenAI(base_url=...))` for any OpenAI-compatible endpoint; `set_default_openai_api("chat_completions")`; LiteLLM and any-llm adapters (beta); `set_tracing_disabled(True)` if no OpenAI key | Anthropic models | Provider-agnostic (LangChain integrations; not fetched) | LiteLLM, HF providers, Ollama, Transformers |
| HITL / approval | n/a | n/a | Guardrails | `PreToolUse` `ask`/`defer`, `canUseTool` | **`interrupt()` + checkpointer + `Command(resume=)`** | none |
| Tools via MCP | manual | yes (not fetched) | yes (not on fetched page) | **In-process MCP server**, `mcp__server__tool` naming, tool search on by default | via adapters | `ToolCollection.from_mcp` |
| Overhead / cost | Lowest; you control every token | Low | Low; built-in tracing (to OpenAI platform unless disabled) | Heaviest: coding-agent runtime with built-ins, tool-search, permission flow | Medium: graph boilerplate | CodeAgent produces long code turns |
| Fit for our tiny 3-day, auditable system | **Good** (one file, easy to review) | **Best balance**: typed outputs, validators map 1:1 to "risk gate retry" | Good if endpoint is OpenAI-compatible | Good if Anthropic is reachable and we want hooks; overkill otherwise | Good for explicit state machine + audit | Poor |

Recommended 3-way: **(1) PydanticAI `Agent(output_type=Decision)` with an `output_validator` calling the same risk gate (raise `ModelRetry` with the gate's reasons so the LLM revises once); (2) raw SDK loop as fallback if PydanticAI provider support for our endpoint is lacking; (3) Claude Agent SDK only if we want to present the system as an MCP-tool agent with hooks.** The judges' rubric ("real AI use") is satisfied by pattern A/B/C, not by a specific framework.

### 8. Cost, latency, determinism practicalities
- Token cost control: compact evidence packet (numbers, not raw candle dumps); precompute indicators; cap candle count; tool results with `summary` modes (tradesdontlie pattern); schema-constrained output (<= 150 tokens); one symbol-batch call per cycle instead of one per symbol.
- Latency: first request with a new strict schema pays grammar compilation (cached 24 h from last use; changing schema structure invalidates; changing only names/descriptions does not) (Anthropic doc). Keep schemas stable; warm up at start.
- Prompt caching: changing `output_config.format` invalidates prompt cache for that conversation (Anthropic doc); keep format constant across cycles.
- Cache for reproducibility: `decision_key = sha256(json.dumps(evidence, sort_keys=True) + prompt_version + model_id + params)`; store `(key -> raw_response)` in SQLite/JSONL; backtest and judge re-runs read the cache first. State clearly in README that live LLM outputs are non-bit-reproducible but the *recorded* decisions are replayable.
- Temperature 0 does not guarantee identical output across calls on hosted APIs; seed support unverified; hence the cache.

## Comparison table (skills repos)
| Repo | Stars/maint. (verified `gh api`) | Strength | Weakness | Use for us |
|---|---|---|---|---|
| agiprolabs/claude-trading-skills | n/a here (cloned at 981e1d7) | Dense formulas; crypto-flavoured; scripts with `--demo` | Solana-centric; guideline numbers not validated; some code simplified (DSR) | Source of formulas for gate and validation |
| tradermonty/claude-trading-skills | 3140 stars, pushed 2026-10-20, MIT | Fail-closed gates, JSON artifacts, workflows, journaling | Equity/US-calendar oriented; human-in-loop by design ("recommendation... does not enforce") | Gate/verdict schema, `--as-of` determinism, journal rows |
| staskh/trading_skills | 385 stars, pushed 2026-10-21, MIT | Skill + MCP dual exposure; dry-run default | Options/IB specific | MCP wrapper layout |

## Reusable for our system (concrete)
- `tradememory-protocol@cb599bd:src/tradememory/proxy/policy.py:17-110` policy load/seal/template -> adapt to a `policy.json` for Wallex (MIT per `gh api` of repo listing in file 12; confirm LICENSE file before copying code; at least copy the field list).
- `tradememory-protocol@cb599bd:src/tradememory/proxy/alpaca.py:117,211` deterministic intent id.
- `alpaca-mcp-server@2a973a0:src/alpaca_mcp_server/security.py:18-104` untrusted-data envelope; `overrides.py:195-230` order tool with annotations and idempotency docstrings (MIT).
- `tradingview-mcp@16ba255:src/tradingview_mcp/core/errors.py:28-80` error code enum + envelope (MIT).
- `claude-trading-skills(agiprolabs)@981e1d7:skills/position-sizing/scripts/size_calculator.py`, `risk-management/scripts/drawdown_analyzer.py` as reference implementations (read before copying; license file LICENSE.md at repo root, not inspected).
- `claude-trading-skills(tradermonty)@cb0f3aa:skills/drawdown-circuit-breaker/scripts/check_circuit_breaker.py` rule engine structure (32 KB), MIT.
- `ai-market-maker@dd71150:data/MANIFEST.json` approach for hash-pinned datasets (AGPL-3.0 per `gh api`: copy the idea, not code).

## Recommended design decisions for the hackathon
Scoring tie-ins in brackets. Numbers marked "ours" are our adaptations of the cited conventions, to be tuned in backtest; they are not claims from the repos.
1. **Architecture**: data -> features -> ML signal + regime -> evidence packet -> **LLM decision (typed)** -> deterministic risk gate -> executor -> decision log. LLM chooses among {ENTER(size_bucket, stop, target, horizon), HOLD, EXIT, REDUCE} per symbol and writes `reason` + cites `evidence_ids` [Real AI use 35, Strategy logic 40]. It must be able to disagree with the ML signal; log disagreements.
2. **Gate (code, not LLM)** [Risk 30, Loss control 30]: per-trade risk <= 1% of equity (ours; 0.5-1% "conservative" tier, position-sizing/SKILL.md:39-43), max single position 20% and gross exposure 60% (ours, tighter than the 10%/50-80% in l.220-229 because TMN pairs are few and correlated), stop mandatory on entry, min of {fixed-fractional, vol-adjusted, depth-based cap}, never all-in. Kelly only as a cap and only once >= 50 closed trades (unlikely in 3 days) so expect the Kelly term to be inactive; document that choice.
3. **Breakers** (adapted from risk-management & tradermonty): daily loss -3% => no new entries until next day; drawdown ladder: 5% => size x0.5, 8% => exits only (ours; the sourced ladder is 5/10/15/20); 3 consecutive losses => size x0.5, 5 => halt 6 h (ours; source 24 h is too long for a 3-day contest); stale data > 60 s or exchange error burst => HALT (fail closed). Release only by CLI.
4. **Exit stack** [Loss control]: hard stop (ATR 2.0x, sourced default) > trailing (Chandelier 2.5x) > scaled TP (2R/4R) > time stop. Flatten-to-TMN is an operator command (optional `end_at`); the contest counts only Toman holdings (requirements.md "Return Metric"), but the system stays end-agnostic.
5. **Tool surface**: expose only the read tools and `propose_order/cancel/close/halt` in section 4. No raw `place_order`. `MODE` env var = backtest|shadow|live; shadow must run the whole pipeline including the LLM and log would-be orders [Backtest+shadow 20].
6. **Framework**: PydanticAI or raw SDK; temperature 0; strict/JSON-schema output; decision cache; JSONL log with fields `{ts, symbol, evidence_hash, evidence, prompt_version, model_id, raw_response, parsed_decision, gate_verdict, reasons, order_id, mode}` [Reproducibility 25, per-trade log mandatory].
7. **Backtest protocol**: walk-forward with purge+embargo (embargo >= 2x label horizon), fees+slippage on, report IS vs OOS and number of trials tried; deliver `make reproduce` that replays from pinned CSVs + manifest hashes (ai-market-maker idea) and from cached LLM decisions.
8. **Avoid the rule-set-in-disguise trap**: keep the LLM prompt free of a pre-computed buy/sell score; give it features and the ML probability and require reasoning on trade-offs; keep a test showing the decision changes when evidence changes.
9. **Security**: wrap any news/social text as untrusted (Alpaca envelope); API keys only in env; withdraw permission disabled on the Wallex key (verify in Wallex docs whether key scopes exist: open question).

## Unverified / open questions
- The "Wallex MCP" in requirements.md is the official `https://api.wallex.ir/mcp` (see 05c). Its tool results beyond `initialize`/`tools/list` are unverified.
- LLM provider is custom (decided later): validate structured-output support on that endpoint when chosen (OpenAI Agents SDK docs warn feature support varies per provider).
- Whether Anthropic's API accepts `temperature`/`top_p` for the models we may use and whether any `seed` exists: the Messages API page fetched did not show sampling parameters in the portion read (page truncated); not claimed here.
- OpenAI `seed` and "system_fingerprint" behaviour: not read; do not rely on it.
- PydanticAI supported-provider list, model-settings passthrough, MCP client support: not fetched; verify before committing.
- OpenAI Agents SDK `output_type` and MCP support: not on the pages fetched.
- LangGraph provider-agnostic claim and checkpointer backends: only the interrupts page was read.
- agiprolabs license file contents (LICENSE.md) not inspected; tradermonty/staskh licenses reported MIT via the GitHub API listing.
- DSR code in `walk-forward-validation/SKILL.md:110+` appears non-standard; not verified numerically.
- Wallex order types, min notional, fee tiers, rate limits: covered in 05/05c; the community MCP's `OrderType` enum (LIMIT, MARKET, OCO, STOP_LIMIT, STOP_MARKET; schemas.py:92-97) is not confirmed against official docs.
