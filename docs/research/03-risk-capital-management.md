# Risk and Capital Management: Sizing, Exits, Circuit Breakers, Risk Gate
> **Fee caveat:** fee numbers here are assumptions (Wallex publishes none in docs). Replace them with the output of `wallex_basic_get_account_fees` / `GET /v1/account/fee` before building. See [00-index](00-index.md).

**Scope**: Implementable risk design (sizing, stops/TP/trailing/time-stop, breakers, caps, cooldowns, fee-aware edge, min-notional, kill switch, flatten-to-Toman) for a 5,000,000 TMN / 3-day Wallex account. · **Researched**: 2026-10-21 · **Repos+commits** (shallow clones, read only, nothing executed):
freqtrade/freqtrade@0db79d3 (GPL-3.0) · hummingbot/hummingbot@9af100d (Apache-2.0) · nautechsystems/nautilus_trader@e88439b (LGPL-3.0) · jesse-ai/jesse@4fcbcdd (MIT) · agiprolabs/claude-trading-skills@981e1d7 (MIT) · tradermonty/claude-trading-skills@cb0f3aa (MIT) · staskh/trading_skills@b71a74f (MIT) · PyPortfolio/PyPortfolioOpt@a6638d2 (MIT) · skfolio/skfolio@dc704aa (BSD-3) · dcajasn/Riskfolio-Lib@7b1b26a (BSD-3 text) · polakowo/vectorbt@dd8eb3a (Apache + Commons Clause: do not copy code into a product sold).

## TL;DR
- The cheapest robust architecture is a deterministic **risk gate OUTSIDE the LLM**: the LLM proposes `{symbol, side, confidence, stop_dist, target}`; the gate sizes, caps, vetoes, and attaches exits. Nautilus does exactly this: `RiskEngine.handle_submit_order` denies orders before the execution gateway, with `TradingState` Active / Reducing / Halted (`nautilus_trader/crates/risk/src/engine/mod.rs:587`, `crates/model/src/enums.rs:2115`).
- Position size = **risk budget / (stop distance + round-trip cost)**, then clipped by hard notional caps. Jesse (`jesse/utils.py:149-187`) and Nautilus (`crates/risk/src/sizing.rs:39`, `calculate_riskable_money`) both deduct fees from the risk budget; Nautilus subtracts `2*commission_rate*risk_money`.
- Fees dominate a 3-day horizon. Wallex fee is **unverified** (docs intro page has no fee table; fetched 2026-10-21). With an assumed 0.35%/side + 0.1%/side slippage (0.9% round trip), a 2% stop / 3% target needs a 58% win rate to break even; at 0.1%/side fees it needs 48%. Enforce a **minimum-edge gate** (expected gross move >= 2.5x round-trip cost) and prefer fewer, higher-conviction trades.
- Exits: use an initial hard stop, a ratcheting trailing stop (freqtrade semantics: stop only moves up), a fixed TP (or ROI-by-time table), and a hard time stop (Hummingbot `TripleBarrierConfig.time_limit`). Evaluate stops on net-of-fee PnL (Hummingbot `get_net_pnl_pct`, freqtrade `calc_profit_ratio` includes fees).
- Circuit breakers from three independent sources agree on structure: per-trade loss cap, daily loss halt, peak-to-trough drawdown halt, consecutive-loss cooldown (freqtrade `StoplossGuard`, `MaxDrawdown`, `CooldownPeriod`; Hummingbot `max_global_drawdown_quote`; tradermonty `drawdown-circuit-breaker`: 2% daily, 2 losses/24h cooldown, 5% weekly). For a 3-day contest, compress these to hours (see config).
- Fail **closed**: tradermonty's breaker returns HALTED on incomplete/corrupt state (`SKILL.md` "Key Principles" 4). Our gate must reject when price/balance data is stale or any check raises.
- Rubric mapping: "order size cap" = `max_position_pct` + `max_gross_exposure_pct`; "stop loss" = mandatory per-order stop attached by the gate (no order passes without one); "no all-in entry" = per-position cap 25% and gross cap 60% of equity; loss control (30 pts, smaller drawdown) = soft/hard DD breakers + daily halt.
- Kelly is only an **upper bound** (quarter Kelly, Wilson lower-bound win rate, min 50 trades per agiprolabs `kelly-criterion/SKILL.md`). With 3 days of data we cannot estimate it; do not size from it.
- Flatten (operator command / kill switch; the system does not know the end time): optionally stop entries, sell all non-TMN assets to TMN, verify via balances API, log final equity. If config `end_at` is set, the same steps run on a schedule. Residual dust below min-notional is possible.
- Portfolio optimizers (Riskfolio/PyPortfolioOpt/skfolio) are overkill for 2-4 positions in 3 days; reuse only their ideas (CDaR/MDD definitions, `DiscreteAllocation` rounding, DSR). Use inverse-volatility weights.

