# Signals and Strategies for a 3-day, spot, long-only, fee-sensitive Wallex account
> **Fee caveat:** fee numbers here are assumptions (Wallex publishes none in docs). Replace them with the output of `wallex_basic_get_account_fees` / `GET /v1/account/fee` before building. See [00-index](00-index.md).

**Scope**: concrete, implementable signal families (trend, mean reversion, momentum rotation, vol breakout, regime filters, microstructure, TMN/USDT) for 5,000,000 Toman, 3 days, long-only (flat-to-cash allowed); fee drag maths; which signals are deterministic features vs LLM-owned decisions.
**Researched**: 2026-10-21
**Repos+commits / sources** (all shallow clones, read only, never executed):
`freqtrade/freqtrade-strategies@f3340ce` (GPL-3.0), `freqtrade/freqtrade@0db79d3` (GPL-3.0), `je-suis-tm/quant-trading@611b73f` (Apache-2.0), `jesse-ai/jesse@4fcbcdd` (MIT), `agiprolabs/claude-trading-skills@981e1d7` (MIT), `HKUDS/Vibe-Trading@9081946` (MIT), `JerBouma/FinanceToolkit@5b2ccab` (MIT), `stefan-jansen/machine-learning-for-trading@35d6e2b` (MIT), `TA-Lib/ta-lib-python@ee40529` (BSD-2), `charliedream1/ai_quant_trade@373534a` (Apache-2.0, only skimmed: egs_trade/{vanilla,rl}, no formulas used).
Live Wallex public endpoints queried 2026-10-21: `https://api.wallex.ir/v1/markets`, `/v1/depth?symbol=`, `/v1/udf/history?symbol=&resolution=&from=&to=` (via WebFetch; numbers were relayed by a summarising model, so treat as indicative, re-measure in code).

Repo-path shorthand below: `fts` = freqtrade-strategies `user_data/strategies/`; `ctsk` = claude-trading-skills `skills/`; `vt` = Vibe-Trading `agent/src/skills/`.

## TL;DR
- **Fees are the binding constraint.** Official Wallex fee page could NOT be fetched (wallex.ir/fee 404/empty; docs intro page has no fees; `/v1/markets` has only a boolean `isZeroFee`, no maker/taker numbers). Only a third-party aggregator (blockspot.io/exchange/wallex) states 0.10 % maker/taker on TMN markets and 0.05 % on USDT markets. Treat as UNVERIFIED; the engine must read the real fee per order fill and from the account fee endpoint (needs API key) at startup.
- With those numbers a round trip costs 0.20 % (TMN, fees only) / 0.10 % (USDT, fees only); adding the observed top-of-book spread when crossing: ~0.20 % USDTTMN, ~0.37 % BTCTMN, ~0.31 % ETHUSDT. Anything targeting < ~1 % moves per trade loses a third or more of its gross edge to costs.
- Hence: 1h to 4h bars, a handful of round trips per day at most (suggest 6-15 total over 3 days), limit/post-style entries where possible, ATR-based stops, and a hard "expected move >= 3x round-trip cost" gate before any entry.
- Observed Wallex liquidity is thin (ETHUSDT best ask 0.014 ETH; many hourly bars have volume 0 and are MISSING from the candle feed), so the feature pipeline must reindex candles, forward-fill, and flag `bar_volume==0`. 5 M Toman is only about 19 USDT at 264k TMN/USDT, so size/impact is negligible but `minQty/stepSize/minNotional` rounding matters.
- USDTTMN itself trended from ~98k (2025-09-17) to ~264k (2026-10-21) Toman; last 30 days +15.8 %. A TMN-quoted long on any asset carries this FX drift; a USDT-quoted long on a coin sees it only after converting back to TMN. This is a first-order regime fact, not a signal we can verify as persistent.
- Best-evidenced, cheapest signal stack: EMA trend + ADX/ATR regime gate + Donchian/RSI-pullback triggers computed deterministically; LLM chooses among *pre-validated candidate setups* and sizes within a deterministic cap. Freqtrade's own sample strategies are 5m scalpers whose stop/ROI tables are tuned for far lower fees and are not usable as-is.
- Several public strategy repos ship look-ahead bugs (min/max normalisation over the full frame): see Findings 9. Compute every feature with expanding/rolling windows only and `shift(1)` for channel levels.

## Findings

