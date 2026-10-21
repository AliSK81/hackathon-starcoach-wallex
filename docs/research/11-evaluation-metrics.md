# Evaluation Metrics, Robustness Checks and Report Layout

**Scope**: Exact metric definitions (as required by the contest and as computed by freqtrade / vectorbt / nautilus / jesse), correct annualisation for a 3-day crypto window, statistical proof that profit is "not one lucky trade", and the evaluation report to show judges. · **Researched**: 2026-10-21 · **Repos+commits**: freqtrade/freqtrade@0db79d3 (GPL-3.0) · polakowo/vectorbt@dd8eb3a (Apache-2.0 + Commons Clause) · nautechsystems/nautilus_trader@e88439b (LGPL-3.0) · jesse-ai/jesse@4fcbcdd (MIT) · skfolio/skfolio@dc704aa (BSD-3) · dcajasn/Riskfolio-Lib@7b1b26a · agiprolabs/claude-trading-skills@981e1d7 (MIT).

## TL;DR
- Contest return is `Return% = (V_final - 5,000,000) / 5,000,000 * 100` where `V_final` = TMN-denominated net account value incl. fees and unrealised P&L (requirements.md, "Return Metric"). Our reports must reproduce this number **exactly** from exchange balances, not from our own PnL ledger; reconcile the two and show the diff.
- Compute **max drawdown on mark-to-market equity snapshots** (e.g. every 1-5 min), not on closed trades. freqtrade's `calculate_max_drawdown` uses cumulative closed-trade `profit_abs` (`data/metrics.py:207`), which misses intra-trade unrealised drawdowns; freqtrade's own `calculate_max_drawdown_from_balance` (`:501`) exists for the balance-based variant. Judges' "account drawdown" (30 pts) is account-level.
- Do **not** quote annualised Sharpe/Calmar for a 3-day run as headline numbers: sqrt(365)=19.1 (daily), sqrt(365*24)=93.6 (hourly), sqrt(365*288)=324 (5-min) inflate noise. Report the non-annualised per-period Sharpe, its t-stat `SR*sqrt(T)` and a probabilistic Sharpe (PSR) instead; annualise only for comparability, labelled as such.
- Implementations disagree: freqtrade Sortino divides by std of **losing trades only** (`calculate_sortino`, `:407`), whereas vectorbt (`returns/nb.py:451,484`), Nautilus (`sortino_ratio.rs:30`) and Jesse (`services/metrics.py:90`) use the lower-partial-moment `sqrt(sum(min(r,0)^2)/N)`. Freqtrade's Sharpe/Sortino use per-trade profits with `days_period = max(1,(max_date-min_date).days)` (integer days: 2.9 days gives 2). State your formula in the report and use the LPM form.
- Crypto annualisation constant is 365 (Jesse default `annualization=365`, `services/metrics.py:36`; freqtrade `_calculate_annualized_ratio(..., annualization_factor=365)`, `:341`); Nautilus defaults to 252 (`sharpe_ratio.rs:55`), wrong for 24/7 markets unless overridden.
- "Not one lucky trade" evidence, in order of cheapness: (1) top-1 / top-3 trade share of total PnL and PnL without best trade, (2) per-day PnL signs (3 days only: also per-6h blocks), (3) trade-level bootstrap and sign-flip test for P(total PnL > 0) and a 5th-percentile PnL, (4) rolling walk-forward backtest on the previous 4-8 weeks with frozen parameters, (5) parameter-sensitivity grid +/-20-30% with a plateau, (6) deflated Sharpe if many configs were tried (skfolio `deflated_sharpe_ratio`).
- With ~20-60 trades in 3 days, statistical power is low: a per-trade Sharpe of 0.2 needs ~100 trades for t=2 (own arithmetic `(2/SR)^2`); 0.3 needs 45; 0.1 needs 400. Say so honestly; the evidence for judges is explainability + consistency + backtest/shadow, not a p-value.
- LLM nondeterminism is a reproducibility risk: log every prompt/response with a hash, run backtests in **replay mode** from cached decisions, and report decision agreement across repeated runs (temperature 0).
- The report must show fee drag and exposure so judges see profit is not a market-beta accident (return vs buy-and-hold of the traded coins; freqtrade reports `market_change`, `optimize_reports.py`).