## Findings

### 1. Position sizing methods (formulas and where implemented)
| Method | Formula | Source (verified) | Use for us |
|---|---|---|---|
| Fixed fractional risk | `notional = equity * r / (s + c)` where r=risk fraction, s=stop distance as fraction of entry, c=round-trip cost fraction | agiprolabs `position-sizing/SKILL.md` Sec.1 (`qty = risk_amount/(entry-stop)`); jesse `risk_to_size` (`jesse/utils.py:171`): `min((risk%/100*capital)/risk_per_qty*entry_price, capital)`; jesse `risk_to_qty` additionally multiplies size by `(1 - fee_rate*3)` (`utils.py:165`) | **Primary** |
| Nautilus fixed-risk | `risk_money = equity*risk - 2*commission_rate*equity*risk`; `size = risk_money / fx / (|entry-stop|/tick) / tick / multiplier`; then `hard_limit`, `units` split, `unit_batch_size` floor, `max_quantity` clip | `crates/risk/src/sizing.rs:39-160` (`calculate_fixed_risk_position_size`, `calculate_riskable_money`) | Pattern for "clip chain" |
| Volatility / ATR targeted | `size = base * target_vol/current_vol`; or `units = (equity*target_daily_vol)/ATR`; ATR stop `entry - k*ATR(14)`, k=1.5 tight, 2.0 standard, 3.0 wide | agiprolabs `position-sizing/SKILL.md` Sec.2; `exit-strategies/SKILL.md` Sec.1; tradermonty `position-sizer` mode B (`--atr-multiplier` default 2.0) | Secondary: choose stop distance s = k*ATR/price, feed into the fixed-fractional formula |
| Kelly | `f* = p - (1-p)/b`, b = avg win/avg loss; floor at 0 | tradermonty `position-sizer/scripts/position_sizer.py:122` `calculate_kelly` (also returns half-Kelly); jesse `kelly_criterion` (`utils.py:267`); agiprolabs `kelly-criterion/SKILL.md` | Cap only |
| Equal stake split | `stake = (available + tied_up)/max_open_trades`, `min(stake, available)` | freqtrade `wallets.py:347` `_calculate_unlimited_stake_amount` | Fallback |
| Constraint clip | `final = max(0, min(risk_sized, pos_cap, sector_cap))`, report binding constraint | tradermonty `position_sizer.py:142` `apply_constraints` | Port directly (log which cap bound) |

Kelly growth numbers (own arithmetic, g(c) = c(2-c) x g_max for fraction c of full Kelly, log-growth approximation): 0.25x gives 44% of max growth, 0.5x gives 75%, 1x gives 100%, 2x gives 0. agiprolabs claims "0.25x ~50%, 0.5x ~75%" (`kelly-criterion/SKILL.md` table): consistent for 0.5x. Wilson lower bound for win rate is recommended there ("Conservative Estimation") with minimum 50 trades.

Worked example (own arithmetic, equity 5,000,000 TMN, r = 0.75% = 37,500 TMN, c = 0.9%):
| Stop s | notional = 37,500/(s+0.009) | after 25% cap (1,250,000) | loss if stopped (s+c)*notional |
|---|---|---|---|
| 1% | 1,973,684 | 1,250,000 (cap binds) | 23,750 |
| 2% | 1,293,103 | 1,250,000 (cap binds) | 36,250 |
| 3% | 961,538 | 961,538 | 37,500 |
(So the cap, not the risk budget, usually binds for stops <= 2%; max single-trade loss stays <= 0.75% of equity.)