### 1. Fee drag (the core calculation)
Sources/assumptions: fee `f` per side. Wallex numbers UNVERIFIED (blockspot.io aggregator: TMN 0.10 %, USDT 0.05 %; the same page marks the exchange "inactive", which is clearly stale since `api.wallex.ir` serves live data). Spread snapshots from `/v1/depth`, 2026-10-21 ~17:00 UTC.

Exact break-even gross move for a round trip (buy, then sell, taker both sides): `r = 1/(1-f)^2 - 1 ≈ 2f + 3f²`, plus spread crossing `s` (buy at ask, sell at bid, so one full spread) plus slippage `σ`.

| Market (snapshot spread) | f/side | Fee RT | + spread cross | Total break-even move (taker/taker) | Maker/maker (no spread, fill risk) |
|---|---|---|---|---|---|
| USDTTMN (1 TMN on 264,434 = 0.0004 %) | 0.10 % | 0.200 % | 0.0004 % | **~0.20 %** | 0.20 % |
| BTCTMN (ask 22,300,794,604 / bid 22,262,000,045 = 0.174 %) | 0.10 % | 0.200 % | 0.174 % | **~0.37 %** | 0.20 % |
| ETHUSDT (2492.45 / 2487.25 = 0.209 %) | 0.05 % | 0.100 % | 0.209 % | **~0.31 %** | 0.10 % |
| Fee-free symbol (`isZeroFee=true` flag in `/v1/markets`, none seen true in the first ~85 rows) | 0 | 0 | spread | = spread | 0 |

(The depth tool mis-stated BTCTMN spread as 0.00174 %; recomputed above from the raw prices: 38,794,559 / 22.28e9 = 0.174 %.)

Implications:
- Required win probability for TP/SL bracket with total cost `c`: `p* = (SL + c) / (TP + SL)`. Example TP 1.5 %, SL 1.0 %, c 0.35 % gives p* = 54 %; with c 0.2 % gives 48 %. For ATR-scaled brackets use the same formula.
- Capital drag: `drag_on_capital ≈ N_round_trips × c × avg_position_fraction`. 12 round trips at c = 0.35 % and 30 % average exposure = 1.26 % of capital, i.e. the strategy must clear ~1.3 % just to break even across 3 days. 40 round trips would cost 4.2 %.
- Rule: skip trade unless `expected_move_to_target >= 3 × c` (ie ~1.0-1.1 % on TMN pairs) and `reward:risk >= 1.5`.
- Timeframe: realised hourly ETHUSDT bars on Wallex show typical |close-open| of 0.2-0.6 % (rows 2026-10-18 06:00 to 2026-10-21 16:00); 15m or faster bars sit inside the cost band. Use 1h as decision clock (optionally 15m only for exit monitoring), 4h and 1d as context.
- Minimums seen in `/v1/markets`: `minNotional` 50,000 TMN for TMN pairs, 1 for USDT pairs; fields `tickSize`, `stepSize`, `minQty`, `isZeroFee` per symbol. 85+ symbols exist; not all are in the "approved list" for the contest (see requirements.md hard constraint).

