# Backtesting, Shadow (Paper) Mode and Backtest/Live Parity for an LLM-Driven Agent
> **Fee caveat:** fee numbers here are assumptions (Wallex publishes none in docs). Replace them with the output of `wallex_basic_get_account_fees` / `GET /v1/account/fee` before building. See [00-index](00-index.md).

**Scope**: how mature open-source engines implement candle-by-candle backtests, fee/slippage/fill models, dry-run/paper fills and backtest-live parity; how to backtest an LLM agent (cost, non-determinism, replay cache, leakage); a concrete 3-mode architecture for Wallex. · **Researched**: 2026-10-21
**Repos+commits** (shallow/blobless clones, read only, nothing executed): `freqtrade/freqtrade@0db79d3` (GPL-3.0), `jesse-ai/jesse@4fcbcdd` (MIT), `Lumiwealth/lumibot@05c04fd` (GPL-3.0), `nautechsystems/nautilus_trader@e88439b` (LGPL-3.0), `polakowo/vectorbt@dd8eb3a` (Apache-2.0 w/ Commons Clause), `kernc/backtesting.py@ca2e261` (AGPL-3.0), `QuantConnect/Lean@de116c0` (Apache-2.0), `Drakkar-Software/OctoBot@c45fdc2` (GPL-3.0/LGPL parts), `Haehnchen/crypto-trading-bot@cb95633` (MIT), `TauricResearch/TradingAgents@e8f5503` (Apache-2.0, backtest module only). Licenses are from memory of repo LICENSE files, not re-verified: treat as "re-implement the idea, do not copy code" for GPL/AGPL ones.

## TL;DR
- **Every serious engine solves "no lookahead" the same way: the decision at candle *t* only sees data up to the *close* of t, and the order fills at the *open of t+1* (or later).** Freqtrade shifts signal columns by one candle (`freqtrade/optimize/backtesting.py:554-562`, `.shift(1)`); backtesting.py fills market orders at next bar open (`backtesting/backtesting.py:919-923`); Nautilus requires bar `ts_init` = bar close so a bar is invisible until formed (`docs/concepts/backtesting/bar-execution.md`); Jesse feeds 1m candles and only exposes the higher-TF candle once complete.
- **Pessimistic intrabar ordering is the norm**: when stop and target both lie in one candle, assume the stop hit first (freqtrade `_get_close_rate_for_stoploss` L597-649 uses worst-case; backtesting.py L902 "pessimistically assume limit was hit before the stop"; Nautilus default path Open->High->Low->Close). Adopt: stop-loss wins ties; limit fill only if price trades *through* the limit, not merely touches.
- **Fee/slippage defaults are weak or absent everywhere** (freqtrade: fee from exchange worst tier, no slippage in backtest; Jesse: flat `env.exchanges.<x>.fee`, none for slippage; Lean `FeeModel` = 0; backtesting.py commission 0 / spread 0; vectorbt `fees=0, slippage=0`; Nautilus: fee model is mandatory per venue). We must set explicit numbers ourselves and be conservative.
- **The best realistic fill model for market orders is "walk the order book"** - freqtrade dry-run does exactly this in `get_dry_market_fill_price` (`exchange/exchange.py:1325-1370`) with a 5% slippage cap (L1282) and converts limit orders that cross the spread by >1% into market orders (L1272). That is the template for our Wallex shadow fill model (we can fetch Wallex depth live).
- **Only one repo runs an LLM agent inside a true backtest loop with caching: LumiBot** (`lumibot/components/agents/`). It keys a gzip-JSON replay cache on SHA-256 of {system prompt, task prompt, context, runtime context, memory state, model, reasoning effort, tool surface, simulated timestamp...} (`replay_cache.py:63-94`, `manager.py:1767-1800`, `runtime.py:2243-2275`) and its own docs warn that "Historical model knowledge can include later events even when tools respect the strategy clock" (`docsrc/agents_quickstart.rst:81`). TradingAgents' backtest is a *decision-quality grid, explicitly not a portfolio simulator* (`tradingagents/backtest.py:1-15`). So nobody gives a full answer; we assemble it.
- **Backtest/live parity**: Nautilus and LumiBot are the reference designs (same `Strategy` class, swap the engine/broker: `Strategy.backtest(...)` vs broker runner, `docs/concepts/live.md:13-20`). Nautilus defines three contexts: `Backtest` (historical data + simulated exec), `Sandbox` (real-time data + simulated exec = our shadow), `Live` (`docs/concepts/architecture.md:148-154`). We copy this exactly.
- **Backtest LLM calls once, then replay**: record `{prompt_hash -> raw response, model, params, tokens, latency}`; judges re-run with `--replay` and get bit-identical decisions with zero API cost; deterministic components (features, gate, sizing, fills) must be pure functions of the recorded inputs.
- **Statistical honesty**: a 3-day window gives maybe 10-40 trades. Backtest over a longer historical window (e.g. 30-60 days, 15m candles) with the LLM called at a coarse cadence, report trade count and bootstrap CI, and say plainly that it is not proof of edge.