## Findings

### 1. Metric definitions (our standard)
Notation: equity series `E_t` sampled at fixed step `dt` (marks), returns `r_t = E_t/E_{t-1} - 1`, `T` = number of steps, `N` closed round-trip trades with net PnL `p_i` (after both fees), `E_0 = 5,000,000`.

| Metric | Formula | Notes |
|---|---|---|
| Total return (contest) | `(E_final - E_0)/E_0 * 100` | `E_final` from exchange balances in TMN, incl. fees, open positions marked; identical to vectorbt `total_return_nb = total_profit/init_cash` (`portfolio/nb.py:6927`) |
| Max drawdown (MDD) | `max_t (peak_t - E_t)/peak_t`, `peak_t = max_{s<=t}(E_0..E_s)` | Nautilus `max_drawdown.rs:67`: compounds returns from 1.0, running max, returns **negative** `-max_dd`; vectorbt `max_drawdown_1d_nb = min(drawdown series)` (`returns/nb.py:229`). Include `E_0` in the peak (freqtrade `_calc_drawdown_series` adds a zero row and `high_value = max(0, cummax)`, `metrics.py:130`). Report also max drawdown in TMN, duration, time-to-recover |
| Sharpe (per-period) | `mean(r)/std(r, ddof=1)` | vectorbt `sharpe_ratio_1d_nb` (`returns/nb.py:411`) uses ddof=1, `*sqrt(ann_factor)` to annualise; returns inf if std=0 |
| Sharpe (annualised) | `mean/std * sqrt(K)`, K = periods per year | K=365 daily, 8760 hourly, 105,120 for 5-min (vectorbt `ann_factor = year_freq / freq`, `returns/accessors.py:279-289`; year_freq must be passed, 365 days for crypto) |
| Sortino | `mean(r) / sqrt(sum(min(r,0)^2)/T) * sqrt(K)` | vectorbt `downside_risk_1d_nb` (`:451`) + `sortino_ratio_1d_nb` (`:484`); Jesse same (`metrics.py:90`); freqtrade differs (std of negative trade profits only, `metrics.py:407`) |
| Calmar | `CAGR/|MDD|`, `CAGR = (E_final/E_0)^(365/days) - 1` | Nautilus `calmar_ratio.rs:73` = CAGR / |max_dd| (NaN if no drawdown); vectorbt `calmar_ratio_1d_nb` (`:254`). freqtrade `calculate_calmar` (`:538`) multiplies the daily mean return by 100 and then applies `sqrt(365)` to `mean/MDD`: not the textbook ratio, do not copy. **Extrapolating a 3-day return to a year makes CAGR astronomically large**; freqtrade guards overflow (`calculate_cagr`, `:292`). For us: report `return / MDD` ("return-to-drawdown", non-annualised) |
| Win rate | `#(p_i > 0)/N` | vectorbt `trades.py:628`; freqtrade `winrate` (`optimize_reports.py:217`) |
| Profit factor | `sum(p_i for p_i>0) / |sum(p_i for p_i<0)|` | freqtrade `optimize_reports.py:183` (0.0 if no losses); vectorbt `trades.py:638` (inf/NaN when no losses) |
| Expectancy (TMN/trade) | `wr*avg_win - lr*avg_loss`, `lr = #losses/N` | freqtrade `calculate_expectancy` (`metrics.py:310`) also returns `expectancy_ratio = (1+R)*wr - 1`, R=avg_win/avg_loss (default 100 when no losses); vectorbt `trades.py:654` excludes breakevens from `lr`; Nautilus `expectancy.rs:62` counts only non-zero trades |
| Expectancy in R | `mean(p_i / risk_i)`, `risk_i` = TMN risked at entry (stop distance*size) | needs the risk gate's per-trade risk; ties results to risk management |
| Average trade | `mean(p_i)`; also median, `avg_win`, `avg_loss`, `payoff = avg_win/|avg_loss|` | |
| SQN | `sqrt(N) * mean(p_i/E_0) / std(p_i/E_0)` | freqtrade `calculate_sqn` (`:613`); vectorbt `trades.py:681` |
| Exposure (time in market) | `sum_i(notional_i * hold_i)/(E_avg * T_total)` (average gross exposure) and `% of time with any open position` | vectorbt reports "Max Gross Exposure [%]" (`portfolio/base.py` stats). Our cap: gross <= 60% |
| Turnover | `sum |traded notional| / E_avg` (round trips counted both legs) | judges see "trading volume / avg trade volume" (requirements, Trading Performance) |
| Fee drag | `total_fees / E_0` and `total_fees / gross_profit` (gross = PnL before fees) | at assumed 0.9% round trip incl. slippage: 20 trades x 1.25M = 225,000 TMN = 4.5% of capital (from file 03) |
| Worst day / trade | min daily PnL; min `p_i`; freqtrade `backtest_worst_day` (`optimize_reports.py:523`) | |
| Market comparison | strategy return minus equal-weight buy-and-hold of the traded coins over the same window | freqtrade `calculate_market_change` (`metrics.py:14`) |
| Tail risk (optional) | historical VaR/CVaR 95% on step returns | agiprolabs `risk-management/SKILL.md`; skfolio `cvar` (`measures/_measures.py:635`) |
| PSR | `Phi( (SR_hat - SR*) sqrt(T-1) / sqrt(1 - g3*SR_hat + (g4-1)/4 * SR_hat^2) )`, per-period values, g3=skew, g4=kurtosis (non-excess) | skfolio `probabilistic_sharpe_ratio` (`_measures.py:1302`); SR*=0 |
| Deflated Sharpe | `PSR(SR_0)`, `SR_0 = sigma_SR[(1-gamma) Z^-1(1-1/N) + gamma Z^-1(1-1/(N e))]`, N = number of trials, gamma = Euler-Mascheroni | skfolio `expected_max_sharpe_ratio` (`:1217`) and `deflated_sharpe_ratio` (`:1383`; needs the Sharpe of *every* trial); vectorbt `deflated_sharpe_ratio` accessor (`returns/accessors.py:665`) |
| Trade-level t-test | `t = mean(r_i)/ (std(r_i)/sqrt(N))`, two-sided p | freqtrade `calculate_p_value` (`metrics.py:642`, `scipy.stats.ttest_1samp`; returns 1.0 if N<2 or zero variance) |