### 2. Trend following (EMA / MACD / Supertrend / ADX / Donchian)
| Strategy | Source | Exact rule/params | TF | Notes/weaknesses |
|---|---|---|---|---|
| EMA 20/50/100 + Heikin-Ashi (Strategy001) | `fts/Strategy001.py:83-120` | Entry: `crossed_above(ema20, ema50) & ha_close > ema20 & ha_open < ha_close`. Exit: `crossed_above(ema50, ema100) & ha_close < ema20 & red HA bar` (sic: exit uses cross *above*, an odd rule). `minimal_roi {"60":.01,"30":.03,"20":.04,"0":.05}` (minutes), `stoploss -0.10`, `exit_profit_only=True`, `timeframe 5m` | 5m | ROI table up to 5 % in <=1h is calibrated to bull alt-coin pumps; stop of 10 % is 30x the round-trip cost. Whipsaws in ranges |
| ADX momentum (ADXMomentum) | `fts/berlinguyinca/ADXMomentum.py:33-65` | Entry: `adx(14)>25 & mom(14)>0 & plus_di(25)>25 & plus_di>minus_di`. Exit: `adx>25 & mom<0 & minus_di>25 & plus_di<minus_di`. `stoploss -0.25`, 1h | 1h | Clean, explainable, 1h. Needs a time/ATR stop; -25 % stop unusable |
| MACD + CCI (MACDStrategy) | `fts/berlinguyinca/MACDStrategy.py:65-99` | Entry: `macd>macdsignal & cci<=buy_cci`; exit: `macd<macdsignal & cci>=sell_cci`; 5m | 5m | Too frequent for our fees |
| 3x Supertrend (Supertrend) | `fts/Supertrend.py:40-160` | Buy: three supertrends all `'up'` with tuned `buy_params` (multipliers 4/7/1, periods 8/9/8; class defaults m=4,p=14 at lines 70-82); sell: all three `'down'` with `sell_params` m=(1,3,6), p=(16,18,18); sell: all three `'down'`. `stoploss -0.265`, trailing 0.05 offset 0.144, 1h, `startup_candle_count 199` | 1h | Supertrend = ATR band: `basic_ub=(H+L)/2+m*ATR(p)`, `basic_lb=(H+L)/2-m*ATR(p)`, direction flips when close crosses the (ratcheted) opposite band. FinanceToolkit has a version: `financetoolkit/technicals/volatility_model.py:171` |
| Donchian breakout | `FinanceToolkit volatility_model.py:374-` | `upper = rolling_max(high, N).shift(1)`, `lower = rolling_min(low, N).shift(1)`; breakout = `high > upper`. The `.shift(1)` is deliberate: excluding the current bar is the only correct non-self-defeating form (docstring explains) | 1h/4h | N=20 (1h: ~1 day) good for 3-day horizon; false breakouts in chop; use with ADX filter + volume (ratio>1.2) |
| Multi-signal vote (technical-basic) | `vt/technical-basic/example_signal_engine.py:197-238` | `ema_fast=12, ema_slow=26, adx_period=14, adx_threshold=25, bb_window=20, bb_std=2, rsi 14 (30/70), vol_ma/obv_ma 20`; `buy = (trend_bull | mr_oversold) & obv>obv_ma & ~mr_overbought`. Trend+MR OR'd together is incoherent regime-wise; better gate each by regime | any | Shows idiomatic Wilder RSI/ADX (`ewm(alpha=1/period)`) at lines 23-81 |

Textbook formulas to implement (verify against TA-Lib in tests; `ta-lib-python@ee40529` is a C wrapper, formulas not in the repo):
- `EMA_n: α=2/(n+1)`, `MACD = EMA12-EMA26`, `signal = EMA9(MACD)`, `hist = MACD-signal`.
- `TR = max(H-L, |H-C_prev|, |L-C_prev|)`, `ATR_n = Wilder-smoothed TR` (`ewm(alpha=1/n)`).
- `ADX`: `+DM=max(H-H_prev,0)` if > `-DM` else 0 (and symmetric); `+DI=100·Wilder(+DM)/ATR`; `DX=100·|+DI−−DI|/(+DI+−DI)`; `ADX=Wilder(DX)`. Reference implementation `vt/technical-basic/example_signal_engine.py:32-83`. Warning: `ctsk/regime-detection/SKILL.md:66-87` uses `ewm(span=period)` (α=2/(n+1)) instead of Wilder α=1/n and so is not TA-Lib compatible; use the Vibe-Trading one.

Trade frequency: EMA(20/50) on 1h yields ~1 signal per 2-4 days per symbol in trending tape, ~0 in chop. That is compatible with our budget but means each asset often idles; use a basket of 5-8 liquid symbols.

