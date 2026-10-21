# Execution Engine Patterns (freqtrade, hummingbot, ccxt, nautilus) and the design for our Wallex engine

**Scope**: How mature trading frameworks implement order lifecycle, idempotency, partial fills, timeouts/cancel-replace, restart reconciliation, rate limiting, retry/backoff, precision rounding, fee/balance handling; distilled into a concrete execution-engine design for a 5,000,000 TMN, 3-day Wallex run, including end-of-run liquidation to Toman. · **Researched**: 2026-10-21 · **Sources** (all shallow clones, read only, never executed):
- `freqtrade/freqtrade@0db79d3` (`freqtrade/exchange/common.py`, `exchange/exchange.py`, `freqtradebot.py`, `exceptions.py`, `constants.py`, `strategy/interface.py`)
- `hummingbot/hummingbot@9af100d` (`hummingbot/connector/client_order_tracker.py`, `connector/exchange_py_base.py`, `connector/utils.py`, `core/data_type/in_flight_order.py`)
- `ccxt/ccxt@51dfc97` (`python/ccxt/base/errors.py`, `base/exchange.py`, `async_support/base/throttler.py`)
- `nautechsystems/nautilus_trader@e88439b` (`crates/model/src/orders/mod.rs`, `crates/live/src/node/config.rs`, `docs/concepts/execution/reconciliation.md`, `docs/concepts/live.md`)
- Wallex facts from `05-wallex-api-integration.md` (same folder).

## TL;DR
- All four frameworks keep a **local order object with an explicit state machine**, update it from *both* push events and periodic REST polls, and treat the **exchange as source of truth** on restart. We should do the same with a small explicit FSM (below).
- **Idempotency**: hummingbot generates the client order id *before* sending and tracks the order as `PENDING_CREATE` (`exchange_py_base.py:424-433`); nautilus does the same with `ClientOrderId`. freqtrade does not (uses exchange ids; its DB is the only record). Wallex gives us `client_id` on create and `GET/DELETE /v1/account/orders/{client_id}` -> we can adopt the hummingbot/nautilus model fully: persist intent first, send second, resolve unknowns by querying `client_id`.
- **Unknown outcome != failure**. Hummingbot never declares an order lost after one miss: `process_order_not_found` counts misses and only after `lost_order_count_limit` (default 3) moves it to a `_lost_orders` list that is still polled (`client_order_tracker.py:45,221-265`). Nautilus resolves `SUBMITTED` only after in-flight retries (default 5 checks, 5 s threshold, 2 s interval) and a targeted single-order query (`config.rs:456-466`, `reconciliation.md:797-865`).
- **Cancel races** are the classic bug: freqtrade `handle_cancel_enter` re-fetches the order after cancel and *bails out if status is still not closed/canceled*, leaving it to the next loop (`freqtradebot.py:2086-2092`); nautilus allows `Canceled -> Filled` and `PendingCancel -> Filled` transitions "real world possibility" (`orders/mod.rs:247,256`). Our FSM must allow fills after cancel requests.
- **Partial fills**: never drop; freqtrade refuses to cancel a partially-filled entry if the remaining position would be below min stake ("unexitable trade", `freqtradebot.py:2071-2079`) and falls back to wallet amount within 2 % when exiting (`_safe_exit_amount`, `:2216-2252`). We must handle dust and fee-reduced balances the same way.
- **Retry policy**: freqtrade `retrier` = 4 retries (5 for fetch_order) with quadratic backoff `(max_retries - remaining)^2 + 1` seconds only for rate-limit/retryable errors (`common.py:35-36,114-121,170-196`); `create_order` errors are mapped to Insufficient/Invalid (no blind retry), Temporary (retry), Operational (fatal) (`exchange.py:1572-1598`). Never auto-retry a create without the idempotency check.
- **Rounding**: ccxt truncates amounts and rounds prices (`base/exchange.py:6716-6732`); freqtrade rounds through the exchange precision and reserves 5 % + stoploss when computing min stake (`constants.py:25`, `exchange.py:1164-1209`). Wallex gives decimals per symbol plus `minNotional` 50,000 TMN.
- **Reconciliation on restart**: freqtrade `startup_update_open_orders` refetches every open DB order (`:573`); hummingbot `restore_tracking_states` reloads in-flight and lost orders (`client_order_tracker.py:153`); nautilus runs startup reconciliation + continuous in-flight/open-order/position checks. We implement: persist -> on start load open orders -> `GET openOrders`+`balances` -> diff -> adopt/cancel/mark.
- **End-of-run**: none of the frameworks has a built-in "liquidate everything by deadline" procedure besides freqtrade's `emergency_exit` after N exit-order timeouts (`handle_cancel_order` + `emergency_exit`, `freqtradebot.py:~1796-1843`). We design our own staged liquidation (limit-at-touch -> aggressive limit -> market) with a hard deadline and dust policy.