## Findings

### 1. Event-driven backtest loops (candle by candle)

| Repo | Loop and anti-lookahead mechanism | Fill assumption | Cite |
|---|---|---|---|
| freqtrade | `Backtesting.backtest_loop(row, pair, current_time, trade_dir, can_enter)` per pair per candle: (1) manage open orders, (2) entries, (3) fill entry orders, (4) create exit orders, (5) process exit orders. Entry/exit signal columns **shifted by 1** so a signal on candle t acts on t+1; first row dropped; indicators computed on full frame (hence separate lookahead tool) | Market/limit entry at `row[OPEN_IDX]` of the next candle; limit price clamped into [low, high] via `min(propose_rate, row[HIGH_IDX])`; stop-loss exit at stop price unless the candle gapped through it (then open); ROI exit at computed ROI price clamped to the candle; default exit on signal at open | `optimize/backtesting.py:1519-1580` (loop), `518-572` (shift), `574-720` (close rates), `1025-1060` (entry price) |
| Jesse | Simulator steps **1-minute candles**; higher-timeframe candles are built incrementally and handed to the strategy only when closed; orders fill *inside* the 1m candle, which is split at the order price (`candle_service.split_candle`, `candle_includes_price`) so the strategy sees partial candle only up to the fill | Fill at order price if candle range includes it; opening-gap orders fill at open (`_execute_opening_gap_orders`) | `modes/backtest_mode.py:1052-1305` (`_step_simulator`), `1456-1630` (gap handling), `1630-1720` (`_simulate_price_change_effect`); `services/candle_service.py:121,125` |
| backtesting.py | `Backtest.run()` loops `range(start, len(data))`, strategy `next()` sees data sliced to `[:i+1]`; orders placed in `next()` are processed at the **next bar** in `_Broker.next()` | Market order -> next bar Open (or previous close if `trade_on_close=True`); limit filled if `low<=limit` (long); if stop and limit both hit in one bar, stop wins ("pessimistically", L902-905); SL/TP are contingent orders on next open | `backtesting/backtesting.py:855-1011`, `1339` |
| Nautilus | `BacktestEngine` replays a time-ordered stream; bars become 4 synthetic L1 updates (O,H,L,C; `bar_adaptive_high_low_ordering` optional) and resting orders match after each; strategy-submitted orders arrive only after all 4 points of that bar; bar `ts_init` must be the interval close | Matching engine with L1/L2/L3 book; fill model decides limit-touch fill probability and slippage | `docs/concepts/backtesting/bar-execution.md`, `execution-flow.md`, `fill-prices-and-matching.md` |
| vectorbt | **Vectorized**, not event-driven: `Portfolio.from_signals/from_orders` over whole arrays; lookahead is the user's job (`signals.shift(1)`); `price` default `np.inf` = close of the same bar (i.e. optimistic) | Same-bar close price (+slippage) | `portfolio/enums.py:1500-1516` (Order fields), `portfolio/nb.py:72-90,215-233` |
| Lean | `AlgorithmManager` feeds time slices; orders go through `Fill(FillModelParameters)` -> `MarketFill/LimitFill/StopMarketFill...` using `GetPrices()` (ask for buys, bid for sells) with `Security.SlippageModel` | Market buy at Ask (+slip) / sell at Bid (-slip) of the latest bar; limit fills when bar low/high crosses | `Common/Orders/Fills/FillModel.cs:59,273-345,697-760` |
| lumibot | `BacktestingBroker` advances simulated datetime; `process_pending_orders(strategy)` fills pending orders against the *next* available bar; smart-limit orders fill at **mid +/- slippage** | market -> bar price; limit/stop crossing; OCO/bracket supported | `backtesting/backtesting_broker.py:2124`, `4586-4650` |
| OctoBot | Backtest runs the *same* trading modes against an `ExchangeSimulator` fed by recorded OHLCV/trade/order-book files via `*_updater_simulator.py` channels | Limit orders create a price-hit event in `PriceEventsManager`; fill when price event fires | `packages/trading/octobot_trading/exchanges/implementations/exchange_simulator.py`; `personal_data/orders/types/limit/limit_order.py:64-96` |
| crypto-trading-bot (Haehnchen) | `typed_backtest.ts` runs strategy per candle (must be ascending order, throws otherwise) and emits signals + `BacktestTrade{entryPrice, exitPrice, profitPercent}`; **no fee/slippage/fill model** (grep finds none) | signal close price | `src/modules/strategy/v2/typed_backtest.ts:94-160` |