### 3. Mean reversion (RSI / Bollinger / z-score / stochastic)
| Strategy | Source | Rule | Notes |
|---|---|---|---|
| Strategy002 | `fts/Strategy002.py:107-135` | Entry: `rsi<30 & slowk<20 & bb_lower(20,2, typical price)>close & CDLHAMMER==100`; exit `sar>close & fisher_rsi>0.3`; inverse Fisher: `x=0.1*(rsi-50)`, `fisher=(e^{2x}-1)/(e^{2x}+1)` | 5m. Four-way AND = very rare, few trades |
| Strategy004 | `fts/Strategy004.py:114-140` | `(adx>50 | slowadx(35)>26) & cci<-100 & fastk/fastd(prev)<20 & slowfastk/d(prev)<30 & fastk crosses above fastd & mean-volume>0.75` | 5m, "buy the dip inside a strong trend" |
| BbandRsi | `fts/berlinguyinca/BbandRsi.py:37-60` | Entry `rsi(14)<30 & close<bb_lower`; exit `rsi>70` | 1h, stoploss -0.25; the cleanest 1h MR template |
| Bandtastic | `fts/Bandtastic.py:24-156` | 15m; BB lower bands at 1..4 std (window 20 on typical price) as trigger; optional `rsi<52`, `mfi<30`, `ema211>ema250` filters; exit by upper band/MFI>46; ROI `{0:.162,69:.097,229:.061,566:0}`, stop -0.345, `startup_candle_count 999` | Hyperopt-overfit (EMA 211/250, stop -34.5 %): shows what NOT to copy |
| Bollinger pattern recognition | `quant-trading/Bollinger Bands Pattern Recognition backtest.py:38-165` | bands `mid=SMA20`, `±2·std20`; "bottom W" / "top M" patterns using `alpha` (price-to-band tolerance) and `beta` (bandwidth threshold); exits on contraction (`std<beta`) | Pattern code is long, loopy, discretionary |
| MR toolkit | `ctsk/mean-reversion/SKILL.md` (Hurst, half-life, z-score, ADF, OU) | z-score entry/exit, half-life gating | Library-level; use only the z-score and half-life |

Implementation: `z = (close - SMA_n)/std_n` (n=20-48 on 1h); buy when `z <= -2` AND regime != strong-downtrend AND `RSI14 < 30-35`; exit at `z >= 0` or time stop of `2·half_life` bars. Known weaknesses: in a trending-down Toman-priced alt, "oversold" persists (catching a falling knife); always require regime gate (ADX<25 or price above EMA200) and hard stop at `1.5-2·ATR`. Expected frequency: 1-3 signals/day across a 6-symbol basket on 1h at z=-2. Because longs only, mean reversion buys dips and sells bounces: the profit target is bounded by the band mid, typically 0.5-1.2 % on 1h, which is barely 2-3x cost; this is the family most hurt by fees.

### 4. Momentum / relative-strength rotation
- ai_quant_trade has `egs_trade/vanilla/momentum_rotation` and `double_ma` (README-level only; not audited). stefan-jansen ch.17-18 covers portfolio construction and a cost cliff (`machine-learning-for-trading/18_transaction_costs/11_cost_cliff.py`, `09_frequency_tradeoff.py`, `10_gross_vs_net_performance.py`) showing gross-vs-net degradation with turnover: use as backing for "turnover is the enemy".
- Spec for our 3-day setting (proposal, not from a repo): every 4h compute `mom_k = close/close[-k]-1` for k ∈ {6, 24, 72} bars (1h bars), cross-sectional rank across the approved basket, and `rs_vs_BTC = mom_24 - mom_24(BTCUSDT)`. Candidate = top-2 by `0.5·z(mom_24)+0.3·z(mom_72)+0.2·z(mom_6)` AND `rs_vs_BTC>0` AND above EMA50. Hold until rank falls out of top-3 or stop. Max 1-2 rotations/day.
- Weakness: cross-sectional momentum on 3 days of thin alts is dominated by single-day pumps (SOL bull-period +176 % buy&hold in CryptoTrade test windows, see file 07) and mean-reverts afterwards; require volume confirmation (`vol_ratio>1.5`) and cap per-asset weight.

### 5. Volatility breakout / squeeze
- Dual Thrust (`quant-trading/Dual Thrust backtest.py:94-131`): upper = `open + param·range`, lower = `open − (1−param)·range`, `param=0.5`, range from previous days (`rg`). Long-only variant: buy if price > upper after the daily open; exit at close/stop. Works on daily-rolling windows; crypto's 24/7 means choose a fixed UTC-based "session open" (e.g. 00:00 UTC) or a rolling 24h window.
- London Breakout (`quant-trading/London Breakout backtest.py`): FX session specific; not applicable.
- Squeeze (from `ctsk/regime-detection/SKILL.md:104-120`): `bb_width = 2·k·std/SMA` percentile over 100 bars `< 0.20`, then breakout in direction of `close>upper_BB` or Keltner (`EMA ± 1.5·ATR`, FinanceToolkit `volatility_model.py:319`). Entry on the first close above the upper band with `vol_ratio>1.5`; stop at the band midpoint / `1.5·ATR`; target `2-3·ATR`.
- Weakness: false breakouts when book is thin (Wallex hourly highs often single prints, e.g. ETHUSDT 2026-10-20 14:00 high 2460 vs close 2455.64 after a 28.5 ETH volume bar). Confirm with close, not wick.