## Findings

### 1. Order lifecycle state machines

**hummingbot** (`core/data_type/in_flight_order.py:21-32`): `OrderState = PENDING_CREATE(0), OPEN(1), PENDING_CANCEL(2), CANCELED(3), PARTIALLY_FILLED(4), FILLED(5), FAILED(6), PENDING_APPROVAL, APPROVED, CREATED, COMPLETED`. `is_done` = state in {CANCELED, FILLED, FAILED} **or executed >= amount** (`:185-190`); `update_with_order_update` sets state only if client or exchange id matches and returns `updated` if `(exchange_order_id, state)` changed (`:327-349`); fills are keyed by `trade_id` so duplicates are ignored (`:356-371`). Orders are held in `active_orders`, `cached_orders` (recently done, for late fills) and `lost_orders` (`client_order_tracker.py:66-133`). A FILLED order update waits up to `TRADE_FILLS_WAIT_TIMEOUT = 5` s for its trade-fill messages before completing (`:36,273-282`).

**nautilus** (`crates/model/src/orders/mod.rs:199-300`): explicit transition table on `(status, event)`; invalid pairs return `OrderError::InvalidStateTransition`. States: Initialized, Denied, Emulated, Released, Submitted, Accepted, Rejected, PendingUpdate, PendingCancel, Triggered, PartiallyFilled, Filled, Canceled, Expired, Voided. Notable tolerated "real-world" transitions: `Canceled -> Filled` (`:247`), `Expired -> Filled`, `PendingCancel -> Filled/Accepted ("allow failed cancel requests")`, `Submitted -> Canceled` (IOC/FOK), `Accepted` may overtake `CancelRejected`.

**freqtrade**: DB `Order.status` mirrors ccxt `open/closed/canceled/expired/rejected` (`constants.py:133`: `CANCELED_EXCHANGE_STATES = ("cancelled","canceled","expired","rejected")`, `NON_OPEN_EXCHANGE_STATES = CANCELED + "closed"`); `ft_is_open` flag; trade-level aggregation through `update_trade_state` (`freqtradebot.py:2510`) which also calls `handle_order_fee` and `recalc_trade_from_orders`.

**ccxt**: stateless; order dict `status` in open/closed/canceled/expired/rejected; error `OrderNotFound`, `DuplicateOrderId` (`errors.py:142,158`).

### 2. Idempotent client order ids
- hummingbot: `get_new_client_order_id(is_buy, trading_pair, prefix, max_id_len)` = `prefix + "B"/"S" + base first/last char + quote first/last char + hex(tracking nonce) + md5(uname+pid+ppid)` truncated to `max_id_len` (`connector/utils.py:50-81`). The id exists before the HTTP call; failure paths transition to `FAILED` with `misc_updates={error_message,error_type}` (`exchange_py_base.py:500-525`).
- nautilus: `ClientOrderId` assigned at order construction (`Initialized`), `Submitted` event published when command sent, then `Accepted`; reconciliation looks orders up by client id.
- freqtrade: no client id; relies on returned exchange order id (so a lost create-response can orphan an order; mitigated by its fetch-open-orders-on-start). **Weakness we avoid.**
- Wallex: `client_id` is *unique or order rejected* and is the lookup key (`05-wallex-api-integration.md` §3-4) -> perfect for "send, if unsure query".

