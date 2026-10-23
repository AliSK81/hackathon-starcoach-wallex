# How the bot trades

This is the document for judges. It says what the bot does, why, and how to check it.
Details and dates are in [DECISIONS.md](DECISIONS.md) (D = decision, F = checked fact) and [PROGRESS.md](PROGRESS.md).

Contents: [In one paragraph](#in-one-paragraph) · [The live run](#the-live-run) · [Architecture](#architecture) ·
[One full cycle, step by step](#one-full-cycle-step-by-step) · [The AI roles](#the-ai-roles-in-detail) ·
[Tools](#the-traders-tools) · [Data and features](#data-and-features) · [Setups](#setups-named-patterns-as-evidence) ·
[Skills](#skills-the-traders-playbooks) · [Pace](#the-pace-follows-the-trading-time) ·
[Decision rules](#how-trades-are-decided) · [Sizing](#how-code-sizes-an-order) ·
[Orders and exits](#orders-and-exits) · [The guard](#the-guard-every-minute) · [Hard limits](#risk-and-capital-management-the-hard-limits) ·
[Failures](#when-something-fails) · [Memory](#memory) · [The owner note](#the-owner-note) ·
[Logs](#logs-and-how-to-check-them) · [Results](#results-so-far) · [Re-run](#how-to-re-run) · [Limits](#honest-limits)

## In one paragraph

Every 15 minutes, a LangGraph agent runs one decision cycle over every allowed Toman market that is liquid
enough (21 of 62 on 2026-10-22, picked again each cycle). An AI trader studies the markets with tools: features
and regimes, the live order book and trades from the Wallex MCP server, candles, what our tests on the past
found, and lessons from its own past trades. It decides like a trader: which markets to buy, how much to risk,
where the stop is, and the exit plan (target, time limit, trend turn, maker or taker), and which positions to
sell. A bull and a bear analyst argue each buy it proposes, and a judge approves, reduces or rejects it. Code
keeps only the hard limits (allowed markets, never all-in, stop and risk ranges, loss halts, what the order book
can take, the end of trading) and turns the trader's risk and stop into an order size. A guard checks every
stop and target on the live price each minute. After a trade closes, the AI writes a lesson for later cycles.
Every step is logged in a hash-chained file.

**The split of work.** The AI decides *what* to trade, *how much to risk* and *when to leave*. Normal code decides
*nothing about the market*. It only limits, sizes, places and watches orders. The AI never places an order and has
no tool that can.

## The live run

| Item | Value |
|---|---|
| Start capital | 5,000,000 TMN (the contest's base) |
| Real orders | from 2026-10-22, with `wx agent --live` under `scripts/keep_running.py` |
| Trading ends | 2026-10-26 17:30 UTC (21:00 Tehran) (D64). `data/end_at.txt` overrides `--end-at` at start. |
| Last 45 minutes | no new buys |
| Last 30 minutes | everything is sold into Toman, so the final value is all Toman |
| Account | one dedicated Wallex account. All orders come from the code in this repository. |
| Where to look | `data/live/trade_report.md` (every trade, rebuilt after every cycle), `data/live/decisions/` (every cycle), `data/live/orders.jsonl` (every order event) |

The version in this repository is the version that traded. Each live trade names the git commit it was decided
under (the report shows it), because the code was improved during the run.

## Architecture

```
                         every cycle (5, 15 or 30 minutes by the time left): one LangGraph run (brain.py)
 ┌────────┐   ┌───────────────────────────────┐   ┌─ bull (AI) ─┐   ┌────────────┐   ┌──────┐   ┌─────┐   ┌─────────┐   ┌─────────┐
 │ sense  │──>│ trader (AI agent)             │──>│             │──>│ judge (AI) │──>│ gate │──>│ act │──>│ reflect │──>│ journal │
 │ (code) │   │ tools · skills · memory       │   └─ bear (AI) ─┘   │ approve /  │   │(code)│   │(code)│  │  (AI)   │   │ (code)  │
 └────────┘   │ decides buys, plans, sells    │   argue its buys    │ reduce /   │   │ hard │   └─────┘   └─────────┘   └─────────┘
              └───────────────────────────────┘                     │ reject     │   │limits│
                                                                    └────────────┘   └──────┘
 Wallex REST: candles, best bid/ask, orders      Wallex MCP: order book, latest trades, candles (read only, no key)
 SQLite checkpointer: short-term memory           SQLite store: closed trades, lessons, each position's thesis

                         every minute: the guard thread (runner.py, live.py)
 stop and target on the live bid · unfilled sells sent again · old buys cancelled · market closes · sell everything before the end · KILL file
```

| Part | File | What it does |
|---|---|---|
| Wallex client | `wallex.py` | Public data and our account, standard library only. The key goes only in a header. |
| Wallex orders | `orders.py` | Place, read and cancel orders by our own `client_id`. Only code calls it. |
| Wallex MCP | `wallex_mcp.py` | The official MCP server, for the agent's book, trade and candle reads. Allowlist of 3 read tools. |
| Markets | `universe.py`, `markets.py` | Allowed markets (the exclusion list), the liquid ones, picked again each cycle. |
| Market closes | `closures.py` | Markets Wallex will close (`data/market_closes.json`): no new buys, held coins sold before the close. |
| Candles | `candles.py` | Saves 1-minute and 1-hour candles; a new market downloads only what the features need. |
| Features | `features.py`, `indicators.py` | 43 named features: 1h, 4h, 15-minute, 5-minute and 1-minute views, plus whole-market context. |
| Setups | `setups.py` | Named patterns the trader can cite as evidence (dips, trends). Not gates. |
| Pace | `horizon.py` | The time left sets how often the agent decides and how long it plans to hold. |
| Agent graph | `brain.py` | The cycle above: nodes, tools, prompts, the plan format, memory, evidence. |
| Skills | `skills/*.md` | Trader playbooks the AI reads when it needs them. |
| Hard limits | `risk.py` (`Envelope`, `size_plan`) | The only rules the AI can't change, and the sizing ladder. |
| Execution | `live.py`, `execution.py` | Real orders (`live.py`) or the shadow book (`execution.py`). Same methods. |
| Runner | `runner.py`, `scripts/keep_running.py` | The beat, the guard thread, halts, the kill file, the AI answer cache, restarts. |
| Decision log | `decide.py`, `live_report.py` | The hash-chained log and the judges' trade report. |
| Tests on the past | `backtest.py`, `study.py`, `agent_replay.py`, `scripts/` | Backtests, studies, the agent replayed on past moments. |

## One full cycle, step by step

The beat (`runner.py`) calls the graph once per cycle. The length of the cycle comes from the time left
([pace](#the-pace-follows-the-trading-time)): 5 minutes in the last 8 hours, 15 minutes before that, 30 minutes if
more than a week is left. The cycle starts on a round clock time (:00, :15, :30, :45 in the 15-minute pace).
In a second thread, the [guard](#the-guard-every-minute) runs every minute.

### 1. Sense (code, no AI)

1. **Pick the markets.** All Toman markets Wallex allows (the organizers' exclusion list is applied), then those
   that are liquid enough: at least 5 bn TMN traded in 24 hours, or at least 1 bn TMN with a live book that can take
   our size (spread at most 0.6%, at least 20 M TMN within 1% on both sides). Markets we hold, `BTCTMN` and
   `USDTTMN` always stay in (`universe.py`, D53).
2. **Compute the features** of each market, 8 markets at a time. The candles are brought up to date first, and the
   live best bid and ask are read. A market that fails is dropped for this cycle and the rest go on.
3. **Add the whole-market context** to every market: `usdt_trend_up` (is the Toman weakening?) and `btc_ret_24h_pct`
   (the market's mood), and check the setups again with them.
4. **Sync our book.** Every open order is read back from Wallex by its `client_id`. Fills are booked. Buys that
   waited too long are cancelled. The code exits (stop, target, trend turn) are applied.
5. **Read the account.** Equity is the real Toman balance plus the coins at today's prices. The peak, the day's
   starting equity and the drawdown come from it. Each position is valued at the **bid**, not the mid price, and
   shows its spread (F88).
6. **Prepare the state.** Hours left, the pace profile, each position's thesis from memory, and the `lean` flag
   (set when the AI failed 3 cycles in a row or the day's token budget is spent: then the debate is skipped).
7. If no market has features at all, the cycle goes straight to the journal. Nothing is bought.

### 2. Trader (AI agent with tools)

The trader gets its instructions (the system prompt) and a first message of facts, then calls tools until it
answers. See [The AI roles](#the-ai-roles-in-detail). It ends with one JSON plan: buys, sells, and a short view.

Right after the trader, **code runs the pre-buy checks** for every buy it proposed. It reads the live order book and
the last 12 five-minute and 8 fifteen-minute candles from the Wallex MCP server. The AI often skipped these checks
(F84). Now the bull, the bear and the judge always see them, and the book-depth size limit always applies.

### 3. Bull and bear (AI, in parallel)

Only if the trader proposed at least one buy, and the cycle is not `lean`. Two separate AI calls get the same data
(the buys, their markets, the books, the candles, BTC, the evidence). One argues for each buy, one against.

### 4. Judge (AI)

It reads both cases and each buy, and returns APPROVE, REDUCE (with a lower `risk_pct`) or REJECT, with a reason.
It approves by default and rejects only for a concrete risk in the data.

### 5. Gate (code)

`check_plan` turns the plan into decisions. It never invents a trade:

- A buy for a market already held, asked twice, or without features is dropped, with a note in `problems`.
- Values are clamped into the envelope: `risk_pct` 0.05 to 3, `stop_pct` 1 to 15, `max_hours` up to the pace's
  limit (and 72 at most), `order` is `maker` unless the AI said `taker`.
- A REJECT becomes a HOLD (no order). A REDUCE sets the risk to the smaller of the trader's and the judge's.
- Buys are sorted by the trader's conviction, so the strongest gets the free cash first.
- A sell for a market we do not hold is dropped.

### 6. Act (code)

1. If 30 minutes or less are left: sell everything (`flatten`).
2. Execute each SELL: cancel an unfilled buy, or send a sell for an open position.
3. For each BUY, in order: refuse if Wallex closes the market soon, refuse if the bot is halted, then `size_plan`
   ([sizing](#how-code-sizes-an-order)). If the size is at least the minimum order, the buy is placed. The trader's
   thesis (strategy, reason, invalidation, exit plan) is saved in memory.
4. Collect the trades that closed since the last cycle (from this cycle's sync and sells, and from the guard).

### 7. Reflect (AI, only after closed trades)

For each closed trade the reviewer sees the buy thesis and the sell reason, and writes one lesson. The lesson and
the trade are stored for later cycles. See [Memory](#memory).

### 8. Journal (code)

One record is written to the hash-chained log: the features of every market, the plan, the bull and bear cases, the
judge's review, every decision with its verdict, the orders, the closed trades, the lessons, every tool call and its
result, the AI's tokens, any problems, and the code version. A one-line summary of the cycle goes to the
short-term memory. After the cycle, the judges' trade report is rebuilt.

## The AI roles in detail

All five roles use the same model, set in `.env` (`LLM_BASE_URL`, `LLM_MODEL`; any OpenAI-compatible API) at
temperature 0 (where the model allows it). Every call and answer is saved in `data/brain/llm_cache.sqlite`.

| Role | Kind | Sees | Returns |
|---|---|---|---|
| Trader | agent with 12 tools (LangChain `create_agent`, a LangGraph subgraph) | instructions, playbooks, evidence, hard limits, facts; tools for more | the plan: buys, sells, view, approach |
| Bull | one JSON call | the proposed buys, their features, books, candles, BTC | a case for each buy and a strength 0 to 1 |
| Bear | one JSON call | the same | a case against each buy and a strength 0 to 1 |
| Judge | one JSON call | the buys, the plan's approach, both cases, books, candles, account | APPROVE / REDUCE / REJECT for each buy |
| Reviewer | one JSON call | each closed trade with its thesis and sell reason, past lessons | one lesson per trade |

### The trader

**Goal in its instructions:** the highest Toman value when trading ends. A loss scores zero, a smaller drawdown
scores, regular trading scores a little. Spot only, long only, Toman markets.

**What it decides:** which markets to study, whether to buy, `risk_pct`, `stop_pct`, an optional target, the longest
hold, whether to sell when the trend turns, maker or taker, which positions to sell. Nothing is bought unless it asks.

**What is in its system prompt** (the same every cycle of a pace, so the provider can cache it, D47): the
instructions, the hard limits, the meaning of each setup, the evidence from our tests, the list of skills, the
playbook `trader-core`, and the playbook of the pace (`sprint-trading` when 24 hours or less are left).

**What is in its first message (the facts, new every cycle):**

| Fact | Meaning |
|---|---|
| `owner_instructions_do_these_first` | The owner's current note, if any ([The owner note](#the-owner-note)). |
| `now_utc`, `hours_left`, `profile` | The time and the pace. |
| `account_tmn`, `positions` | Equity, cash, coins, peak; each position with its entry, value, P&L, stop, target, time limit, spread, and `past_time_limit`. |
| `our_result` | Written in words: "-1.2% since the start, +0.3% today, 1.5% below the peak". A model once read `drawdown_pct 0.25` as 25% (F75). |
| `buys_last_24h` | For the 60-a-day cap. |
| `markets_overview` | One row per liquid market, with the main features, `move_x_cost`, and the active setups. In sprint the row leads with fast features. |
| `markets_closing_utc` | Markets Wallex will close. |
| `your_last_cycles` | Its own last 8 cycle summaries (3 if an owner note exists, because old notes repeat old rules, F80). |
| `lessons_losses_first` | Up to 6 lessons from past trades. |
| `your_thesis_per_position` | Why it bought each position it holds, and what would prove it wrong. |

**Rules in its instructions** (it must follow them; code checks only the hard limits):
- Never invent a number. Name the features used.
- Read `move_x_cost` before a buy: the market's typical 24-hour move divided by its round-trip cost. Near 1, even a
  good call earns nothing. Prefer 3 or more. Under 2 needs a very strong reason. (Its own judgment, D56.)
- A position with `past_time_limit: true` is not sold by code. Each cycle it decides: keep (the reason still holds)
  or sell. It should not sell a good coin only to buy it back soon: that pays about 0.6% for nothing (D62).
- Never propose a buy in a market in `markets_closing_utc`.
- The envelope limits apply to new buys only. Never sell a position only to fit a limit (F74).
- USDTTMN is a market like the others. Holding USDT is its choice (D48).
- Work in order: read the overview, find opportunities (`get_regime`, `get_market`, `list_markets`), check evidence
  (`get_evidence`, `get_orderbook`, `get_candles`, `recall_lessons`), size with `check_order`, decide. At most 12 tool calls.

**Its answer** (one JSON object):

```
market_view, approach,
buys:  [{symbol, strategy, risk_pct (0.25-3), stop_pct (1-15), target_pct (or null), max_hours,
         exit_on_trend_turn, order (maker|taker), conviction (0-1), reason, cited[], invalidation}],
sells: [{symbol, reason}]
```

A sell closes the whole position. There are no partial sells. Positions not in `sells` keep their exit plan.

**Middleware around the agent:** a tool-call cap of 12 (then it must answer), one retry of a failed tool after 2
seconds (the MCP server can be slow), and clearing of old tool results past 16,000 tokens (keeping the newest 4;
the portfolio is never cleared), because the model's window is small (F59). If the answer is not valid JSON or has
the wrong shape, the trader is asked once more in JSON mode. If it still fails, the cycle counts as a failed AI
call and nothing is bought.

### Bull and bear

Each is told to make the strongest honest case for its side, using only the numbers given, citing feature names.
They return, per buy: an argument of at most 250 characters, the features used, and a strength from 0 to 1. They run
in parallel and see the pre-buy checks (book and candles). If one fails, the judge decides without it.

### The judge

It weighs the two cases against the data and the evidence, and may APPROVE, REDUCE (new lower `risk_pct`) or REJECT.
Its instructions tell it to approve by default. It reduces or rejects only for a concrete risk beyond the coin's usual
swings:

- no buyers near the price in the book;
- the move already done in the last 5 and 15-minute candles;
- a spread over 1%;
- a stop the market can't respect;
- overbought and stretched (`rsi14` over 70 with `bb_z_20` over 2): wait for a pullback;
- no recent volume for a momentum buy (`vol_ratio_5m` near 0);
- no trend for a trend buy (regime range and `adx14` under 20);
- a number in the trader's reason that is not in the data.

It must not cut a buy only for weak 5-minute momentum or a small edge: every buy has those, and cutting all of them
left the account in cash (F76). It always gives a reason, also when it approves.

### The reviewer

After a trade closes, it sees the closed trade (result, entry, exit, how it ended), the thesis from the buy, and the
sell reason. It judges the buy and the sell separately: was the buy reason sound, and did the sell follow the plan
or a mistake? It uses `net_pct_with_left_coin`, which counts leftover coin too small to sell. It writes one lesson of at
most 300 characters, using the playbook `post-trade-review`: what the setup and reason were, what happened, and one
concrete thing to check next time. It must not invent fields (F85).

## The trader's tools

All tools are read-only. Only `get_orderbook` and `get_candles` call the Wallex MCP server. None can place an order.

| Tool | What it gives | Source |
|---|---|---|
| `get_portfolio` | Equity, cash, positions with exit plans, today's result, drawdown, buys in 24 hours, the hard limits. | our book |
| `list_markets` | Every allowed Toman market with Wallex's 24-hour volume and change, and whether it is in the overview. | Wallex REST |
| `get_market` | All 43 features of any allowed market (computed on demand for markets outside the overview). | candles + live book |
| `get_regime` | Volatility, trend, direction, volume, Hurst exponent, and the playbook for that regime. | candles |
| `get_evidence` | What our tests found: setups over 12 hours, rule sets by horizon, exits, time of day, how big 12 hours can be, the AI's own record, costs, fast strategies. | our tests |
| `get_orderbook` | Live book and the last 50 trades: spread, Toman within 1% per side, imbalance, buyer share, trades per minute, the cost of filling 500k and 1.25M TMN. | **Wallex MCP** (REST if it fails) |
| `get_candles` | 5, 15 or 60-minute candles (at most 24), prices as % from the first open. | **Wallex MCP** |
| `get_hourly_closes` | The last N hourly closes (N at most 72), as % from the first. | saved candles |
| `check_order` | What code would do with a buy at this risk and stop: size in Toman and the limit that set it, or why it refuses. Nothing is ordered. | `risk.size_plan` |
| `recall_lessons` | Lessons from past trades, losses first, filtered by market or setup. | memory |
| `explain_features` | The meaning of any feature. | `features.py` |
| `read_skill` | The full text of one playbook. | `skills/*.md` |

**Wallex MCP.** The server at `https://api.wallex.ir/mcp` has 52 tools. We allow three read tools:
`wallex_basic_get_market_depth`, `wallex_basic_get_latest_trades`, `wallex_basic_candle_history`. Any other name raises
an error. We never send our API key to it. The raw answers are long, so code reduces them to a short summary. If the
MCP server fails, the same numbers come from the REST API and the summary says which source was used.

## Data and features

**Candles.** Wallex 1-minute and 1-hour candles are saved to `data/candles/`. A live market needs about 750 closed
hourly candles for the long averages, and keeps 43 days of hourly and 4 days of 1-minute candles. Only closed candles
feed the hourly indicators. Returns use the live mid price.

**The 43 features**, by group (every one has a fixed name that the AI cites, and `explain_features` gives its meaning):

| Group | Features |
|---|---|
| Price and cost | `price`, `spread_pct`, `round_trip_cost_pct` (two taker fees + spread), `typical_24h_move_pct` (median 24-hour move over 30 days), `move_x_cost` (in the overview) |
| Returns | `ret_5m_pct`, `ret_15m_pct`, `ret_30m_pct`, `ret_1h_pct`, `ret_4h_pct`, `ret_24h_pct`, `ret_72h_pct` |
| 1-hour trend | `ema20_vs_ema50_pct`, `price_vs_ema200_pct`, `ema20_slope_5h_pct`, `adx14`, `plus_di14`, `minus_di14`, `macd_hist_pct`, `regime` |
| 1-hour stretch | `rsi14`, `bb_z_20`, `bb_pos_20`, `zscore_48h`, `donchian20_pos`, `breakout_up` |
| Volatility and volume | `atr14_pct`, `atr_pctile_100`, `vol_ratio_20`, `zero_volume_hours_24` |
| Slower and faster views | `trend_4h_pct`, `rsi14_15m`, `ema9_vs_ema21_5m_pct`, `rsi14_5m`, `bb_z_5m`, `atr14_5m_pct`, `vol_ratio_5m`, `vwap_4h_dev_pct`, `range_1h_pct`, `pos_in_1h_range` |
| Whole market | `usdt_trend_up` (the Toman is weakening), `btc_ret_24h_pct` |
| Bookkeeping | `data_age_min`, `setups` (the setups whose rule holds now) |

**The regime** (`get_regime`, the installed regime-detection skill): volatility is low, normal or high by the ATR's
rank over 100 hours (under 0.3, over 0.7); trend is trending (ADX over 25), ranging (under 20) or transitional;
direction comes from the EMA 20 slope and its place against the EMA 50; volume is high above 1.5 times the average,
low under 0.5. The **Hurst exponent** over 100 hours says if the price reverts (under 0.4), trends (over 0.6) or is
random. The playbook for each regime:

| Volatility | Trend | Play |
|---|---|---|
| low | trending | clean trend: trend following, normal stops |
| normal | trending | trend following |
| high | trending | momentum at half size, wide stops |
| low | ranging | quiet range: mean reversion |
| normal | ranging | mean reversion at the edges |
| high | ranging | choppy: a quarter size or sit out |
| any other | transition | small size or wait |

**Order-book summary** (`get_orderbook`): `spread_pct`, `bid_tmn_within_1pct` and `ask_tmn_within_1pct`,
`imbalance_1pct` = (bids − asks) / (bids + asks), `buy_Nk_cost_pct` and `sell_Nk_cost_pct` (how far from the mid an
order of 500,000 and 1,250,000 TMN would fill on average), and from the last 50 trades: `buy_share` (share of money in
buyer-initiated trades), `trades_per_min`, `tmn_traded`, `last_price`.

## Setups: named patterns as evidence

A setup is a rule on the features, with textbook thresholds that were not tuned. The trader can cite a setup as
evidence. It is **not a gate**: the trader may buy with no setup, or skip a setup that fired (D43). Each setup has an
exit meaning and a grade from our tests (A: beat the costs over 12 hours in both halves of the history and on both
market sets, F41; B: mixed).

| Setup | Entry rule | Grade | Evidence (12 hours, after costs) |
|---|---|---|---|
| `capitulation` | `rsi14` < 25 and `bb_z_20` < −2 | A | +0.41% a trade, 229 trades |
| `stretched_dip` | `bb_z_20` < −2.5 | A | +0.25%, 560 trades |
| `dip_toman_weak` | `bb_z_20` < −2, `rsi14` < 30, `usdt_trend_up` | A | +0.31%, 189 trades |
| `trend_strong` | EMA 20 > EMA 50, ADX > 25, +DI > −DI, Toman not getting stronger, BTC up over 24 hours | B | +0.31% overall, but +0.78% then −0.51% by half |
| `trend` | EMA 20 > EMA 50 | – | −0.05%; −0.32% when the Toman gets stronger |
| `sharp_drop` | `ret_24h_pct` ≤ −2 × `typical_24h_move_pct` | – | older, 24-hour hold (F19, F22) |
| `oversold` | `rsi14` < 30 | – | older, 24-hour hold |

## Skills: the trader's playbooks

Eleven Markdown files in `skills/`. Each has a header (name and one-line description). The trader reads
`trader-core` and the playbook of its pace in its instructions, and can call `read_skill` for any other.

| Skill | What it teaches |
|---|---|
| `trader-core` | The goal, the costs, the facts that rule everything, and the 8-step checklist before every buy (regime, evidence, book, shape, whole market, lessons, plan, what would prove it wrong). |
| `risk-and-sizing` | Risk tiers (0.5–1% weak, 1–2% good, 2–3% best), how code sizes, the hard limits, the response to a drawdown. |
| `exit-planning` | Stop (2–4 × the hourly ATR), why fixed targets and trailing stops did worse in our tests, time limit, trend-turn exit, maker or taker. |
| `market-regime` | How to read `get_regime` and which play fits each regime. |
| `mean-reversion-dips` | Deep dips: good signs (fast fall, volume flush, buyers near the price, 15-minute RSI turning) and "falling knife" warning signs. |
| `trend-following` | Confirmations (ADX, 4-hour trend, BTC up) and warning signs (late, stretched entry). |
| `order-book-and-flow` | How to read depth, imbalance and buy share; when sell pressure is real. |
| `toman-usdt-regime` | Why the Toman against USDT moves every coin, and how to read `usdt_trend_up`. |
| `sprint-trading` | Trading with less than a day left: what 1-minute tests found, and a strategy-by-time-left map. |
| `session-end` | Trading against a deadline: what `hours_left` changes. |
| `post-trade-review` | How to write a useful lesson. |

## The pace follows the trading time

The time left until trading ends sets the pace (D45, D52, `horizon.py`):

| Time left | Profile | Decisions | Data read first | Holds the trader may plan | Limit buys wait |
|---|---|---|---|---|---|
| 8 hours or less | sprint | every 5 minutes | 1, 5, 15-minute candles, the live book | up to 6 hours | 10 minutes |
| up to 7 days | short | every 15 minutes | 15-minute and 1-hour candles | up to 48 hours | 30 minutes |
| more than 7 days, or no end | swing | every 30 minutes | 1-hour and 4-hour candles | up to 168 hours (72 at most, the envelope) | 60 minutes |

The profile moves to sprint by itself as the end comes closer. Sprint starts only in the last 8 hours because the
setups with an edge need holds up to 12 hours (D52). With 24 hours or less left, the trader's instructions also
include the sprint playbook and its strategy-by-time-left map (D59). In sprint the overview leads with the fast
features. Our tests on 1-minute data showed that standard fast strategies lose 0.3% to 0.95% a trade on Wallex after
costs (F62), so the playbook uses fast data to time good trades and exit failing ones quickly, not to trade more.

## How trades are decided

The trader decides each trade (D43). The skills give it the playbooks:

- **Which markets:** any allowed Toman market. The overview has every liquid one; `list_markets` and `get_market`
  reach the rest.
- **When to buy:** from the regime (`market-regime`), the evidence (`get_evidence`), the book and the shape.
  Named setups (deep dips, strong trends) are evidence it can cite, with their measured records. It checks the book
  and the 5 and 15-minute candles before a buy.
- **How much:** `risk_pct` from the tiers of the position-sizing skill (0.5–1% weak, 1–2% good, up to 3% best).
- **Exit plan:** a stop from about 2 to 4 times the hourly ATR; an optional target; a time limit; an optional exit
  when the trend turns; maker or taker (`exit-planning`). Our tests showed fixed targets and trailing stops did
  worse, and the skill says so.
- **Selling:** any position, any cycle, with a reason. Typical reasons in the live log: the trend turned
  (`ema20_vs_ema50_pct` fell below 0), the move was too small for the cost (`move_x_cost` low, wide spread), the
  position was flat or down for hours, or the thesis was invalidated.

## How code sizes an order

`risk.size_plan` turns the trader's `risk_pct` and `stop_pct` into Toman:

1. **Clamp** `risk_pct` to 0.05–3 and `stop_pct` to 1–15.
2. **Refuse** if: fewer than 45 minutes are left; equity is more than 4% under the day's start; equity is more than
   10% under the peak; the data is older than 5 minutes; 60 buys have been made in 24 hours.
3. **Risk size** = `risk_pct` of equity ÷ (`stop_pct` + round-trip cost). So a stop-out loses about `risk_pct` of equity,
   with fees and spread included.
4. **The ladder.** The order is the **smallest** of:
   - the risk size;
   - the room in one coin: 20% of equity;
   - the room in coins: 85% of equity minus what is held; 95% in the last 3 hours (D61, D63);
   - free Toman cash;
   - half of the Toman resting within 1% on the ask side (`book_share`), when the book is known.
   `USDTTMN` counts as cash: up to 98% of equity, outside the coin limits (D51).
5. **Refuse** if the result is under Wallex's minimum order (50,000 TMN).
6. The verdict names the limit that set the size (`approved`, `max in one coin`, `book depth`, ...). It is logged.

Example: equity 5,000,000, risk 1%, stop 4%, round-trip cost 0.6%. The risk size is 50,000 ÷ 0.046 ≈ 1,087,000 TMN.
One coin may hold at most 1,000,000. So the order is 1,000,000, "shrunk to the max in one coin limit".

## Orders and exits

### Placing a buy (`live.py`)

1. The market must be allowed and must not be on the exclusion list. A buy in any other market is refused, and the
   refusal is logged (a hard contest rule, D3).
2. The best bid and ask are read. A **maker** buy is a LIMIT order at the best bid. A **taker** buy is a LIMIT order at the
   best ask, so it fills at once.
3. Price and quantity are rounded to the market's rules (decimals, minimum quantity and value, `rules.py`).
4. The order carries our own `client_id`. After a timeout or a restart, the order is read back from Wallex by this id, so
   it is never sent twice.
5. A buy that has not filled within the fill window (10, 30 or 60 minutes by the pace) is cancelled. Any part that filled
   is kept as a position.

### Selling

A sell is a LIMIT order 0.5% under the best bid, so it fills at once against the bids like a market order, but never
far below the price (not every market allows MARKET orders, F9). If it has not filled within 60 seconds, it is
cancelled and sent again at the new bid. A remainder too small for the minimum order is left as dust and the
position is closed. The report shows both the result and the result with the leftover coin.

### Exits

| Exit | Who decides | When |
|---|---|---|
| Stop | code | The price is at or under the entry minus `stop_pct`. Checked on the live bid every minute (guard), and on the price at each cycle. |
| Target | code | The price reaches the entry plus `target_pct`, if the trader set one. |
| Trend turn | code | `exit_on_trend_turn` was set, the trend was up at some point while held, and the 1-hour EMA 20 fell under the EMA 50. |
| Trader's sell | the AI | Any cycle, with a reason. |
| Time limit | the AI | `max_hours` passed: the position shows `past_time_limit`. Code does **not** sell; the trader decides each cycle (D62). |
| Market closes | code | 30 minutes before Wallex closes a market in `data/market_closes.json`. |
| End of trading | code | 30 minutes before the end, everything is sold into Toman, and the guard keeps trying every minute. |
| Kill switch | the operator | `uv run wx kill` or the file `data/KILL`: cancel every open order and sell every position. |

The stop and the exit plan come from the trader. The price at which they act is checked by code. A trade can
close in a way the trader did not choose only by the stop, the target, the trend turn, a market closing, the end of
trading or the kill switch.

## The guard: every minute

A separate thread (`runner.guard_loop`) runs every 60 seconds, between cycles, so a stop does not wait for the next
decision:

1. If `data/KILL` exists: cancel and sell everything, then stop the run.
2. If 30 minutes or less are left: sell everything, push unfilled sells again.
3. For each position: sell if its market closes soon; for an open one, read the live bid and sell at the stop or the
   target; for a sell in progress, check it and resend if needed; cancel a buy past its fill window; book a buy that
   filled, so its stop is watched at once.
4. If the guard fails 3 rounds in a row, the bot is halted (no new buys) until a clean cycle. The guard itself never dies.

## Risk and capital management: the hard limits

All in `risk.py` (`Envelope`) and `live.py`, normal code. The AI can't change them. Values follow the installed
risk-management and position-sizing skills. Current values:

| Limit | Value |
|---|---|
| Loss if a stop is hit, costs included | at most 3% of equity (the trader usually picks 1–1.5%) |
| Stop distance | 1% to 15% under the entry |
| In one coin | at most 20% of equity (D54) |
| In coins together | at most 95% of equity (D61); new buys stop at 85% until the last 3 hours (D63) |
| Never all-in | follows from the two limits above |
| Daily loss halt | no new buys after losing 4% in a UTC day |
| Drawdown halt | no new buys while equity is 10% under its peak. The peak resets after equity has stayed more than 6% under it for 24 hours, so one bad day can't stop trading for good. |
| Buys per day | at most 60 in 24 hours |
| Data age | no buys on data older than 5 minutes |
| Order vs the book | at most half the money resting within 1% on the ask side |
| Minimum order | Wallex's minimum (50,000 TMN) and decimals |
| Longest planned hold | 72 hours |
| Allowed markets | the organizers' exclusion list is applied every cycle, and again at order time |
| No new buys | in the last 45 minutes, and 45 minutes before a market closes |
| Sell everything | 30 minutes before the end, and 30 minutes before a market closes |
| Kill switch | `wx kill`, or a file `data/KILL` inside the running bot |
| After failures | 3 failed cycles or guard rounds in a row: no new buys until a clean cycle |

Each verdict names the limit that set the size, and is logged.

The older backtest and shadow loop also has risk modes (`defensive`, `normal`, `active`, `aggressive`) in `risk.py`.
They were used to test rule sets (F53). The live agent uses the envelope above, not the modes.

## When something fails

The design rule: **fail closed**. A failure never causes a buy. Held positions keep their stops.

| Failure | What happens |
|---|---|
| The AI call fails, or its plan has the wrong shape after one retry | No new buys that cycle. Positions keep their exit plans and stops. The failure is logged. |
| 3 failed AI cycles in a row, or over the day's token budget (12 M) | "Lean" mode: the bull, bear and judge are skipped, so each cycle costs less. |
| The bull, bear or judge fails | The judge decides without that side, or the trader's plan stands inside the hard limits. |
| A market's features fail | That market is left out of this cycle. |
| The Wallex MCP server fails | The same numbers come from the REST API. The summary says which source was used. |
| A graph cycle raises an error | It is logged (also in the hash chain) and the bot goes on at the next beat. 3 in a row: no new buys until a clean cycle. |
| The process stops | `scripts/keep_running.py` restarts it, until trading ends or `data/KILL` exists. The book, orders and memory are on disk, so nothing is lost. Orders are read back by `client_id`. |
| An order is rejected by Wallex | The error is logged with the order, and no position is booked. |
| A market is about to close | See `data/market_closes.json` (D50). |

## Memory

| Kind | What it keeps | Where | How it is used |
|---|---|---|---|
| Short term (LangGraph SQLite checkpointer) | the state after every cycle, and a one-line summary of each cycle | `data/brain/live_checkpoints.sqlite` | the trader sees its last 8 cycles (3 with an owner note) |
| Long term (LangGraph SQLite store) | closed trades, lessons, each open position's thesis | `data/brain/live_memory.sqlite` | lessons are recalled with losses first (6 in the facts, more via `recall_lessons`); the thesis is shown while the position is held and deleted when it closes |
| Our book | positions, peak, the day's start | `data/live/book.json` | restart safety |
| Order events | every order event | `data/live/orders.jsonl` | audit, the trade report |
| AI answers | every AI call and answer | `data/brain/llm_cache.sqlite` | `WX_LLM_REPLAY=1` re-runs a cycle with the saved answers |

## The owner note

The owner of the account can leave the trader a note in `data/owner_note.txt`. It is read every cycle and shown to
the trader and the judge as `owner_instructions`. The file holds only the current note. The decision log does not copy
the note text, but each trade's AI reason and "approach" say how the AI followed it.

What the note is for: it sets **style and risk appetite** (D49, D54, D57–D61). For example: use more of the balance over
time, spread over several coins, prefer moving coins with a high `move_x_cost`, keep about 15% free for new chances,
check the book and the candles before a buy, and review every held position each cycle with a keep-or-sell rule.

What the note is not for: the contest forbids manual trades. The note gives rules for the AI to apply, never an order to
buy or sell a named coin at a named time (D58). The AI still picks every market, every size, every stop and every exit.
Code applies the same hard limits whatever the note says. The trade report shows the AI's own reason for each trade, and
some of its strategy labels quote the note ("owner pick" means the AI chose a coin that the note's rules favour).

**An honest record:** on 2026-10-23 at about 07:25 UTC the note named one coin (TRXTMN) as an example of a quiet coin to
sell. At 07:35 it was rewritten as a general rule that the AI applies to every held position (D58). The AI's own reason
for each sell is in the decision log.

## Logs and how to check them

| Where | What | How to check |
|---|---|---|
| `data/live/decisions/<day>.jsonl` | One record per cycle, hash-chained (each record holds the hash of the previous one and its own) | `uv run wx verify-log --live`: reports any changed record or broken link |
| `data/live/trade_report.md` | The judges' per-trade report, rebuilt after every cycle | `uv run wx tradelog --live` rebuilds it |
| `data/live/orders.jsonl` | Every order event: placed, bought, cancelled, sell placed, closed, failures | read with any JSON tool |
| `data/live/book.json` | The current positions | `uv run wx live` |
| `data/brain/live_run.log`, `supervisor.log` | The agent's console output; starts and stops | read |
| `data/brain/llm_cache.sqlite` | Every AI call and answer | `WX_LLM_REPLAY=1` |

**What each cycle record holds:** the code version, the features of every market, the account and positions, the order-book
summaries and candles, the trader's plan, the bull and bear cases, the judge's review, every decision with its risk-check
verdict, the orders, the closed trades, the lessons, every tool call with its (shortened) result, the AI's tokens and
seconds, and any problems. A cycle that fails is logged too.

**What the trade report shows for each trade:** when it was decided and under which code version; the signal the
code saw with the numbers; the AI's strategy, conviction, reason and what would prove it wrong; its plan (risk, stop,
target, hold, trend exit, maker or taker); the judge's review; the code's risk check; the fill; the exit with its
reason and Wallex's average exit price; the result; and every order event. Because each trade has an AI reason, a
signal, a code version and a client order id, a trade made by hand would stand out.

## Results so far

All numbers are after fees (Wallex maker 0.25%, taker 0.30%, F3) and spread.

**Over 12 hours**, which is close to a short contest (F41, F42, F45):

| Test | Result |
|---|---|
| Every market hour, buy and sell 12 hours later | -0.26% |
| Hold USDT for 12 hours | -0.31% |
| Old trend rule, 12-hour windows, sold into Toman | -0.14% on average, worst -3.31% |
| Agent setups, 12-hour windows, sold into Toman, old limits | -0.07% on average, worst -2.69%, no trade in 35% of windows |
| Agent setups, 12-hour windows, agent limits (D38) | -0.04% on average, worst -1.43%, drawdown 4.6%, no trade in 61% of windows |
| The same on 12 markets not used to pick the rules | -0.08% on average (was -0.18%), worst -4.38% (was -4.61%) |
| Deep dips (capitulation), one trade | +0.41% after costs, positive in both halves and on both market sets |

What this means:
- Over 12 hours, costs (about 0.5% to 0.8% a round trip) are larger than the usual move. No simple rule earned on
  average. The setups we trade lose less, and their worst window is smaller. Their result in a single window is
  close to a coin flip.
- That is why the bot buys rarely and small, and only where the evidence is best. The agent limits halve the
  average loss and the worst window, at the price of fewer trades.
- Most of the Toman's fall against the dollar happened in Tehran daytime (F44). In Tehran evening and night, the
  drift was close to zero.

**Every test, on the current agent rules** (F49, `scripts/test_all_scenarios.py`). Limit orders, after costs.
Our 6 TMN markets / 12 other TMN markets / 6 USDT markets (no Toman drift):

| Test | Agent (current) | Old trend rule | Hold every market |
|---|---|---|---|
| Whole 89 days | +3.1% / +18.5% / -0.3% | +35.7% / +34.5% / -8.4% | — |
| Max drawdown | 4.6% / 12.2% / 6.9% | 8.2% / 13.1% / 16.9% | — |
| 1st half, 2nd half | both positive on both TMN sets | both positive on TMN, lost without the drift | — |
| 3-day windows, average (worst) | -0.03% / +0.26% / -0.02% (-1.9% / -5.1% / -1.5%) | +0.54% / +0.20% / -0.44% | +1.58% / +2.33% / +0.39% (-7.8% / -10.2% / -9.4%) |
| 1-day windows | -0.04% / -0.04% / -0.02% | -0.01% / -0.21% / -0.30% | +0.14% / +0.30% / -0.30% |
| 12-hour windows | -0.04% / -0.08% / -0.02% | -0.14% / -0.25% / -0.27% | -0.25% / -0.20% / -0.49% |

- The agent has the smallest drawdown and the smallest worst window in every test, and it does not lose when the
  Toman drift is taken out. Over 12 hours and 1 day it is the best of the systems tested.
- It earns little. Over days, the old trend rule and plain holding made more, because the Toman fell. They also
  lost 2 to 4 times as much in their worst windows, and the trend rule lost 8% without the drift.

**The agent deciding its own trades, on 20 past moments** (F58, `wx agent-replay`): it stayed out at 16 and
bought at 4. Its account result averaged -0.03% a moment (worst -0.26%). At the same moments the fixed rules lost
1.14% a trade and holding every market lost 0.81% on average (worst -3.40%). In a falling period it avoided most
losses by not trading, and made almost no profit.

**By setup** (F50): dips alone made +3.1% on our markets and lost 4.1% on the other 12. trend_strong alone lost
1.2% on ours and made 27.6% on the other 12. Neither is reliable alone, so the agent keeps both.

**The whole agent on past moments** (F51, `wx agent-replay`): 20 moments, all with trend_strong candidates, in a
period where trend_strong lost. Every candidate: -2.37% per trade. The agent's buys, weighted by the size it allowed:
-1.79%. It gave low conviction every time and the officer cut 18 of 22 buys, so the AI shrank the losers. It could
not stop them: none of the checked vetoes applied.

**Over many days** (the older results, F25, F28, F33):

| Test | Result |
|---|---|
| Backtest, 88 days, our 6 markets, trend rule | +35.6%, worst drawdown 8.2%. Both halves positive. |
| Backtest, 88 days, 12 other markets | +34.5%, worst drawdown 13.1% |
| AI replay, checked veto plus tools | AI buys +1.34% each, all trend buys +1.24%, the 7 it stopped -0.88% |

Much of the multi-day profit came from the Toman losing value. Without that drift, the trend rule lost in the
2nd half on 4 of 5 coins (F36).

**Shadow trading:** 40 cycles of the older agent with no crash. The first trade closed at its stop exactly as the
backtest models it (F39). The new graph runs in shadow too: `wx shadow` and the log in `data/decisions/`.

**Live trading:** the result, the trades and the AI's reasons are in `data/live/trade_report.md`, rebuilt after every
cycle. The live account's return is computed in the contest as (final value − 5,000,000) ÷ 5,000,000, with everything
sold into Toman.

## How to re-run

```bash
uv run wx                            # install, and show which keys are set (copy .env.example to .env first)
uv run wx candles                    # 120 days of candles (about 15 minutes the first time)
uv run wx backtest --hours 12        # 12-hour windows: agent setups, dip setups, the old trend rule
uv run wx backtest                   # the multi-day backtest
uv run wx study                      # each setup over the history
uv run wx agent --shadow --end-at 2026-10-27T00:30   # the agent on every liquid allowed market, fake orders
uv run wx order-test USDTTMN         # a real order check: a buy 20% under the price, read back, cancelled
uv run wx agent --live --end-at 2026-10-26T17:30     # the agent with REAL orders (trading key needed)
uv run python scripts/keep_running.py --live --end-at 2026-10-26T17:30   # the same, restarted after any stop
uv run wx live                       # the live book
uv run wx kill                       # kill switch
uv run wx verify-log --live          # check the hash chain of the live decision log
uv run wx tradelog --live            # rebuild the judges' trade report
WX_LLM_REPLAY=1 uv run wx agent --shadow --cycles 1   # re-run with saved AI answers where the inputs match
uv run wx agent-replay               # the whole agent graph on past moments, against the rules alone
uv run python scripts/test_risk_rules.py              # F48: each risk rule alone, then together
uv run python scripts/live_health.py                  # health check of a live run
uv run pytest                        # about 150 tests, no internet
uv run --no-project --with pandas --with numpy python scripts/study_12h_signals.py   # F41
```

Saved outputs are in [results/](../results/README.md). The backtest and study need no keys. The agent needs the
AI settings in `.env`. Live orders need a Wallex key that can trade. Never give the key withdrawal rights.

A judge can re-run the agent in shadow mode on live data with no real orders. The shadow book uses the same graph, the
same prompts, the same hard limits and the same code for stops, targets and exits as the live run.

## Honest limits

- **Costs beat the usual short move.** A round trip costs 0.5% to 1%. Over 12 hours, no simple rule earned on average.
  The bot is built to trade rarely and small, and to cut a failing trade fast.
- **Much of the old multi-day profit was the Toman falling.** Without that drift, the trend rule lost.
- **A short contest is close to a coin flip per trade.** Three days is a small sample. A good or bad result is not
  proof of skill. The risk limits are what protect the account.
- **The AI is not always right.** In past replays it skipped the trades that later did best when it judged freely
  (F20, F27) and it did not stop trend losses (F51). That is why it is held to numbers, why its buys are sized by
  code, and why a debate and a judge check each buy.
- **The model's window is small** (32,768 tokens, F59). The prompts are compact and old tool results are cleared.
- **The code improved during the live run.** The report shows the commit for each trade. Early trades were made under
  earlier limits (for example, 40% in one coin at first, then 20%).
- **Live fills differ from the backtest.** The backtest uses fixed spreads (F40). Real fills depend on the book.
- **Leftover coin.** A sell can leave coin below the minimum order. The report shows the result with and without it.