### 2. Fee and slippage models (exact formulas / defaults)

| Repo | Fee | Slippage | Cite |
|---|---|---|---|
| freqtrade backtest | `fee` config (schema: number, 0..0.1) else **max fee across pairs from exchange, "worst case fee (lowest tier)"**; cost on entry `amount*rate*(1+fee)`; applied at open and close | none by default (docs: "fee can help simulate slippage") | `optimize/backtesting.py:268-281`, `config_schema/config_schema.py:185-190` |
| freqtrade dry-run | `add_dry_order_fee(pair, order, "taker"/"maker")` -> `fee.cost = cost*rate`; market orders always taker | market fill price = order-book walk, capped at `worst_rate = rate*(1±0.05)`; limit crossing spread by >1% converted to market | `exchange/exchange.py:1272,1282,1307-1323,1325-1370` |
| Jesse | `order.fee = env.exchanges.<name>.fee * notional` set when not live | none | `services/order_service.py:82-86,112-116` |
| backtesting.py | `commission` float / `(fixed, relative)` / callable; `fixed + abs(size)*price*relative`; charged at open and at close; range -10%..10% | `spread` constant: `price*(1+copysign(spread,size))` | `backtesting/backtesting.py:727-760,843,1088-1103` |
| vectorbt | `Order.fees` (relative), `fixed_fees`; `reject_prob`, `size_granularity`, `min_size` | `adj_price = price*(1+slippage)` buy, `price*(1-slippage)` sell | `portfolio/enums.py:1507-1514`, `portfolio/nb.py:90,233` |
| Lean | `IFeeModel.GetOrderFee`; base `FeeModel` returns 0 USD; per-broker models (BinanceFeeModel etc.) | `ConstantSlippageModel(percent)`; `VolumeShareSlippageModel(volumeLimit=0.025, priceImpact=0.1)`: `volumeShare=min(qty/barVolume, volumeLimit)`; `slip% = volumeShare^2 * priceImpact`; `slip = slip%*refPrice` | `Common/Orders/Fees/FeeModel.cs`, `Slippage/VolumeShareSlippageModel.cs:37-80` |
| Nautilus | `MakerTakerFeeModel(maker_rate, taker_rate)` mandatory per venue (negative maker = rebate), per-instrument overrides | `FillModel`: `prob_fill_on_limit` (default 1.0), `prob_slippage` (default 0.0, one tick against order), seedable `random_seed`; book-shaped models `TwoTierFillModel` (10 units best, rest 1 tick worse), `SizeAwareFillModel`, etc.; `StaticLatencyModel(base/insert/update/delete_latency_nanos)` delays commands in sandbox | `crates/execution/src/models/fee.rs:321`, `fill.rs:166-200,286-330,671+`, `latency.rs:146-170`; `docs/concepts/backtesting/fill-models.md` |
| lumibot | `TradingFee(flat_fee, percent_fee, per_contract_fee, maker, taker)`; taker applies to market/stop, maker to limit; `cost = flat + price*qty*percent + qty*per_contract` | `TradingSlippage(amount)` absolute, summed from `buy/sell_trading_slippages`; smart limit fills mid +/- slippage | `entities/trading_fee.py:7`, `backtesting/backtesting_broker.py:2093-2119,4040-4056,4618-4640` |
| OctoBot | simulator config maker/taker fee in **percent** ("0.1" = 0.1%), deducted at simulated order completion in simulator and backtest | no explicit slippage model | `docs/content/guides/octobot-usage/simulator.md` (Fees) |