### 2. Annualisation for a short crypto window (derived, own arithmetic)
- Sampling step for returns determines K: daily K=365, hourly K=8,760, 15-min K=35,040. Annualised Sharpe from n=3 daily points is meaningless (sample std from 2 d.o.f.).
- Use hourly marks (T=72 over 3 days). Standard error of the per-period Sharpe is approximately `sqrt((1 + 0.5*SR^2)/T)` (Lo 2002; standard result, **not found in the cloned repos**): at T=72, SR=0.2 -> SE ~0.119, t ~1.7; at T=288 (15-min), SR=0.2 -> SE ~0.060, t ~3.4. So a 15-min grid gives a tighter-looking figure only if returns are not autocorrelated; Jesse offers `autocorr_penalty` ("smart" Sharpe, `services/metrics.py:114`) which scales the divisor by `sqrt(1 + 2*sum(((n-x)/n) * rho^x))`: use it if equity marks are autocorrelated (positions held across marks).
- Report: per-period Sharpe, t-stat, PSR(0) and, secondarily, annualised Sharpe with K stated.
- freqtrade's daily Sharpe hyperopt loss (`hyperopt_loss_sharpe_daily.py`) shows a common convention: subtract slippage 0.0005 per trade, bin by calendar day, reindex missing days with 0, `mean/std*sqrt(365)`, returns -20.0 when std=0. Reusable convention for a daily table.