### 3. Partial fills, fees, dust
- freqtrade `handle_cancel_enter` (`freqtradebot.py:2047-2136`): if status open and `filled > 0`, compute `remaining_stake = (trade.amount + filled) * open_rate`; if `< get_min_pair_stake_amount(...)`, **do not cancel** (would create unexitable dust) and return False (`:2066-2079`). Then `cancel_order_with_result`, re-fetch up to 3x (0.5 s) when replacing, and if the order still isn't closed/cancelled -> "not cancelled", handle next iteration (`:2081-2092`). With `filled == 0` and no other open orders the trade is deleted; otherwise `update_trade_state` records the partial fill (`:2105-2132`).
- freqtrade `get_real_amount` / `handle_order_fee` (`:2650-2720`): if the fee was taken in the base asset (Binance style) the position amount is reduced by the fee; fee rate sanity check rejects fees >2 % (`fee_rate < 0.02`).
- freqtrade `_safe_exit_amount` (`:2216-2252`): before selling, refresh wallet; `wallet >= amount` -> amount; `wallet > amount*0.98` -> use wallet; else raise `DependencyException`.
- min stake: `_get_stake_amount_limit` (`exchange.py:1164-1209`) = max over cost-limit and amount-limit*price, multiplied by `margin_reserve = 1 + amount_reserve_percent` (`DEFAULT_AMOUNT_RESERVE_PERCENT = 0.05`, `constants.py:25`) and a stoploss reserve `margin_reserve/(1-|stoploss|)` clipped to [1, 1.5].
- hummingbot: `InFlightOrder.executed_amount_base/quote` accumulates `TradeUpdate`s with per-fill `fee`; filled completion requires fills (5 s grace); `is_done` also true if executed >= amount.
- nautilus: separates order events (Filled with `last_qty/last_px/commission`) and position reconciliation; mismatched positions produce synthetic MARKET reconciliation orders when `generate_missing_orders=True` (`reconciliation.md:899-900`).

### 4. Timeouts, cancel/replace
- freqtrade `manage_open_orders` (`:1772-1810`): loop over open trades/orders, `fetch_order` (skip on ExchangeError), `update_trade_state`, then if still `open` or fully cancelled: `ft_check_timed_out` (config `unfilledtimeout.entry/exit` + `unit`, default minutes; `strategy/interface.py:1734-1756`) -> `handle_cancel_order` (reason TIMEOUT) else `replace_order` (adjust price on new candle). After `exit_timeout_count` cancelled exit orders -> `emergency_exit` with `ExitType.EMERGENCY_EXIT` (`:1812-1843`) — this is a proven "escalate to market" pattern.
- Exchange stoploss (`handle_stoploss_on_exchange`, `:1637-1732`): every loop, fetch the stoploss order; if closed/triggered -> record exit; if position open and no stoploss order -> create one; if all existing are cancelled -> recreate; trailing -> cancel+replace. `stoploss_blocks_assets` option: a resting stop locks the balance so a discretionary exit must first cancel it (then `_safe_exit_amount` refreshes wallet). **Relevance to Wallex**: a `STOP_MARKET` resting order would lock coin balance (`locked` field) — must cancel before manual exit.
- hummingbot cancel: `_execute_order_cancel` (`exchange_py_base.py:~530-572`): `asyncio.TimeoutError` (order has no exchange id yet) or "order not found" exceptions -> `process_order_not_found`; cancel success -> `CANCELED` if `is_cancel_request_in_exchange_synchronous` else `PENDING_CANCEL` until the exchange confirms; `_cancel_lost_orders` loop cancels lost orders.
- nautilus in-flight checker: after exhausted retries `SUBMITTED -> REJECTED (INFLIGHT_TIMEOUT)`, `PENDING_CANCEL/UPDATE -> CANCELED` unless "retain unresolved" policy applies (`reconciliation.md:781-796`).