Take-away for Wallex: fees are large relative to 3-day edges; use taker fee for every market/aggressive-limit fill and add an explicit slippage term derived from depth (see design below).

### 3. Dry-run / paper / shadow mode

- **freqtrade dry-run** is the cleanest "live data, simulated fills" implementation. Bot code path is identical (`freqtradebot.py` branches on `config["dry_run"]` only at the exchange boundary: `exchange/exchange.py` L1532, 1683, 1784, 1861 `if self._config["dry_run"]`). `create_dry_run_order` (L1227) builds a ccxt-shaped order dict with id `dry_run_{side}_{pair}_{uuid4()}`, stores it in `_dry_run_open_orders`; market orders are filled instantly using the **live L2 order book** (20 levels), limit orders fill when `_dry_is_price_crossed` (live best ask <= buy limit, optionally with `allowed_diff`) is true on a later poll (`fetch_dry_run_order` L1467 -> `check_dry_limit_order_filled` L1400). Stop orders are simulated the same way. Wallet starts at `dry_run_wallet` (schema default `DRY_RUN_WALLET = 1000`, `constants.py:85`). API keys are stripped in dry-run (L274-277).
- **Nautilus Sandbox** context: real-time data + simulated execution (`architecture.md:152`); `SandboxExecutionClientConfig(venue, starting_balances, latency_model=StaticLatencyModel(...), fee_model=MakerTakerFeeModel(...))` (`docs/concepts/backtesting/execution-flow.md` "Sandbox inbound latency"). Latency is applied only to the inbound leg (submit/modify/cancel).
- **OctoBot simulator**: "simulate trades using the exact same process as with the real trading mode"; `TraderSimulator` (`exchanges/traders/trader_simulator.py`) replaces exchange responses; fills decided from exchange **last trades / price events**, portfolio persisted between runs, reset by changing starting portfolio (`docs/.../simulator.md`).
- **LumiBot**: same `Strategy` class runs via `Strategy.backtest(...)` or a broker runner (Alpaca paper etc.) (`README.md:38,212-225`).
- Last-price vs order book: freqtrade uses order book for market fills and best bid/ask for limit crossing; OctoBot uses last trade/price events (optimistic for makers); Lean uses bid/ask of last bar; backtesting.py/vectorbt use bar prices. **Order book is the only approach that models size-dependent slippage**; use it for shadow.

### 4. Backtest/live parity (single strategy, swappable broker)

- **Nautilus**: shared `NautilusKernel` (cache, portfolio, engines, trader, clock, message bus) for Backtest/Sandbox/Live (`architecture.md:156-160`); live differs only in transport, timing, reconciliation (`live.md:13-34`). Strategy code identical. Use `StrategyConfig` classes for params.
- **LumiBot**: `Strategy` lifecycle (`initialize`, `on_trading_iteration`) + `Broker` abstraction (`brokers/broker.py`) with `BacktestingBroker(Broker)` (`backtesting/backtesting_broker.py:134`). Env flag `IS_BACKTESTING` (`strategies/_strategy.py:20`).
- **Jesse**: exchange abstraction `Exchange` with `Sandbox(Exchange)` implementing `market_order/limit_order/stop_order/cancel_order` (`exchanges/sandbox/Sandbox.py`); live exchanges implement the same interface.
- **freqtrade**: parity by keeping the *bot* identical and swapping the Exchange object behavior under `dry_run`; but **backtesting is a separate engine** (`Backtesting` class re-implements trade logic), so parity is imperfect - known divergences (signal shift, ROI timing). Lesson: don't write two engines.
- **OctoBot**: exchange abstraction (`ExchangeSimulator` vs real `RestExchange`) under unchanged trading modes.