### 6. Regime filters (ADX / ATR percentile / Hurst / trend)
Source: `ctsk/regime-detection/SKILL.md` (981e1d7), formulas lines 33-161, combined classifier lines 249-281, crypto adaptation table lines 221-226.
- ATR percentile: `rank_pct(ATR14, lookback=100)`; `<0.25` low-vol, `>0.75` high-vol (lines 57-59); classifier uses 0.30/0.70 (lines 254-258).
- ADX `>25` trending, `<20` range (lines 63, 259-263).
- Hurst (R/S, `max_lag=50`) `<0.4` mean-reverting, `>0.6` trending (lines 127-129); crypto large-cap suggested window 100 bars (line 226). Weakness: R/S estimates on <100 bars are noisy and biased upwards; our 3-day hourly data gives ~72 bars of live regime. Use Hurst only as informational feature or on 4h bars over 30 days (180 bars).
- Strategy mapping (lines 289-295): low vol+up-trend = full size trend-following; high vol+trending = half size; low vol+ranging = mean reversion; high vol+ranging = 25 % size or sit out; transition = flat/minimum.
- Crypto speed table (lines 221-226): ADX period 10-14, ATR lookback 50-100, regime persistence "days-weeks".
- Correlation regime (Vibe-Trading `agent/backtest/regime.py:1-60`): `edge_density` = fraction of asset pairs with |ρ|≥0.5 over a 60-bar window plus hysteresis. Useful for "all coins move together, so diversification is illusory, cut aggregate exposure"; cheap to compute for the basket.

### 7. Microstructure: order-book imbalance, VWAP, spread
- `GET /v1/depth?symbol=` returns bids/asks; compute `OBI_k = (Σ bid_qty_k − Σ ask_qty_k)/(Σ bid_qty_k + Σ ask_qty_k)` over top k=5 levels (value-weighted by price·qty), `microprice = (ask·bid_qty1 + bid·ask_qty1)/(bid_qty1+ask_qty1)`, `spread_bps`.
- Observed books are thin and lumpy (ETHUSDT top 3 asks: 0.014, 9.41, 0.014 ETH; USDTTMN: 2061 USDT at best ask), so OBI is noisy and spoofable; **use only as an execution filter** (avoid entering when `spread_bps > 25` or top-5 notional < 5× order size, prefer limit at bid+1 tick), not as an alpha source. No repo here validates OBI on Wallex; `ctsk/market-microstructure*` skills are DEX/trade-flow oriented (not audited in depth).
- VWAP: `vwap = Σ(typical·vol)/Σvol` anchored at 00:00 UTC; feature `dist_vwap = close/vwap − 1`. With zero-volume bars common, anchor on sessions with volume>0 and do not trust it for illiquid alts. Execution-side TWAP/VWAP slicing is pointless at ~19 USDT notional.
- Spread/slippage model for backtests: charge `spread/2 + f` each side for taker, assume 50 % fill probability for passive orders and charge the missed-trade opportunity separately.

### 8. TMN-USDT premium / stablecoin-rate signals specific to Iran
Documented in repos: nothing Iran-specific (only generic `vt/stablecoin-flow`, `perp-funding-basis` skills, not read in detail; no Wallex adapters anywhere). What can be derived from Wallex data itself:
- `USDTTMN` daily closes fetched (`/v1/udf/history?symbol=USDTTMN&resolution=D`, 400 points 2025-09-17 to 2026-10-21): 98,194 → 264,435 TMN (x2.69, ≈ +0.25 %/day average log drift), biggest daily moves +7.65 % (2026-01-28) and −5.20 % (2026-05-23); last 30 days +15.8 %, sideways 259-269k over the last 3 weeks.
- Triangular consistency features computable live with zero extra data: `implied_USDT_rate(X) = X_TMN_price / X_USDT_price` for X in {BTC, ETH, SOL, ...}; **premium_X = implied_USDT_rate(X) / USDTTMN_mid − 1**. A persistent premium > ~0.5 % (> round-trip cost) between the TMN book and USDT book of the same coin signals either illiquidity or an arbitrage leg: buy the cheap leg only if you can exit in Toman (long-only TMN end-state fits: buy X with USDT, sell X for TMN = "USDT→X→TMN" route vs direct USDT→TMN). Edge is real only if premium exceeds 3 fees (2 trades each leg, about 0.3-0.5 %); needs live depth check. Unverified as profitable.
- Regime feature `usdt_tmn_trend = EMA24(USDTTMN)/EMA96(USDTTMN) − 1` and `usdt_tmn_vol = std(1h log ret, 24)`: a rising USDTTMN lifts every TMN-quoted coin price mechanically; the LLM should be told "TMN-price strength may be FX, not coin alpha" (`coin_ret_tmn − usdttmn_ret ≈ coin_ret_usdt`).
- Final-state rule from requirements: must end in Toman. Holding USDT till day 3 and selling is permitted only if converted to TMN before the cutoff (USDT is a coin holding in Wallex terms; see requirements "no coin-denominated holdings"). Plan an explicit "liquidate everything to TMN at T−X hours" deterministic routine.