### 2. Exit logic: exact semantics
**freqtrade** (GPL-3.0, re-implement, do not copy):
- Evaluation order inside `IStrategy.should_exit` (`strategy/interface.py:1419`): exit signal, then hard stoploss / liquidation, then ROI, then trailing stop (comment "Sequence" lines ~1504-1508). `calc_profit_ratio` includes fees (`persistence/trade_model.py:1208`).
- Stop initialisation: `Trade.adjust_stop_loss(open_rate, stoploss, initial=True)` sets `stop_loss = current_price*(1-|stoploss|)` rounded up (`trade_model.py:839-879`). A later stop only replaces the stored one if it is **higher** for longs ("stop losses only walk up, never down", `:886`); `is_stop_loss_trailing=True` is set when it moves.
- Trailing (`interface.py:1524` `ft_stoploss_adjust`): if `trailing_stop` and not (`trailing_only_offset_is_reached` and profit < `trailing_stop_positive_offset`): if `trailing_stop_positive` is set and profit > offset, the trail distance switches to `trailing_stop_positive`; stop = high*(1-distance) via `adjust_stop_loss`. Exit type becomes `TRAILING_STOP_LOSS` when the trail is hit, else `STOP_LOSS` (`ft_stoploss_reached`, `:1605`).
- ROI table (`min_roi_reached_entry`, `:1675`): `minimal_roi` is `{minutes: min_profit}`; take the **largest key <= trade duration**; exit when `current_profit > roi`. Time-decaying profit target: e.g. `{0: 0.03, 60: 0.015, 240: 0.004, 720: 0}` (our example, not freqtrade default).
- Stake: `tradable_balance_ratio` keeps a reserve (`wallets.py:314` `get_total_stake_amount`: `(tied_up + free) * ratio`); `validate_stake_amount` (`:408`) raises tiny stakes to the exchange minimum only if the bump is <= 30% (`stake_amount * 1.3 < min_stake_amount` then trade ignored), and caps to available.

**Hummingbot** (Apache-2.0, safe to port ideas/code with attribution):
- `TripleBarrierConfig` (`strategy_v2/executors/position_executor/data_types.py:32`): `stop_loss`, `take_profit` (fractions of entry), `time_limit` (seconds, int), `trailing_stop=TrailingStop(activation_price, trailing_delta)`, order types (time-limit and stop-loss **must** be market orders, validated at `:52`). `new_instance_with_adjusted_volatility(volatility_factor)` (`:56`) scales SL/TP/trailing by a volatility factor but not time_limit.
- Barrier loop `control_barriers` (`position_executor.py:461`): only after the entry order is filled and filled size >= `min_order_size` and quote value >= `min_notional_size` it runs SL, trailing, TP; the time limit runs always (also cancels unfilled entries).
- Conditions are on **net** PnL: SL if `net_pnl_pct <= -stop_loss` (`:519`), TP if `net_pnl_pct >= take_profit` (`:530`), `net_pnl_pct = net_pnl_quote / open_filled_amount_quote` (`:270`).
- Trailing (`:782`): arms when `net_pnl_pct > activation_price`, then `trigger = pnl - trailing_delta`; every tick, if `pnl - delta > trigger` it ratchets; exit when `pnl < trigger`. Pure ratchet in PnL space, simple to unit-test.
- Close = market order for `amount_to_close` if >= `min_order_size` (`place_close_order_and_cancel_open_orders`).

**agiprolabs exit-strategies** (MIT): "three exits defined before entry" (stop, TP, trail); ATR stop `entry - 2*ATR`; Chandelier `highest_high(22) - 2.5*ATR`; time stop `bars_since_entry > max_hold_bars and pnl <= 0`; time guidelines scalp 5-15 min, day trade 4-8 h; volume-collapse exit (`recent_vol(10) < 0.3 * baseline(50)`).
**staskh/trading_skills** (MIT): IBKR/options oriented; only reusable idea is `calc_trail_reference` = `max(current_price, avg_cost)` as trail anchor (`broker/trailing_stop.py:32`). Not otherwise relevant.