### 5. Bias-detection tooling (cheap, worth copying)
- freqtrade `lookahead-analysis` (`optimize/analysis/lookahead.py`): runs the full-range backtest, then for sampled trades re-runs with data **cut at the signal date** and compares indicator/signal values; reports `false_entry_signals`, `false_exit_signals`, `false_indicators`; skips `force_exit` trades; params `minimum_trade_amount`, `targeted_trade_amount` (L203-262). `recursive-analysis` (`recursive.py`) checks indicator values change with different startup-candle counts.
- Re-implementation for us (10 lines): `assert features(candles[:t+1]) == features(candles[:t+1+k])[t]` for random t - a unit test that proves the feature builder never reads future candles.

### 6. Backtesting an LLM-driven agent

**LumiBot replay cache (only production example)**
- `AgentReplayCache.compute_key(payload)`: normalizes (sorted keys, enums/datetimes/Decimals to JSON) -> `sha256(json.dumps(..., sort_keys=True, separators=(",",":")))` (`replay_cache.py:63-67`); file `<cache>/agent_runtime/replay/<key[:2]>/<key>.json.gz` (L69-70).
- Key payload (`manager.py:1767-1800`): `user_system_prompt, base_system_prompt, effective_system_prompt, builtin_skill_fingerprint, task_prompt, context, runtime_context (incl. simulated time), memory_state, model, reasoning_effort, tool_surface[{name,description,source,metadata}], memory_notes`, plus `max_output_tokens` only if set. Changing the model id produces a fresh run (docs `agents.rst:367`).
- Used only when `strategy.is_backtesting` (`runtime.py:2259`); on hit returns the stored result and re-runs recorded broker side effects for tools flagged `replay_on_cache` (`runtime.py:1940-1968`). Never retries a run that already touched the broker (`_attempt_touched_broker`, L2230-2240) - a good safety rule.
- Docs claim: cold six-year daily backtest with 1 tool call/bar = 20-40 min, warm = seconds (`docsrc/agents.rst:468`).
- Point-in-time tools: news tools use strategy datetime as cutoff (`docsrc/agents_builtin_tools.rst:374`); explicit warning that model weights may know the future.

**TradingAgents `backtest.py`** (`tradingagents/backtest.py`): `iter_grid(start, end, every_n_days)` caps at today; `run_backtest` runs the graph per (ticker, date) cell; scores each decision's realized and alpha return from the memory log. Docstring: "evaluates decision quality. It is not a portfolio simulator, and must not grow one" - cells are independent, no cash ledger. Point-in-time rules in `dataflows/date_window.py` (`as_of` clamps any tool date to the trade date; `in_window` drops undated items unless window reaches present). Useful: decision-quality metrics (hit rate of rating vs forward return) as a *complement* to our PnL simulation.

**Issues and mitigations (design, not repo claims)**

| Problem | Mitigation |
|---|---|
| Cost: N candles x M symbols x calls | Coarse decision cadence (e.g. every 15-30 min, only for symbols passing a cheap pre-filter), compact feature packet (<1.5k tokens), cache; estimate before run (`--dry-cost`) |
| Latency | Live: decision latency is real -> in shadow/live fill the order at price *at response time + latency*, not at decision-time price. In backtest, add `decision_latency_s` (e.g. measured median from shadow) as a delay before fill (Nautilus `StaticLatencyModel` idea) |
| Non-determinism | `temperature=0`, fixed `seed` if provider supports, structured JSON output; but **treat the recorded response as the ground truth**: replay cache keyed by sha256 of canonical prompt JSON (+model, params, prompt-template version). Store raw responses in the repo (`artifacts/llm_cache/*.jsonl.gz`) so judges replay offline |
| Knowledge-cutoff leakage | (1) strip absolute dates/ticker news from prompts, give relative times and anonymised feature IDs (ai-hedge-fund `blind` idea, noted in file 01); (2) include only numerical features (no free-text history); (3) backtest on data *after* the model's cutoff where possible (model cutoff here is June 2026 for our own model; pick a window after the chosen LLM's documented cutoff); (4) report a "shuffled/sign-flipped" control: run the same backtest with prices transformed (e.g. time-reversed or symbol-masked) - if PnL persists the LLM is leaking |
| Small sample | Many cheap decisions (every candle, HOLD included) produce many *decisions* but few *trades*; report n trades, per-trade net return after fees, win rate, bootstrap 90% CI, and max drawdown; also evaluate decision quality (forward-return by action) à la TradingAgents; walk-forward: choose prompt/params on days 1-20, report days 21-30 untouched |
| Parameter/prompt overfit | Freeze prompt template version hash before the held-out window; log it in every record |
| Prompt change invalidates cache | Include `prompt_template_version` + `schema_version` in key; changing it correctly forces fresh calls |