### 5. Restart reconciliation
- freqtrade `startup_update_open_orders` (`:573-613`): skip in dry-run; for each open order in DB -> `fetch_order_or_stoploss_order` -> `update_trade_state(send_msg=False)`; on `InvalidOrderException` log and continue; also warns on orphaned orders.
- hummingbot: `restore_tracking_states` rebuilds orders; lost orders restored into `_lost_orders` (`client_order_tracker.py:153-165`); periodic `_update_order_status` / `_update_lost_orders_status` (`exchange_py_base.py:1032-1067`); polling cadence `SHORT_POLL_INTERVAL = 5.0 s`, `LONG_POLL_INTERVAL = 120.0 s` (switched by whether recent stream messages arrived, `:41-42,1135`); balances via `_update_balances`.
- nautilus (`crates/live/src/node/config.rs:436-480`): `reconciliation=True`, `reconciliation_startup_delay_secs=10.0`, `generate_missing_orders=True`, `inflight_check_interval_ms=2000`, `inflight_check_threshold_ms=5000`, `inflight_check_retries=5`, `open_check_threshold_ms=5000` (don't act on orders touched <5 s ago), `open_check_missing_retries=5`, `open_check_open_only=True`. Rules (`reconciliation.md:797-842`): order in cache `ACCEPTED` but absent at venue -> `REJECTED` only in full-history mode and only after a **targeted single-order query**; completed (`FILLED`) orders missing are ignored; pending cancel with order not found -> unresolved.
- Take-away: three loops — fast **in-flight** loop (new/unknown orders), **open-orders** loop (diff vs exchange), **balance/position** loop (diff vs ledger) — each with its own retry budget and a "recent activity grace window".

### 6. Rate limiting and retry
- ccxt: `enableRateLimit = True`, default `rateLimit = 2000 ms` (overridden per exchange) (`base/exchange.py:117-118`); async `Throttler` leaky bucket `refillRate=1.0, capacity=1.0, delay=0.001, cost=1.0` or rolling window (`async_support/base/throttler.py:6-45`), each request `await throttle(cost)`.
- ccxt error hierarchy (`base/errors.py`): `BaseError -> ExchangeError (AuthenticationError(PermissionDenied, AccountSuspended), ArgumentsRequired, BadRequest(BadSymbol), OperationRejected(...), InsufficientFunds, InvalidOrder(OrderNotFound, OrderNotCached, OrderImmediatelyFillable, OrderNotFillable, DuplicateOrderId), NotSupported)` and `BaseError -> OperationFailed -> NetworkError (DDoSProtection, RateLimitExceeded, ExchangeNotAvailable(OnMaintenance), InvalidNonce, RequestTimeout)`, `BadResponse(NullResponse)`, `CancelPending`. Principle: **`OperationFailed` subclasses are safe to retry; `ExchangeError` subclasses are not.**
- freqtrade exceptions (`exceptions.py`): `FreqtradeException -> OperationalException(ConfigurationError) | DependencyException(PricingError, ExchangeError(InvalidOrderException(RetryableOrderError, InsufficientFundsError), TemporaryError(DDosProtection)))`. `retrier`: catches `TemporaryError, RetryableOrderError`; `count` = 4 (`API_RETRY_COUNT`) or 5 for `fetch_order` (`API_FETCH_ORDER_RETRY_COUNT`); sleeps `calculate_backoff = (max_retries - remaining)^2 + 1` s for `DDosProtection | RetryableOrderError` (so 1,2,5,10 s ...), plain Temporary errors retry immediately (`common.py:114-121,170-196`). create_order mapping: `ccxt.InsufficientFunds -> InsufficientFundsError`, `InvalidOrder -> InvalidOrderException`, `DDoSProtection -> DDosProtection`, `OperationFailed/ExchangeError -> TemporaryError`, other `BaseError -> OperationalException` (`exchange.py:1572-1598`).
- hummingbot: error handlers per context (`_handle_update_error_for_active_order`: timeout -> debug + not-found counter; other exception -> warning + counter, `exchange_py_base.py:1006-1020`).

### 7. Precision / lot-size
- ccxt: `amount_to_precision` uses `TRUNCATE`, `price_to_precision` uses `ROUND`, `cost_to_precision` TRUNCATE; default `precisionMode = DECIMAL_PLACES` (`base/exchange.py:321, 6716-6744`) — same semantics as Wallex `stepSize`/`tickSize` decimals (inferred).
- freqtrade `create_order` applies `amount_to_precision(pair, amount)` and `price_to_precision(pair, rate)` right before the call and sets order `status` to open if empty (`exchange.py:1544-1562`).
- hummingbot `_create_order` (`:400-476`): quantize price/amount, track order, reject locally if `quantized_amount < min_order_size` or `notional < min_notional_size` (state FAILED with message) **before any network call** — we copy this.

### 8. What none of them give us (Wallex-specific gaps)
- No Wallex connector in ccxt/freqtrade/hummingbot/nautilus; no private push stream via API key; no documented IOC/post-only; MARKET order auto-cancel at >2 % move or > book size; documented 20 orders/10 s.

## Reusable for our system
- Hummingbot's **three-bucket tracker** (active / cached / lost) + `order_not_found` counter + trade-id-deduplicated fills.
- Nautilus's **explicit (state,event) transition table** returning an error on illegal transitions + tolerated Canceled->Filled.
- Freqtrade's **retrier with quadratic backoff**, **unfilled timeout -> cancel -> emergency exit**, **refuse-to-cancel-if-would-create-dust**, **`_safe_exit_amount` wallet clamp (2 %)**, **min-stake reserve 5 %**.
- ccxt's **error taxonomy split (retryable `OperationFailed` vs terminal `ExchangeError`)**, leaky-bucket throttler, truncate-qty/round-price.
- Nautilus's **grace window before acting on discrepancies** (`open_check_threshold_ms=5000`) and **targeted single-order query before declaring an order gone**.

## Recommended design decisions for the hackathon

### A. Components (single Python process, asyncio, SQLite journal)
`Strategy/AI agent` -> **intent** `{symbol, side, notional_tmn or qty, limit_px, ttl_s, reason, signal_snapshot}` -> `RiskGate` (pure function, deterministic) -> `ExecutionEngine` (FSM + tracker) -> `WallexClient` -> Wallex. Everything the agent proposes and everything that happens is appended to `decisions.jsonl` / `orders` table keyed by `client_id` (also satisfies the mandatory per-trade decision log and makes manual trades identifiable).

### B. Order FSM (ours; names follow nautilus/hummingbot)
States: `INTENT` (persisted, nothing sent) -> `PENDING_SUBMIT` (id allocated, request in flight) -> `OPEN`(`NEW`) -> `PARTIALLY_FILLED` -> `FILLED` | `PENDING_CANCEL` -> `CANCELED`(may carry partial fill) | `REJECTED` (local pre-check or exchange 4xx) | `UNKNOWN` (submit/cancel outcome unknown; polled, "lost" bucket).
Transitions allowed beyond the happy path (taken from nautilus table): `PENDING_CANCEL -> FILLED`, `CANCELED -> FILLED` (late fill info), `PENDING_SUBMIT -> FILLED` (market order filled before we parsed), `UNKNOWN -> any`. Illegal transition => log + metric, never crash. Derive state from Wallex fields because the status enum is undocumented: `active==true && executedQty==0` -> OPEN; `active && 0<executedQty<origQty` -> PARTIAL; `!active && executedQty>=origQty*(1-1e-9)` -> FILLED; `!active && status contains CANCEL` -> CANCELED (record executedQty if >0); anything else -> UNKNOWN + alert.

### C. Idempotent ids and submission protocol
1. `client_id = f"{run_tag}_{symbol_short}_{side[0]}_{seq:05d}"` (charset `[A-Za-z0-9_]`, <=32 chars), `seq` persisted (monotonic across restarts; run_tag e.g. `SC1`). Before the HTTP call write row `PENDING_SUBMIT`.
2. Local pre-checks (copy hummingbot): symbol whitelisted; qty truncated to `stepSize` decimals, price rounded to `tickSize` decimals (buy: round down? choose to *not cross* the intended price: BUY price floor, SELL price ceil), `qty >= minQty`, `qty*price >= minNotional*1.05` (5 % reserve like freqtrade), free balance sufficient incl. taker-fee reserve. Failure -> `REJECTED(local)`, no request.
3. `POST /v1/account/orders` with timeout (connect 3 s, read 8 s). Outcomes:
   - 201 -> parse -> OPEN/FILLED.
   - 4xx (400/422 validation, insufficient funds) -> `REJECTED`, no retry; classify code/message into taxonomy (see D).
   - Timeout / connection reset / 5xx / 429 / unparseable -> state `UNKNOWN`; run **resolve(client_id)**: `GET /v1/account/orders/{client_id}` up to 3 tries at 0.5/1/2 s: found -> adopt; 404 on all tries -> safe to re-POST **once** with the same `client_id` (duplicate ids are rejected by the exchange so a double order is impossible); still ambiguous -> keep UNKNOWN, block new orders on that symbol, let the reconciler cross-check `openOrders`/`balances`.
4. Never reuse the same `client_id` for a different intent.

### D. Error taxonomy and retry policy (adapted from ccxt/freqtrade; Wallex codes to be filled after day-1 probing)
| Class | Examples | Action |
|---|---|---|
| `NetworkTransient` | timeouts, resets, 502/503/504, JSON parse fail | retry reads 4x with backoff `1,2,5,10 s` (freqtrade formula `(n)^2+1`); writes -> resolve(client_id) path above |
| `RateLimited` | HTTP 429 or message containing "rate", nginx 503 on hot endpoints | sleep backoff + jitter, halve request rate for 60 s, never fail the trade loop |
| `AuthFatal` | 401 code 1201 on a key we previously used, 403 | stop trading loop, flatten attempt impossible -> alert; log; exit non-zero (visible failure better than silent) |
| `InsufficientFunds` | balance error from order | refresh balances, shrink/skip intent; no retry of same size |
| `InvalidOrder` | below min notional, precision, price band, STOP condition | reject; refresh `MarketRules`; count; after 3 in a row for a symbol, quarantine symbol 15 min |
| `OrderNotFound` | 404 on get/cancel | for cancel: treat as "maybe already filled/cancelled" -> fetch history, `process_order_not_found` counter (3 strikes -> lost bucket) |
| `Unknown` | anything else | log full body, treat as transient once, then reject |
Global circuit-breaker: >=5 order-path failures within 120 s or reconciliation drift beyond tolerance -> state `HALTED_NEW_ORDERS` (still manages exits/cancels), page in logs. Execution-stability score (15 pts) = no crashes + correct orders -> **every coroutine wrapped; one failing symbol must not kill the loop; systemd/while-loop supervisor restarts within seconds and reconciles**.

### E. Rate limiting
Token buckets in `WallexClient`: `orders` 20 per 10 s documented -> configure 8 per 10 s; `reads` ~5 req/s global, depth per symbol <=1 Hz; prefer WebSocket for prices/books/trades; coalesce duplicate reads; respect server caching (`max-age=1`).

### F. Timeouts, cancel/replace, stops
- Every entry LIMIT has `ttl_s` (e.g. 20–60 s for 1-min strategies); at expiry: `GET` order; if filled -> done; if partial -> keep fill, cancel remainder only if remainder notional >= `minNotional` (or the filled part is already >= minNotional so it is sellable) — mirror of freqtrade's dust guard; else leave until filled/cancelled.
- Cancel: `DELETE /v1/account/orders/{client_id}` -> mark `PENDING_CANCEL` -> immediately `GET` to confirm (up to 3x at 0.5 s like freqtrade `replacing` loop). If the order turns out FILLED/partial, accept it (FSM allows).
- Replace = cancel (confirmed) then new `client_id`; never amend in place. Max 2 replaces then escalate: after `exit_timeout_count = 2` failed exit orders, send MARKET exit (`emergency_exit` pattern, `freqtradebot.py:1812`).
- Stops: **software stop-loss** evaluated each tick from WS/REST price -> sends MARKET (or marketable LIMIT through the book) exit. Optionally also a resting `STOP_MARKET` safety net *after* verifying it works with a minimum-size order; remember it locks the coin balance (must cancel before another sell, freqtrade `stoploss_blocks_assets`). Time stop on every position (max holding time) to bound exposure over 3 days.

### G. Reconciliation (start-up and runtime)
Persisted state (SQLite table `orders`, `fills`, `positions`, `equity_snapshots`; fsync on each write).
**Startup**: (1) load non-terminal orders; (2) `GET openOrders` (all symbols, paginate) and `GET balances`; (3) for each local non-terminal order: `GET /orders/{client_id}` -> update; (4) any exchange open order whose `client_id` has our `run_tag` prefix but not in DB -> adopt; with foreign prefix -> **do not touch, alert** (manual-trade risk: judges may inspect; we never create foreign orders); (5) compute holdings from balances vs ledger: unexplained coin balance -> reconcile via fills history `GET /v1/account/orders?from=..` and produce a `RECON` record (nautilus-style synthetic fill) so ledger = exchange; (6) only then start strategy.
**Runtime loops** (asyncio tasks): in-flight loop every 2 s (orders in UNKNOWN/PENDING_SUBMIT older than 5 s -> resolve; max 5 retries; then keep as UNKNOWN & halt symbol); open-orders loop every 10 s (diff `openOrders` vs local; if local says OPEN but exchange lacks it: ignore if touched <5 s ago, then `GET` by id, 3 misses -> lost bucket, still polled); balance loop every 15–30 s (ledger vs `balances` per asset with tolerance = fee + 0.1 %; drift -> halt that symbol + record). Poll cadence rises to 1–2 s while an order is live (hummingbot SHORT/LONG poll idea: 5 s / 120 s).
**Fees**: from `fills[]` (`fee`, `feeAsset`); if fee asset == base coin on BUY, position qty = filled - fee. Sellable qty = `min(ledger_qty, free_balance)` truncated to `stepSize` (freqtrade `_safe_exit_amount` 2 % rule: if free balance is within 2 % below ledger use free balance, else raise and reconcile).

### H. End-of-run liquidation to Toman (final value must be TMN, no coin holdings)
Timeline (3-day window; use actual official end `T_end`, which must be confirmed with organizers):
- `T_end - 6 h`: entries disabled for non-liquid markets; `T_end - 3 h`: **no new entries at all** ("flatten mode"); strategy may only exit. (An open position at the end cannot be re-evaluated, and unrealised PnL counts only in "realized terms".)
- `T_end - 90 min`: engine sets `LIQUIDATE=ON`: cancel all open orders (confirmed), refresh balances, build sell list = every non-TMN asset with `value > 0` (not only ones we opened — also include stray balances from earlier fills).
- For each asset (largest notional first), staged exit with per-stage timeout: **Stage 1** marketable-limit SELL at best bid (or 1 tick inside) for full sellable qty, TTL 20 s; **Stage 2** cancel, SELL limit at `best_bid * (1 - 0.3 %)`, TTL 20 s; **Stage 3** `MARKET` SELL (respect: auto-cancel if qty > book depth or >2 % move -> split into chunks <= 25 % of visible depth within 1 %); each stage re-reads balances, truncates qty to `stepSize`, re-checks `minNotional`. Partial fills simply reduce the remaining qty and continue.
- **Dust**: remaining value `< minNotional` (50,000 TMN = 1 % of capital) cannot be sold by a normal order (local pre-check would reject). Prevention: size buys so that (a) `qty_after_fee` truncation leaves < 1 step, (b) never leave partial remainder < min notional (rule in F). If dust remains: try (i) `OTC` instant-sell endpoint (`/docs/otc-create-order`, `otc_min_notional` 90,000 — likely higher, so no), (ii) buy a top-up and sell whole (costs 2 fees; only worth it if dust value > fees), (iii) accept and document (value counted as unrealised/holding; ask organizers whether sub-minimum dust is acceptable). Log it as a known limitation.
- Final: when all stages done, `GET balances`; assert only `TMN` (and permitted dust) remains; write `final_report.json` with equity, per-asset residuals, fees paid; stop trading loops; keep read-only reconciliation running to the official end. If any order is still `UNKNOWN`, keep resolving until terminal.
- Safety: liquidation is the same code path as normal exits (same FSM/ids/logs) so it is auditable and not a "manual trade".

### I. Testing the execution layer (for backtest+shadow 20 pts and stability 15 pts)
- `DryRunExchange` implementing `WallexClient` interface (freqtrade `create_dry_run_order`/`get_dry_market_fill_price` idea: fill LIMIT when book crosses, MARKET from depth, apply fee, precision, minNotional) used in backtest and shadow mode with identical engine code.
- Fault injection tests: timeout-after-accept, 5xx-on-create, duplicate client_id, cancel-race-fill, partial-fill-then-cancel, balance < ledger by fee, restart mid-order. Target: engine never raises past the main loop; state after restart equals exchange.
- Smoke test on day 1 with real key and minimum-notional orders (50,000 TMN) on USDTTMN: record exact error bodies/codes (fills the taxonomy table), verify decimals semantics, fee asset, MARKET payload, status enum, cancel/lookup by `client_id`.

## Unverified / open questions
- Hummingbot `_execute_order_cancel` line range (~530-572) is approximate; the exact `lost_order_count_limit` default of 3 is from `ClientOrderTracker.__init__(…, lost_order_count_limit: int = 3)` (`client_order_tracker.py:45`).
- I did not read freqtrade's `create_stoploss_order` / `fetch_stoploss_order` bodies, nautilus execution-engine Rust (`crates/execution`) or hummingbot `_update_orders_fills` implementation in detail; claims above are limited to what is quoted with line numbers.
- Which Wallex HTTP status/`code` values correspond to insufficient funds, below-min-notional, precision, duplicate `client_id`, rate limit (429?) — must be discovered empirically on day 1.
- Whether a resting STOP_MARKET locks the base balance on Wallex and how `stopPriceCondition` behaves.
- Whether `GET openOrders` includes partially-filled and stop (untriggered) orders; pagination max `per_page`.
- Official `T_end` and whether the evaluation snapshot is taken at the exact end (affects liquidation timeline), and whether sub-min-notional dust is penalised.
- Whether placing/cancelling orders at high frequency has account-level limits beyond 20/10 s.