### 9. Look-ahead traps present in popular strategy libraries
- `fts/lookahead_bias/readme.md`: DevilStra, GodStraNew, Zeus, wtc "do have a lookahead bias"; cause: `normalize()` using full-frame `.min()/.max()`, `MinMaxScaler.fit_transform` on the whole series.
- `fts/Strategy004.py:107-110` comments that `dataframe['volume'].mean()` over the whole frame leaks in backtests; use `rolling(12).mean()`.
- Freqtrade docs say FreqAI features are computed once over the training range, so "be sure that features do not look-ahead" (`freqtrade/docs/freqai-running.md:71`); the project ships `freqtrade lookahead-analysis` (`docs/lookahead-analysis.md`) which re-runs backtests on truncated data and compares signals; replicate this unit test: compute features on `df[:t]` and `df[:t+k]`, assert row t identical.
- Donchian off-by-one: FinanceToolkit explicitly uses `shift(1)` so the breakout bar is not inside its own channel (`volatility_model.py:374-` docstring).

### 10. Freqtrade strategy parameters are NOT portable to our fee regime
Typical freqtrade-strategies ROI/stop: `stoploss -0.10 ... -0.345`, ROI `0.01-0.16`, `5m` timeframe, designed for 0.1 % Binance fees on bull-run pairs and with hyperopt on in-sample data. Their `exit_profit_only=True` plus -10 % stop hides large unrealised losses (a *Loss control* 30-point criterion in our scoring). Take rule *structures*, replace the risk parameters.

## Comparison table (family vs our constraints)
| Family | Best TF | Round trips / 3d (6 symbols) | Typical gross move/trade | Fee-drag share at c=0.3 % | Regime it needs | Main failure | Verdict for us |
|---|---|---|---|---|---|---|---|
| EMA trend + ADX gate | 1h-4h | 3-8 | 1.5-4 % | 8-20 % | trending | whipsaw after reversal | PRIMARY |
| Donchian-20 breakout + volume | 1h | 3-8 | 1.5-3 % | 10-20 % | vol expansion | false break in thin book | PRIMARY (alt trigger) |
| RSI/BB/z-score dip-buy in uptrend | 1h | 4-10 | 0.5-1.5 % | 20-60 % | range / pullback in uptrend | falling knife | SECONDARY, only with trend filter and wider target |
| Cross-sectional momentum rotation | 4h | 2-6 | 2-6 % | 5-15 % | broad risk-on | pump reversal | Use as *ranking input* |
| Squeeze breakout | 1h | 1-4 | 2-4 % | 8-15 % | low→high vol | wick fakeouts | Optional |
| OBI / microprice | seconds-min | n/a | < cost | > 100 % | n/a | spoofing, thin book | Execution filter only |
| TMN-USDT triangular premium | min-h | 0-4 | 0.3-1 % | 30-100 % | dislocations | gone by the time you trade | Monitor; opportunistic |

(Ranges are my estimates from the quoted fee levels and hourly bar sizes seen in the ETHUSDT sample; not backtested. Fraction = c / gross move.)