## Comparison table (what to copy)

| Capability | Best reference | Our choice |
|---|---|---|
| No-lookahead rule | freqtrade shift(1) / Nautilus bar `ts_init`=close | decide at close(t), fill at open(t+1)+latency |
| Intrabar ambiguity | backtesting.py pessimistic, Nautilus O-H-L-C | stop-first pessimistic; limit needs trade-through |
| Market-order slippage | freqtrade order-book walk with cap | same, on recorded/live Wallex depth; fallback `half_spread + k*sqrt(size/vol)`-style constant when no depth |
| Fee model | Nautilus `MakerTakerFeeModel`, lumibot maker/taker | `maker_bps`, `taker_bps` from config, loaded from Wallex fee schedule |
| Sandbox | Nautilus Sandbox, freqtrade dry-run | `ShadowBroker` |
| LLM replay | lumibot `AgentReplayCache` | prompt-hash JSONL cache, committed |
| Bias tests | freqtrade lookahead-analysis | feature-truncation unit test + shuffled-price control |

## Reusable for our system
- **Re-implement (do not copy GPL code)**: freqtrade `get_dry_market_fill_price` order-book walk + cap, `_dry_is_price_crossed`, fee as `cost*rate` on every fill (GPL-3.0: re-write from the description above, ~40 lines).
- **Pattern**: Nautilus three environment contexts, `FillModel` (`prob_fill_on_limit`, seeded `random_seed`), `StaticLatencyModel`; LGPL, but ideas only.
- **Pattern**: LumiBot cache-key payload list (above) and "never retry after broker touch"; GPL-3.0, idea only.
- **Pattern**: Lean `VolumeShareSlippageModel` formula `slip% = min(qty/barVolume, limit)^2 * priceImpact` as fallback when depth missing (Apache-2.0; formula is safe to reuse with attribution).
- **Pattern**: freqtrade backtest hash for result caching (`optimize/backtest_caching.py`: sha1 over config+strategy file, `.meta.json` next to results) -> our `run_manifest.json`.
- **Pattern**: TradingAgents `as_of` clamp for all tool dates (Apache-2.0) in our data layer.

## Recommended design decisions for the hackathon

### One engine, three modes (mirror Nautilus Backtest/Sandbox/Live)
```
            +-------------------- Agent core (identical code in all modes) ------------------+
Clock ----> | FeatureBuilder -> LLM Decision (client: Live | Recorded) -> RiskGate -> Sizer  |
MarketData->|                                                    |                            |
            +----------------------------------------------------|---------------------------+
                                                                 v   OrderRequest
                                            Broker (Protocol): BacktestBroker | ShadowBroker | WallexBroker
```
- `Clock`: `SimClock` (backtest, advanced by data) vs `WallClock`. Nothing in core calls `time.time()`/`datetime.now()`; everything takes `clock.now()`.
- `MarketDataFeed` (Protocol): `HistoricalFeed` (parquet/CSV of candles + optional recorded depth snapshots), `WallexLiveFeed` (REST/WebSocket). Both yield `MarketSnapshot` objects of the same shape.
- `LLMClient` (Protocol): `LiveLLM` (calls API, writes to cache) and `RecordedLLM` (reads cache by prompt hash; cache miss in `--strict-replay` = error). Mode flags: `--llm live|record|replay`.