### 3. Drawdown circuit breakers and cooldowns
- freqtrade protections (`plugins/protections/`; all inherit `IProtection` with `stop_duration`/`stop_duration_candles` default 60 min and `lookback_period` default 60 min, `iprotection.py:41-53`):
  - `StoplossGuard` (`stoploss_guard.py:21-24`): `trade_limit` default 10, `required_profit` 0.0, `only_per_pair`, `only_per_side`; counts exits of type STOP_LOSS / TRAILING_STOP_LOSS / STOPLOSS_ON_EXCHANGE / LIQUIDATION with `close_profit < required_profit` in the lookback; if count >= limit, locks all pairs (global) until `max(close_date) + stop_duration`.
  - `MaxDrawdown` (`max_drawdown_protection.py:23-25`): `trade_limit` 1, `max_allowed_drawdown` 0.0, `calculation_mode` "ratios" (cumulative profit ratios) or "equity" (relative to account balance incl. profit before the window); global lock if drawdown > limit.
  - `CooldownPeriod`: per-pair lock `stop_duration` after any closed trade on that pair (`cooldown_period.py:_cooldown_period`).
  - `LowProfitPairs` (`low_profit_pairs.py:20-22`): per-pair lock if summed `close_profit` over >= `trade_limit` trades is below `required_profit`.
  - Protections only block **new entries**; they do not close open positions.
- Hummingbot `scripts/v2_with_controllers.py`: `max_controller_drawdown_quote` stops a controller when `peak_pnl - pnl > limit` (`:54`); `max_global_drawdown_quote` stops the whole strategy (`:76`); `manual_kill_switch` per controller (`:104`). Controller entry gating: `can_create_executor` (`directional_trading_controller_base.py:185`): `max_executors_per_side` default 2 and `cooldown_time` default 300 s since last executor on that side; default `total_amount_quote/price/max_executors_per_side` per executor (`:177`).
- tradermonty `drawdown-circuit-breaker` defaults: max daily loss 2.0%, losing streak 2 -> COOLDOWN 24 h, weekly 5.0%, monthly 8.0%; realized P&L only; fail-closed on partial state.
- agiprolabs `risk-management`: drawdown response ladder 0-5% normal, 5-10% size -25-50%, 10-15% minimum size, 15-20% halt new, >20% full stop; daily loss limits 3/4/5% (conservative/moderate/aggressive); consecutive-loss multiplier: >=3 losses x0.5, >=5 x0.25, >=7 halt; counter resets after 2 consecutive wins; combine breakers with the most restrictive multiplier (`references/circuit_breakers.md`, `effective_size_multiplier`). Recovery math: -10% needs +11.1%, -20% needs +25%.
- Nautilus `RiskEngineConfig` (`crates/risk/src/engine/config.rs`): `bypass` false, `max_order_submit` 100/1s, `max_order_modify` 100/1s (throttlers), `max_notional_per_order: {instrument: Decimal}` (must be > 0), `full_position_exit_venues`. Checks: price/quantity precision, GTD expiry, notional cap, cash-balance check for sells, **reduce-only enforcement** and `TradingState::Reducing` (only cancels and reduce-only submissions allowed) vs `Halted` (only cancels/queries). `Reducing` is the right state after a hard breaker: allows flattening, forbids new risk.

### 4. Portfolio libraries (only sizing/risk-relevant parts)
- PyPortfolioOpt `discrete_allocation.DiscreteAllocation(weights, latest_prices, total_portfolio_value)` with `greedy_portfolio()` / `lp_portfolio()` converts weights to whole units and returns leftover cash (`pypfopt/discrete_allocation.py:42,158`). Idea reusable for exchange step sizes; we can do it in 10 lines.
- Riskfolio `riskfolio/src/RiskFunctions.py`: `MDD_Abs` (:825, uncompounded cumulative max drawdown), `CDaR_Abs` (:987), `EDaR_Abs` (:1050), `UCI_Abs` (:1161), `CVaR_Hist` (:366). Definitions only; optimisation unnecessary at 2-4 positions.
- skfolio `measures/_measures.py`: `get_drawdowns` (:864), `max_drawdown` (:955), `cdar` (:1000), `probabilistic_sharpe_ratio` (:1302), `deflated_sharpe_ratio` (:1383). Used in file 11.