### 3. How the frameworks compute (cited)
| Framework | Where | Key behaviour |
|---|---|---|
| freqtrade | `data/metrics.py`: `calculate_max_drawdown` (207), `calculate_expectancy` (310), `_calculate_annualized_ratio` (341: `mean/denom*sqrt(365)`, -100.0 if denom 0/NaN), `calculate_sortino` (407), `calculate_sharpe` (455), `calculate_calmar` (538), `calculate_sqn` (613), `calculate_p_value` (642); `*_from_balance` variants resample balance to daily last (`_calculate_daily_returns_from_balance`, 361) | Trade-based; MDD relative = `(max_balance - cum_balance)/max_balance` with `starting_balance`; report assembly in `optimize/optimize_reports/optimize_reports.py` (`generate_strategy_stats`, 554; `generate_trading_stats`, 436; `generate_daily_stats`, 518) |
| freqtrade hyperopt losses | `optimize/hyperopt_loss/`: `ProfitDrawdown`: `-(P - dd_rel*P*(1-0.075))`; `MultiMetric`: `profit_draw * log(PF+1) * log(min(10,expectancy_ratio)+2) * log(1.2+winrate) * trade_count_penalty` (target 50 trades, DRAWDOWN_MULT 0.055); `MaxDrawDown`: `-profit/drawdown_abs` | Good candidates for a single scalar to choose parameters; MultiMetric explicitly penalises few trades |
| vectorbt | `returns/nb.py`: `annualized_return_1d_nb` (132: `end_value^(ann_factor/n) - 1`), `annualized_volatility_1d_nb` (167), `sharpe_ratio_1d_nb` (411), `sortino_ratio_1d_nb` (484), `omega_ratio_1d_nb` (358); `portfolio/trades.py` win_rate/profit_factor/expectancy/sqn (628-690) | Needs explicit `year_freq`; ann_factor = `year_freq/freq` |
| Nautilus | `crates/analysis/src/statistics/`: `sharpe_ratio.rs:73` (downsamples to **daily bins**, `mean/std*sqrt(period)`, default 252, NaN if std<eps), `sortino_ratio.rs`, `max_drawdown.rs:67`, `calmar_ratio.rs:73`, `profit_factor.rs`, `expectancy.rs:62`; aggregation `analyzer.rs:741-826` (`get_performance_stats_pnls/returns/general`) | Separates PnL-based, returns-based and general stats |
| Jesse | `jesse/services/metrics.py`: `sharpe_ratio` (71, ddof=1, periods=365), `sortino_ratio` (90), `calmar_ratio` (124), `cagr` (208), `trades` (309; win/loss streaks etc.) | Crypto-friendly defaults (365) |
| skfolio | `measures/_measures.py`: `get_drawdowns` (864), `max_drawdown` (955), `cdar` (1000), PSR/DSR (1302/1383); `model_selection`: `WalkForward(test_size, train_size, freq, expand_train, purged_size)` (`_walk_forward.py:243`), `CombinatorialPurgedCV(n_folds=10, n_test_folds=8, purged_size, embargo_size)` (`_combinatorial.py:192`) | Reference for PSR/DSR math and purged splitting |
| Riskfolio | `RiskFunctions.py`: `MDD_Abs` (825, uncompounded), `CDaR_Abs` (987), `UCI_Abs` (1161) | Note: uncompounded drawdown differs from the compounded one; pick one and state it |