### `Broker` interface (single, ~8 methods)
```python
class Broker(Protocol):
    def get_balances(self) -> dict[str, Balance]            # {"TMN": Balance(free, locked), "BTC": ...}
    def get_positions(self) -> list[Position]               # derived from balances * mark price
    def get_instrument(self, symbol) -> Instrument          # tick, step, min_notional_tmn, min_qty, maker/taker bps
    def get_orderbook(self, symbol, depth=20) -> OrderBook  # for gate and cost estimation
    def place_order(self, req: OrderRequest) -> OrderAck    # idempotent on client_order_id
    def get_order(self, order_id) -> OrderState
    def cancel_order(self, order_id) -> OrderState
    def poll_fills(self, since_ts) -> list[Fill]            # fills since; backtest advances sim here
```
Data classes (frozen dataclasses, JSON-serializable, Decimal for money, ints for TMN):
- `Instrument(symbol, base, quote, tick_size, step_size, min_notional, min_qty, maker_bps, taker_bps, active)`
- `Candle(ts, o, h, l, c, v)`; `OrderBook(ts, bids[(px,qty)], asks[(px,qty)])`; `MarketSnapshot(ts, symbol, candles_window, orderbook|None, ticker)`
- `OrderRequest(client_order_id, symbol, side, type{market,limit}, qty, limit_price|None, tif, decision_id)`
- `OrderAck(order_id, client_order_id, status, ts)`; `OrderState(order_id, status{open,partial,filled,canceled,rejected}, filled_qty, avg_price, fee_tmn)`
- `Fill(fill_id, order_id, ts, symbol, side, qty, price, fee, fee_asset, liquidity{maker,taker}, slippage_bps, source{sim,exchange})`
- `Balance(asset, free, locked)`, `Position(symbol, qty, avg_cost, mark, unrealized_tmn)`

`BacktestBroker` and `ShadowBroker` share one `SimulatedExchange` class (balances ledger, order matching, fee/slippage). They differ only in data source (historical vs live) and clock. `WallexBroker` wraps the real API/MCP. Result: strategy/risk code paths are byte-identical; parity bugs can only live in `SimulatedExchange` vs reality, which we measure in shadow (below).

### Wallex-specific realistic fill model (`SimulatedExchange`)
Order of precedence, all parameters in config:
1. **With order-book snapshot** (shadow, and backtest if depth was recorded): market buy walks `asks` consuming qty per level -> `avg_price`; cap at `best_ask*(1+max_slippage)` (freqtrade uses 5%; we use 1%) and reject the order if the cap is hit (the RiskGate should already block orders > `max_participation` of top-N depth, e.g. 10% of depth within 0.5%).
2. **Candle-only** (historical backtest): fill price for a market order decided at close(t): `open(t+1) * (1 +/- (half_spread_bps + impact_bps)/1e4)`, `impact_bps = k * sqrt(order_tmn / candle_volume_tmn)` clipped (k calibrated from shadow, default 10-30 bps) - the Lean volume-share idea with sqrt impact; `half_spread_bps` per symbol from recorded tickers (default conservative, e.g. 10 bps for TMN pairs; **to be calibrated**, no Wallex data verified here).
3. **Limit orders**: fill only if next candle(s) `low < limit` (buy) strictly (trade-through); queue-position haircut: fill probability `p_fill` (Nautilus `prob_fill_on_limit`, default 0.5 for touch, 1.0 for trade-through by >= 1 tick); partial fill allowed; expire after `ttl_s`. In shadow: fill when live best ask <= limit (freqtrade `_dry_is_price_crossed`).
4. **Fees**: `fee = notional * (taker_bps|maker_bps)/1e4`, charged in quote (TMN) or in base - follow Wallex's actual convention (unverified); apply on both legs; round to tick/step with exchange rounding; enforce `min_notional`.
5. **Latency**: `decision_latency_s` (measured LLM wall time in shadow; default 5-20 s) + `exchange_latency_s` (~1 s): fill price is taken from the first candle/snapshot at or after `decision_ts + latency`, not the decision snapshot.
6. **Stops**: simulated by the bot (Wallex stop order support unverified): checked each tick against candle low; fill at `min(stop, open)` for gaps (freqtrade rule), plus slippage; stop wins same-candle ties.
7. **Final liquidation**: `FlattenToTMN` at `end_ts - flatten_lead` at market with the same fill model; equity = TMN balance only. Report both the "mark" and "liquidated" equity.
8. **Reconciliation metric** (parity check): in shadow, for every simulated fill also log what the real top-of-book was at that time and `slippage_bps` vs the model; on live, compare actual Wallex fills to the model's prediction. Publish `fill_model_error_bps` in the report; this closes the loop and scores under "backtest + shadow results".