## Comparison table
| Capability | freqtrade | Hummingbot | Nautilus | Jesse | agiprolabs / tradermonty skills |
|---|---|---|---|---|---|
| Risk-based size | no (stake amount) | no (`total_amount_quote`) | `calculate_fixed_risk_position_size` | `risk_to_qty` | yes (formulas) |
| Pre-trade veto | protections (entries only) | `validate_sufficient_balance` | RiskEngine (notional, balance, reduce-only) | none | pre-trade gate (advisory) |
| Stop semantics | ratchet-up, fee-aware | net-PnL based, market close | order-type based | strategy-defined | formulas |
| Trailing | offset + positive distance | activation + delta | native order types | strategy | % / ATR / Chandelier / EMA |
| Time stop | ROI table by minutes | `time_limit` seconds | n/a | n/a | bars-based |
| DD breaker | `MaxDrawdown` | `max_*_drawdown_quote` | none built in (state machine only) | none | daily/weekly/monthly + streak |
| Kill switch | `/stop`, lock | `manual_kill_switch` | `set_trading_state(Halted)` | n/a | n/a |
| License risk for copying | GPL-3.0 | Apache-2.0 | LGPL-3.0 | MIT | MIT |

## Reusable for our system
- Re-implement (no code copy needed, all short): freqtrade ratchet-up stop and ROI-by-minutes table (GPL: re-implement from semantics above); Hummingbot triple-barrier with net-PnL checks and trailing ratchet (Apache-2.0: port with attribution); Nautilus state machine Active/Reducing/Halted and riskable-money formula (LGPL: re-implement); tradermonty `apply_constraints` "strictest cap wins + report binding constraint" (MIT, port) and fail-closed rule; agiprolabs `effective_size_multiplier` min-combination of breakers (MIT, port) and `ConsecutiveLossBreaker` ladder.
- Skip: Riskfolio/PyPortfolioOpt/skfolio optimizers; staskh (options/IBKR); freqtrade/Hummingbot as runtime frameworks (assumes ccxt-supported exchanges; Wallex adapter would cost days).

## Recommended design decisions for the hackathon

### A. Config (all in one `risk.yaml`, loaded and logged at start). Assumes fee_rate = 0.35%/side and slippage = 0.10%/side until Wallex fee tier is verified; the gate reads real fee from API/config.
| Key | Default | Justification (equity E = 5,000,000) |
|---|---|---|
| `equity_start_tmn` | 5,000,000 | contest capital |
| `fee_rate_per_side` | 0.0035 (ASSUMPTION) | round trip 0.70% |
| `slippage_per_side` | 0.0010 | spread + impact for small TMN sizes; measure in shadow mode |
| `risk_per_trade_pct` | 0.75% (37,500 TMN) | 8 consecutive max losses = 6% (below kill switch) |
| `max_position_pct` | 25% (1,250,000) | no single coin > 1/4 of equity; "no all-in" |
| `max_gross_exposure_pct` | 60% (3,000,000) | >= 40% always in TMN |
| `max_open_positions` | 3 | 3 x 25% = 75% > 60% so the gross cap binds |
| `min_order_notional_tmn` | max(exchange_min, 100,000) (exchange min UNVERIFIED) | below that fees/rounding dominate; also avoids dust |
| `min_edge_ratio` | 2.5 | expected gross move >= 2.5 x round-trip cost (0.9% -> >= 2.25%) |
| `min_rr_net` | 1.3 | (TP - cost)/(SL + cost) |
| `stop_loss_pct` | clamp(k*ATR/price, 1.0%, 3.0%), k=2.0 | LLM may propose, gate clamps |
| `take_profit_pct` | >= 1.5 x stop, default 3.0% | BE win rate at s=2%,t=3%,c=0.9% is 58%; at t=4% is 48.3% (own arithmetic) |
| `trailing_activation_pct` / `trailing_delta_pct` | 1.5% / 0.8% (net) | ratchet per Hummingbot semantics |
| `time_stop_minutes` | 360 (flat-ish trade) / hard 720 | frees capital; matches "day trade 4-8h" |
| `daily_loss_halt_pct` | 2.0% (100,000) | tradermonty default 2.0%; halts new entries until next UTC day |
| `dd_soft_pct` / size mult | 2.5% from peak -> x0.5 | agiprolabs ladder compressed |
| `dd_hard_pct` | 4.0% from peak -> Reducing + 6 h pause | |
| `kill_switch_pct` | 6.0% below start (4,700,000) or 5% below peak-after-profit -> flatten, HALT until end | caps worst-case loss; loss-control score |
| `consec_loss_cooldown` | 3 losses -> 45 min pause, x0.5 size; 5 -> x0.25; reset after 2 wins | agiprolabs ladder; freqtrade StoplossGuard analogue |
| `pair_cooldown_min` | 30 after any exit; 120 after a stop-out | freqtrade `CooldownPeriod`; avoids re-buying a falling coin |
| `max_orders_per_min` | 10 | Nautilus throttler analogue; protects execution-stability score |
| `max_data_age_s` | 20 | stale price -> reject (fail closed) |
| `entry_cutoff_hours_before_end` | 6 | then only exits |
| `flatten_start_hours_before_end` | 2 | flatten procedure below |
| `kelly_cap_fraction` | 0.25 | cap of risk fraction, enabled only after >= 50 closed trades |