### 4. Statistical robustness checks (concrete procedures)
1. **Concentration**: `top1_share = max(p_i)/sum(p_i)`, `top3_share`, `PnL_ex_best = sum(p_i) - max(p_i)`; pass if `PnL_ex_best > 0` and `top1_share < 40%` (our threshold, a design choice).
2. **Per-day / per-block PnL**: split the 72 h into 3 UTC days and 12 six-hour blocks; table of PnL, #trades, win rate, MDD each. Pass if >= 2 of 3 days positive, and no single day contributes > 70% of total. (With only 3 days, show 6h blocks to avoid a degenerate sample.)
3. **Trade-level bootstrap**: resample the `p_i` with replacement B=10,000 times (block size 3 to respect clustering); report median total PnL, 5th percentile, `P(total > 0)`, and the 95% CI of profit factor. Equivalent to a sign-flip (permutation) test of `mean(p_i)=0`. Cheap, 10 lines of numpy. Complements freqtrade `calculate_p_value` t-test.
4. **Fee/slippage stress**: replay with fees x1.5 and slippage x2; strategy must remain >= breakeven (judges re-run under similar conditions).
5. **Walk-forward**: freeze parameters, run the engine over rolling windows of the previous 4-8 weeks of Wallex-pair candles (e.g. 3-day windows stepping 1 day), list per-window return/MDD; show % windows positive and worst window. Use skfolio `WalkForward` semantics (`train_size`, `test_size`, `purged_size`) as the reference; with a rule-based + LLM policy "training" is only parameter selection, so use first N weeks to choose parameters and last weeks as out-of-sample. Add `purged_size` = max holding time.
6. **Parameter sensitivity**: grid over stop (1-3%), TP (2-5%), edge threshold, risk % (+/-25%); show a heatmap of return/MDD. A plateau (neighbouring cells similar) is the evidence, an isolated peak is overfit. If you tried N configs, report N and DSR (skfolio) to prove selection bias is accounted for.
7. **Regime split**: label windows up/down/flat by coin trend and report performance in each (shows profit is not pure beta); include buy-and-hold comparison.
8. **LLM stability**: temperature 0, store `prompt_hash`, `model`, `response`; replay run must reproduce identical orders; live run twice in shadow and report decision agreement rate (% identical action per decision point).
9. **Data sanity**: no look-ahead (decision uses candle close <= t), fees applied both legs, fills at bid/ask not mid.

### 5. Evaluation report layout (also the 5-minute demo storyline)
One generated artifact (`report.html` / `report.md`, produced by `python -m eval.report --run <id>`; seed and config hash printed):
1. **Header card** (10 s): run id, git commit, config hash, window, capital 5,000,000, **final value, Return %** (contest formula), MDD %, #trades, volume, fee total.
2. **Equity curve + drawdown underwater plot** with trade markers and breaker activations (risk gate events annotated).
3. **KPI table** (Section 1): return, MDD, return/MDD, per-period Sharpe + t-stat + PSR, Sortino, win rate, profit factor, expectancy (TMN and R), avg win/loss, exposure, turnover, fee drag.
4. **Robustness panel**: top-1/top-3 share, PnL ex best trade, per-day/6h table, bootstrap histogram with 5th percentile, sensitivity heatmap, walk-forward window bars.
5. **Decision-log excerpt**: 5 representative trades (best, worst, stop-out, time-stop, LLM-vetoed signal) each with signal, LLM rationale, gate result (binding cap), entry/exit, PnL: this is what proves "real AI use" and "no manual trade".
6. **Risk summary**: caps used vs limits (max gross exposure reached, largest position %, min TMN cash %), breaker/cooldown activations, kill-switch test result, final flatten confirmation (non-TMN balances = 0).
7. **Backtest vs shadow vs live comparison table** (same metrics; shows backtest/shadow was performed: 20 pts) and slippage observed vs assumed.
Demo timing (5:00): 0:00-0:30 architecture one-liner and where the LLM sits vs risk gate; 0:30-1:30 live/shadow decision with log (signal -> LLM reason -> gate -> order); 1:30-2:30 report header, equity/drawdown; 2:30-3:30 robustness panel (not one lucky trade); 3:30-4:15 risk gate: rejected order examples and flatten-to-TMN; 4:15-5:00 how to re-run (`make backtest`, `make report`) and results of reproduction.