### Pipeline per mode
- **Backtest** (`make backtest`): `HistoricalFeed` -> `SimClock` steps through candles (e.g. 15m); at each decision tick build features from candles `<= t`; LLM via `RecordedLLM` (record on first run, then replay); gate; `BacktestBroker` fills on next candle(s). Window: >= 30 days, plus the three most recent days as the "mock evaluation" window; walk-forward split. Also run baselines (buy&hold in TMN, "no-LLM rule-only", random-action with the same gate) to show the LLM adds something - it directly supports "Real AI use".
- **Shadow** (`make shadow`): `WallexLiveFeed` + `ShadowBroker` + `LiveLLM`; identical gate; writes the same decision log; run >= 24 h before real trading; capture depth snapshots to `data/shadow/` (reused as realistic backtest input and for calibrating `half_spread_bps`, `k`).
- **Live** (`make live`): `WallexBroker`; same everything; additionally `kill_switch` file, error budget, reconcile balances each tick.

### Artifacts to output (all deterministic file formats; one folder per run `runs/<mode>-<utc>-<gitsha>/`)
- `run_manifest.json`: git sha, dirty flag, config hash (sha256 of resolved config), data hash(es), prompt-template hash, model id + params, python/lib versions (`pip freeze` hash), seed, mode, start/end, cache hit/miss counts, LLM tokens/cost/latency.
- `decisions.jsonl` (hash-chained; see file 09) - includes HOLD and gate rejections.
- `orders.csv`, `fills.csv` (with fee, slippage_bps, liquidity), `equity.csv` (ts, equity_tmn, cash_tmn, positions_value, drawdown), `trades.csv` (round trips: entry/exit ts, qty, net pnl TMN, fees, reason, decision ids).
- `metrics.json`: net return %, max drawdown %, #trades, win rate, avg trade, profit factor, exposure %, fees paid, turnover, per-day PnL, bootstrap CI, baseline comparisons, `fill_model_error_bps` (shadow/live).
- `report.md` + `equity.png` (generated by `make report RUN=...`).
- `llm_cache.jsonl.gz` (committed under `artifacts/` for the official backtest so judges can `--llm replay` without keys).
- `compare.py A B`: diff of two runs' decisions/fills (should be empty for replay of same run) - proof of reproducibility.

### Scoring tie-in
- Backtest+shadow 20 pts: ship the committed run folders for backtest and >= 1 shadow day, with `report.md`.
- Reproducibility 25: `make replay` yields identical `metrics.json` (assert in CI).
- Real AI use 35: baseline table shows rule-only vs LLM-driven; LLM decisions logged with cited features.
- Risk 30 + loss control 30: backtest shows the gate rejections and max drawdown; test that flatten-to-TMN works in sim.

## Unverified / open questions
- **Wallex specifics not verified** (developers.wallex.ir/docs intro page fetched only; no endpoint details): fee schedule/currency of fee, min notional, order types (stop?), depth endpoint and history (klines) availability, testnet, rate limits. The fill-model parameters above are defaults to be calibrated from recorded Wallex depth.
- Nautilus fee commission formula body (`notional*rate`) not read line by line; only the `MakerTakerFeeModel` constructor and docs.
- Lean `ImmediateFillModel` subclass details not read; relied on `FillModel.cs` method structure (market buys use `prices.Current` = Ask is inferred from `GetPricesCheckingPythonWrapper(asset, direction)`, not read in full).
- OctoBot last-trade fill logic for limit orders was traced only to `PriceEventsManager` event creation; the exact trigger comparison not read.
- LumiBot's `_replay_cached_side_effects` semantics beyond the cited lines, and how simulated timestamp enters `runtime_context`, not verified.
- Vibe-Trading backtest module could not be cloned in time (other files in this folder cite `Vibe-Trading@9081946`); not covered here. AgenticTrading not examined.
- Licenses listed are from general knowledge; verify before copying any code (we recommend re-implementation only).
- Jesse's liquidation/fee for live trading and Jesse's `Exchange` abstract method list were only partially read (`Sandbox.py`, `order_service.py`).