Cost drag arithmetic (own): each 1,250,000 TMN round trip costs 0.9% = 11,250 TMN. 10 trades = 112,500 = 2.25% of equity; 20 trades = 4.5%; 40 trades = 9%. Activity (15 pts) rewards "regular, reasonable" trading over 3 days, so target ~4-8 trades/day, not scalping, unless real fees are low.

Worst-case checks: single-trade max loss = risk 0.75% (stops fill with slippage, gap risk: allow 1.5x => 1.1%). Gross cap 60% with all stops at 2% = 1.2% + costs 0.5% = 1.7% loss in a simultaneous stop-out of everything; below dd_hard 4%.

### B. Risk gate spec (ordered checks; first failure rejects and logs `reason_code`)
1. `STATE`: gate state in {ACTIVE, REDUCING, HALTED}; HALTED rejects all but cancels; REDUCING allows only reduce-only/exit orders.
2. `DATA`: price age <= `max_data_age_s`, balance snapshot fresh, instrument in Wallex-approved list (hard constraint in requirements).
3. `BREAKERS`: daily loss, DD soft/hard/kill, consecutive-loss, pair cooldown, entry cutoff time (update state, set size multiplier).
4. `THROTTLE`: orders/min and open-order count.
5. `EDGE`: `expected_gross_move >= min_edge_ratio * round_trip_cost` and net R:R >= `min_rr_net`.
6. `STOP`: order must carry a stop; clamp stop distance to [1%, 3%]; compute TP/trail/time-stop if the LLM omitted.
7. `SIZE`: `n = equity*risk_pct*mult/(s+c)`; clip by `max_position_pct`, `max_gross_exposure_pct - current_gross`, free TMN balance x 0.98, optional Kelly cap; floor to exchange step size.
8. `MIN_NOTIONAL`: if `n < min_order_notional` reject (never round up beyond +30%, freqtrade `validate_stake_amount` rule).
9. `NO_ALL_IN`: assert `n <= 25% equity` and post-trade gross <= 60% (redundant assertion).
10. `LOG`: write full decision record (inputs, each check result, final size) before sending; fail closed on any exception.

```python
def gate(intent, acct, cfg, now):
    try:
        st = update_state(acct, cfg, now)            # breakers -> ACTIVE/REDUCING/HALTED, size_mult
        if st.mode == "HALTED" or (st.mode == "REDUCING" and not intent.reduce_only):
            return deny("STATE")
        if intent.reduce_only:                        # exits always pass if qty <= position
            return allow(min(intent.qty, acct.pos(intent.sym)))
        if now - acct.px_ts(intent.sym) > cfg.max_data_age_s or intent.sym not in cfg.allowed:
            return deny("DATA")
        if now.hours_to_end < cfg.entry_cutoff_h or cooldown_active(intent.sym, st, now):
            return deny("COOLDOWN")
        if acct.orders_last_min >= cfg.max_orders_per_min or len(acct.positions) >= cfg.max_open_positions:
            return deny("THROTTLE")
        c = 2 * (cfg.fee + cfg.slip)                  # round-trip cost fraction
        s = clamp(intent.stop_pct or 2 * atr_pct(intent.sym), 0.010, 0.030)
        tp = max(intent.tp_pct or 0.03, 1.5 * s)
        if intent.expected_move < cfg.min_edge_ratio * c or (tp - c) / (s + c) < cfg.min_rr_net:
            return deny("EDGE")
        n = acct.equity * cfg.risk_pct * st.size_mult / (s + c)
        n = min(n, cfg.max_pos_pct * acct.equity,
                cfg.max_gross_pct * acct.equity - acct.gross, 0.98 * acct.free_tmn)
        if cfg.kelly_enabled(acct):                   # >= 50 closed trades
            n = min(n, cfg.kelly_cap * kelly(acct.stats) * acct.equity / s)
        qty = floor_to_step(n / intent.price, intent.sym.step)
        if qty * intent.price < max(cfg.min_notional, intent.sym.min_notional):
            return deny("MIN_NOTIONAL")
        assert qty * intent.price <= cfg.max_pos_pct * acct.equity + 1   # no all-in
        return allow(qty, stop=intent.price * (1 - s), tp=intent.price * (1 + tp),
                     trail=(cfg.trail_act, cfg.trail_delta), time_stop=cfg.time_stop_min)
    except Exception as e:                            # fail closed
        return deny("GATE_ERROR:" + repr(e))
```