## Reusable for our system
- **Indicator library**: write our own pandas/numpy `features.py` based on `vt/technical-basic/example_signal_engine.py:13-105` (Wilder RSI, ADX, BB, OBV; MIT) and `ctsk/regime-detection/SKILL.md` snippets (ATR percentile, BB-width percentile, Hurst, classify_regime; MIT) and FinanceToolkit Donchian/Keltner/Supertrend (MIT). Avoid TA-Lib as a hard dependency (C build pain on judges' machines); use it only as an optional parity test (BSD-2).
- **Do not copy** freqtrade-strategies code (GPL-3.0 would infect the repo); re-implement rule *ideas* only. quant-trading is Apache-2.0 (safe to adapt Dual Thrust / Bollinger logic with attribution).
- **Backtest hygiene**: `lookahead-analysis` idea (truncate and compare); stefan-jansen `07_defining_the_learning_task/03_label_methods.py` (triple-barrier labels), `18_transaction_costs/11_cost_cliff.py`.
- **Public candle feed**: `GET https://api.wallex.ir/v1/udf/history?symbol=ETHUSDT&resolution=60&from=<unix>&to=<unix>` returns `{s:"ok", t:[...], o,h,l,c,v: [strings]}`; bars with no trades are omitted (a 2-hour gap observed 2026-10-19 22:00-23:00; `resolution` values 15, 60, D worked; others not tested). No API key needed for it. The depth endpoint `/v1/depth?symbol=` and `/v1/markets` were also keyless.

## Recommended design decisions for the hackathon
Scoring link: strategy logic 40, real AI 35, risk 30, repro 25, backtest/shadow 20, profit 90, loss control 30, activity 15, stability 15.

1. **Decision clock**: 1h bars, evaluated at each hourly close (plus 5-min risk monitor). 4h/1d context features. Target 6-15 round trips over 3 days (satisfies "regular activity", keeps drag ≤ ~1.5 % of capital).
2. **Universe**: 5-8 liquid symbols from the approved list, prefer USDT-quoted (0.05 % fee per unverified aggregator) for entries and a single deterministic conversion to TMN at the end; confirm the contest-approved list and each symbol's `isZeroFee`, `minNotional`, `stepSize`.
3. **Deterministic layer computes** (never the LLM): all indicators, regime label, candidate setups (list below), cost model, position-size cap, stop/target levels, liquidation schedule. **LLM owns**: (a) pick which candidate(s), if any, to act on and why; (b) conviction 0-1 which scales size within [0, cap]; (c) when to stand aside; (d) exit-early / hold decisions for open positions inside a deterministic bracket; (e) cross-asset narrative (BTC leadership, FX drift) and anomaly judgement; output must be JSON with `action, symbol, conviction, reasons[], invalidation`, logged per trade.
4. **Candidate setups** (each must pass `expected_move ≥ 3c`, `R:R ≥ 1.5`, spread < 25 bps, regime allows):
   - A. Trend pullback: `EMA20>EMA50>EMA200(1h)`, `ADX14>20`, `RSI14` crossing up through 40-50 after dipping < 45, close > EMA20; stop `1.5·ATR14`, target `3·ATR14`, trail after +1.5 ATR.
   - B. Donchian breakout: `close > donchian_upper(20).shift(1)`, `vol_ratio>1.5`, `ADX>20`, not already > 2.5 ATR above EMA20; stop at `donchian_mid`, target `2.5·ATR`.
   - C. Range dip-buy: regime ranging (`ADX<20`), `z48 <= -2`, `RSI14<32`, price above EMA200(4h) or `usdt_tmn_trend>0`; stop `2·ATR`, target `z=0` and ≥ 3c.
   - D. Rotation overlay: pick from candidates ranked by `rs_score`.
5. **Regime scheme (proposed thresholds, adapted from `ctsk/regime-detection`)** on 1h bars of the symbol, plus BTC as market regime:
   - `vol_pct = rank_pct(ATR14/close, 100 bars)`: low <0.30, high >0.70.
   - `trend`: `TREND` if ADX14>25 (and `slope = EMA20.diff(5)/close`>0 → UP, <0 → DOWN); `RANGE` if ADX14<20; `TRANSITION` otherwise.
   - Risk multipliers: TREND_UP/low-vol 1.0; TREND_UP/high-vol 0.5; RANGE/low-vol 0.7 (MR only); RANGE/high-vol 0.25 (stand aside); TREND_DOWN → 0 (flat to cash, long-only); TRANSITION 0.3.
   - Add `market_stress` flag if BTC 24h drawdown > 6 % or `corr_edge_density>0.8` → halve everything; drawdown breaker at −3 % account from peak → cash for 12 h, −6 % → liquidate to TMN and stop (supports Loss control 30 pts).
6. **Recommended LLM feature set** (per symbol, rounded, as JSON; all backward-looking, computed at bar close t):
   - Price/trend: `ret_1h, ret_4h, ret_24h, ret_72h`; `ema20_50_gap = EMA20/EMA50−1`; `dist_ema200 = close/EMA200−1`; `ema20_slope_5 = EMA20/EMA20[-5]−1`.
   - Momentum: `rsi14` (Wilder), `macd_hist/close`, `roc_24`.
   - Trend strength/regime: `adx14, plus_di, minus_di, atr14_pct = ATR14/close, atr_pctile_100, bbw_pctile_100, hurst_4h_180` (info only), `regime_label`.
   - Mean reversion: `z48 = (close−SMA48)/std48`, `bb_pos = (close−lower)/(upper−lower)` BB(20,2), `dist_vwap_utc`.
   - Breakout: `donch20_pos = (close−lower20.shift1)/(upper20.shift1−lower20.shift1)`, `breakout_up = close>upper20.shift1`, `vol_ratio = vol/SMA20(vol)` (and `bars_with_zero_vol_24` as illiquidity flag).
   - Microstructure: `spread_bps, obi5, microprice_gap_bps, top5_notional_vs_order`.
   - Cross-asset: `rs_vs_btc_24h, btc_regime, corr_edge_density_60`.
   - Iran/FX: `usdttmn_ret_24h, usdttmn_trend (EMA24/EMA96−1), premium_X` (triangular).
   - Cost: `round_trip_cost_pct` (from live fee + spread), `expected_move_to_target_pct`, `rr`, `breakeven_winprob`.
   - Account: `equity, cash_pct, open_positions[{entry, pnl_pct, bars_held, stop, target}], day_pnl_pct, dd_from_peak`.
   Keep to ~35 numbers per symbol and ≤ 8 symbols (token cost, reproducibility; also feed a 24-bar compact OHLC string for pattern reading).
7. **Order policy**: limit orders at best bid (+1 tick) with 2-bar timeout then optional market only when expected move ≥ 5c; exits: stops are deterministic and fire without LLM; if Wallex lacks reliable server-side stop orders (unverified here), the engine polls every ≤ 60 s.
8. **Backtest evidence for judges**: run families A/B/C on at least 60 days of hourly candles (public UDF endpoint) with the cost model above (f_taker per side + half-spread, optional 0.1 % extra slippage), report gross vs net, trades/day, hit rate, max DD; include a shadow run log. Compare to buy&hold and "cash" baselines; show results by regime. Clearly state the LLM layer could not be backtested without look-ahead (file 07) so backtest the deterministic skeleton and shadow-test the LLM live.
9. **Do not tune** more than 5 parameters; fix defaults from literature (EMA 20/50/200, ADX 14/25/20, RSI 14, ATR 14, Donchian 20, BB 20/2) to avoid the hyperopt-overfit visible in Bandtastic (`buy_slowema 250, stoploss −0.345`).

## Unverified / open questions
- Real Wallex maker/taker fees, tiering and whether fees are charged in base/quote; whether any contest-approved market is `isZeroFee`. Needs the authenticated account/fee endpoint or Wallex support.
- Contest "approved markets" list and whether USDT-quoted pairs are included; whether market orders / limit-only; stop-order support; rate limits; WebSocket depth latency (docs sections Spot/WebSocket not readable via fetcher beyond the intro page).
- Whether `udf/history` resolutions other than 15/60/D exist, max bars per request, and how it behaves for illiquid alts (we saw omitted empty bars).
- Persistence of the USDTTMN drift and any signed premium vs. international USDT; no academic source found; do not hard-code a bullish FX bias.
- Hourly volatility statistics quoted here are from one 81-row ETHUSDT sample relayed by a summarising fetch tool; recompute in code on 60+ days for all candidate symbols before fixing thresholds.
- `ctsk/market-microstructure*`, `vt/stablecoin-flow`, `perp-funding-basis`, `ai_quant_trade/egs_trade/vanilla` and `stefan-jansen` ch.17-18 notebooks were identified but not read line by line.
- Supertrend implementation itself is `ftt.supertrend` from the external `technical` package (not in the cloned repos), so its exact band-ratchet rule is the textbook one, unverified here.