## Comparison table (annualisation and conventions)
| Item | freqtrade | vectorbt | Nautilus | Jesse | Our choice |
|---|---|---|---|---|---|
| Return input | per-trade `profit_abs/starting_balance` | per-bar returns | per-day returns | daily balance returns | hourly equity returns |
| K | 365 | `year_freq/freq` | 252 default | 365 | 8,760 (if annualised) |
| Sortino denominator | std of losing trades | LPM over all obs | LPM over all obs | LPM over all obs | LPM |
| MDD basis | closed-trade cumulative profit | returns | compounded returns | daily returns | MTM equity |
| Zero-variance result | -100.0 | inf | NaN | n/a | NaN, shown as "n/a" |

## Reusable for our system
- Port (re-implement from formulas; ~150 lines numpy/pandas): MDD from equity (Nautilus/vectorbt form), Sharpe/Sortino/Calmar per Section 1, expectancy (freqtrade form), profit factor, SQN, PSR/DSR (skfolio BSD-3: can copy with notice, or re-implement from the docstring formulas), bootstrap (new, 10 lines). freqtrade code is GPL-3.0 and Nautilus LGPL-3.0: re-implement, do not paste. vectorbt is Apache-2.0 with Commons Clause (no selling the software): fine for use as a dependency in a hackathon, but writing our own metrics avoids the dependency.
- Optional: `pip install` skfolio only for `deflated_sharpe_ratio`; otherwise re-implement.
- freqtrade `MultiMetric` loss as a template for the parameter-selection objective (profit x PF x expectancy x winrate x trade-count penalty, drawdown-adjusted).

## Recommended design decisions for the hackathon
1. Single `metrics.py` with pure functions and unit tests on hand-computed cases (e.g. equity 5.0M -> 5.5M -> 5.2M -> 6.25M gives MDD 5.45%, return +25%, matching the requirements' own example 6,250,000 -> +25%).
2. Snapshot equity (balances x mid price, in TMN) every minute into `equity.csv`; the report samples hourly. Persist trades to `trades.csv` with entry/exit time, fees, PnL, risk-at-entry, exit reason.
3. Always run the same evaluator on backtest, shadow and live logs (same schema), so judges can compare (technical-test criterion "backtest + shadow", 20 pts).
4. Optimise the parameter-selection objective for return/MDD with a trade-count floor (>= 20 backtest trades); do not optimise raw Sharpe (noisy). Cap number of config trials and record N for DSR.
5. Publish an explicit "limits of evidence" note (short window, N trades, power); judges reward honesty and reproducibility.
6. Make the 3-day live window comparable to backtest by running the same code path (`--mode backtest|shadow|live`), same risk gate, only the broker adapter changes.

## Unverified / open questions
- Official judges' definition of drawdown (closed-trade vs mark-to-market, sampling interval) and whether unrealised P&L at checkpoints counts; we assume MTM account value.
- Lo (2002) standard-error formula and the PSR/DSR theory are cited from literature knowledge and the skfolio docstrings, not independently derived here.
- Pass thresholds in Section 4 (top-1 share < 40%, >= 2 of 3 days positive, day share < 70%) are our design choices, not repository standards.
- freqtrade/vectorbt/nautilus formulas were read from source, not executed; vectorbt `Sortino` default `required_return=0`; exact `portfolio/base.py` stats-table lines (win rate etc.) were read only through docstring examples.
- Wallex fee/min-notional assumptions in the fee-drag example are unverified (see file 03).