### C. Exit manager (runs every tick independent of the LLM, reduce-only market/aggressive-limit orders)
Order each tick: kill switch/flatten schedule, hard stop (net PnL <= -s), trailing (Hummingbot ratchet: arm at +1.5%, trail 0.8%), take profit, time stop, then (optional) LLM "exit" suggestion (can only tighten or exit, never widen stops). The LLM can close early or tighten a stop; it cannot loosen a stop or raise size: this keeps "AI drives decisions" (entries/exits timing) while risk stays deterministic.

### D. Kill switch and flatten-to-Toman
**Scope decision: the system is end-agnostic.** It does not know the hackathon end time or what counts as final holdings. The flatten procedure below is an operator-triggered command (`flatten`, or the kill switch) with optional config `end_at`; it is never assumed. The T-offsets below apply only when `end_at` is configured; otherwise run steps 2 onward on the `flatten` command.
1. T-6h: `entry_cutoff`; no new entries. T-2h: tighten trailing delta to 0.4%, time stops to 30 min.
2. T-60 min: cancel all resting orders; sell all non-TMN assets (limit at best bid, 3 retries at 20 s each, then market-equivalent aggressive limit through the book); loop until every non-TMN balance is below min-notional.
3. T-15 min: re-read balances via API; any remaining coin or USDT balance is force-sold; USDT->TMN conversion via USDT/TMN market (ASSUMPTION: requirements say "no coin-denominated holdings", USDT likely counts).
4. Write `final_equity.json` (balances, marks, equity, return % per requirement formula) and stop the engine; engine refuses to start orders after T-0 (gate state HALTED).
5. Kill switch (`kill_switch_pct` hit or manual file flag `KILL` present or 3 consecutive API errors): set REDUCING, cancel all, run steps 2-4 immediately, then HALTED. Manual flag is operational control, not a manual trade (log it).
Dust: balances below exchange min-notional cannot be sold; keep the entry `min_order_notional` high enough that rounding leaves less than ~0.1% of equity as dust (unverified how Wallex handles dust).

### E. Rubric mapping
| Judge item | Where shown |
|---|---|
| Order size cap | `max_position_pct`, `max_gross_pct`, `max_orders_per_min`; logged `binding_cap` per order |
| Stop loss | mandatory per-order stop, clamp 1-3%, trailing, time stop; stop-hit rows in decision log |
| No all-in | 25% / 60% assertions; >= 40% TMN reserve line in report |
| Loss control (30) | DD ladder, daily halt, kill switch; report max drawdown and breaker activations |
| Execution stability (15) | throttle, fail-closed gate, idempotent order ids, retry logic |
| Reproducibility | `risk.yaml` committed, deterministic gate unit tests (golden cases) |

## Unverified / open questions
- Wallex fee schedule (maker/taker, tier), minimum order value per market, step/tick sizes, dust handling, order types (market? limit? stop-limit?), rate limits: https://developers.wallex.ir/docs intro page contains none of these; need the API reference pages. All fee-dependent numbers above assume 0.35%/side and must be recomputed.
- USDT handling at flatten: configurable (`flatten.include_usdt`, default true).
- freqtrade/Hummingbot semantic details were read from source but never executed; ratchet behaviour for gaps (stop fill price vs trigger) is not verified for Wallex.
- agiprolabs numeric thresholds (3/4/5% daily, ladder) are the repo author's heuristics without cited evidence; our numbers are design choices, to be tuned in backtest/shadow.
- Kelly drawdown table in agiprolabs ("full Kelly 50-80% max DD") is stated without derivation in the file; treat as indicative.
