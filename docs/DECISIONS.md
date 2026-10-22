# Decisions and Checked Facts

This file lists decisions we already made, and facts we checked.

- Add an entry only when a decision is made or a fact is checked.
- Don't edit old entries. To change a decision, add a new one that replaces it.
- Progress entries link to these IDs instead of repeating them.

## Decisions

| ID | Decision | Date | Who |
|---|---|---|---|
| D1 | The bot knows nothing about the end of the hackathon. Ending the account in Toman is handled by the team, outside the bot. | 2026-10-21 | team |
| D2 | Spot trading only. No leverage, no margin, no credit, no OTC. | 2026-10-21 | organizers |
| D3 | We may trade every live Wallex spot market except the ones in [wallex_inactive_markets.txt](../src/wx/inactive_markets.txt). If in doubt, don't trade it. | 2026-10-21 | organizers |
| D4 | The AI provider will be chosen later. The code must work with any OpenAI-compatible API (just change the URL). | 2026-10-21 | team |
| D5 | Keys live only in a `.env` file that git ignores. `.env.example` shows the names with fake values. The team fills `.env` directly. Keys never appear in chat, logs, or AI prompts. | 2026-10-22 | team |
| D6 | Medium risk. Use the defaults from research file 03: risk 0.75% per trade, max 25% in one coin, max 60% in coins in total, stop-loss based on ATR, daily-loss and drawdown limits. Ignore the different numbers in other research files. | 2026-10-22 | team |
| D7 | Build a small first version. These wait until the bot trades live: a second reviewing AI, a machine-learning signal, a tamper-proof log, saved AI answers, Docker, CI. | 2026-10-22 | team |
| D8 | Live trading comes before the backtest and the docs. | 2026-10-22 | team |
| D9 | Python 3.12 or newer, run with `uv`. The command is `wx`. Libraries are added only when a phase needs them. | 2026-10-22 | Claude |
| D10 | Setting names: `WALLEX_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`. `.env.example` must list the same names. A test checks this. | 2026-10-22 | Claude |
| D11 | The forbidden-market list lives in the code: [inactive_markets.txt](../src/wx/inactive_markets.txt). Saved Wallex data goes in `data/`, which git ignores. HTTP uses the Python standard library until we need more. | 2026-10-22 | Claude |
| D12 | Default markets for data: BTCTMN, ETHTMN, SOLTMN, XRPTMN, PEPETMN, USDTTMN (liquid and allowed, from research file 05). Candles are saved as CSV in `data/candles/<SYMBOL>_<1m or 1h>.csv`. Columns `t,o,h,l,c,v`. `t` is Unix seconds (UTC). Values stay as Wallex sends them. Gaps are kept, not filled. | 2026-10-22 | Claude |
| D13 | Live prices come from `/v1/depth` (best bid and ask), not from `/v1/markets` stats, which can be stale. The price log is `data/prices/<UTC date>.jsonl`, one line per cycle, with `time`, `cycle`, `prices` and `errors`. A loop never stops because of an error. It logs the error and waits for the next beat. | 2026-10-22 | Claude |
| D14 | The account behind `WALLEX_API_KEY` is the competition account. It started with 5,000,000 TMN (F2). | 2026-10-22 | team |
| D15 | Keep 120 days of candles (`wx candles` default). Wallex has at least that much (change 7). | 2026-10-22 | team |
| D16 | AI calls use temperature 0 and JSON mode. We keep the model's own reasoning text, so each decision can log it. An AI error message never contains the key. | 2026-10-22 | Claude |
| D17 | The AI gets a fixed set of named features per market, listed in `FEATURES` in [features.py](../src/wx/features.py). Indicators use closed 1-hour candles only (the last 1,000). Returns compare the live mid price with 1-minute candles that have ended. Regime: ADX above 25 is a trend (up or down by the EMA 20 slope), below 20 is a range, else transition. The maths is our own code, with no new library. | 2026-10-22 | Claude |
| D18 | One AI call per cycle covers all markets. Per market it answers BUY, SELL or HOLD, a confidence from 0 to 1, a reason, the feature names it used, and what would prove it wrong. Code turns a market into HOLD if the action is unknown, the confidence is bad, no known feature is cited, or it says SELL on a coin we don't hold (or hold less than the minimum order of). If the AI fails or its JSON can't be read, every market is HOLD and the record says `fallback`. Decisions are logged in `data/decisions/<UTC date>.jsonl`, with the code version, all features, cash, holdings, the AI's raw answer and its reasoning. | 2026-10-22 | Claude |
| D19 | `wx run` decides every 15 minutes (900 s), on the beat. The AI takes about 60 s (F15), so this leaves plenty of room. Returns change every minute, so 15 minutes sees moves the hourly indicators miss. Research file 02 suggests the same. `--interval` changes it. A cycle that fails for any reason is still logged, with driver `none` and the error. | 2026-10-22 | Claude |
| D20 | The AI judges each market over about a day (12 to 48 hours), not hours. A new feature, `typical_24h_move_pct`, gives the usual one-day move over the last 30 days, so the AI compares the cost with a move of the right size. This needs 750 hours of history per market. | 2026-10-22 | Claude |
| D21 | `wx replay` tests the AI on past moments. Features are rebuilt from candles that ended by that moment. The past book is not saved, so the spread is today's spread. The AI sees no dates, no cash change and no holdings. The result is the price change over the next 24 hours, minus the round-trip cost. Moments are picked at random on the 15-minute beat, with a fixed seed so a run can be repeated. | 2026-10-22 | Claude |
| D22 | The AI may only BUY through a buy setup defined in code ([setups.py](../src/wx/setups.py)): `sharp_drop`, `oversold`, `breakout`, `trend_momentum`. Textbook thresholds, not tuned. The two setups that lost in F17 are left out. The AI must name the setup. Code turns a BUY into HOLD if that setup is not active in that market. With no active setup and nothing held, the AI is not asked: every market is HOLD, logged with driver `rules`. | 2026-10-22 | Claude |
| D23 | Tests (`wx replay`, `wx study`) put a stop-loss 4 times the 1h ATR below each entry. We tried 2, 3 and 4. Every stop lowered the average result (F19), and 4 lowered it least. We keep one anyway, because a crash like 2026-10-07 can go on for days. The Phase 3 risk check sets the real stop. | 2026-10-22 | Claude |
| D24 | The AI's role is `veto`. Code buys through the mean-reversion setups (sharp_drop, oversold). The AI reviews every such buy, explains it, and may stop it for a specific, serious danger. Roles `pick` and `informed` made results worse in the replay (F20, F21). `veto` did not (F21). | 2026-10-22 | Claude |
| D25 | The risk check is [risk.py](../src/wx/risk.py), normal code. Per BUY it sizes, shrinks or rejects, and names the rule that decided. Limits from D6: 0.75% of equity at risk per trade, 25% of equity per coin, 60% in coins, stop 4 ATR (D23), no buys after a 2% loss in a UTC day or 6% below the peak, no buys on data older than 5 minutes, Wallex minimum order. A drawdown halt ends after 24 hours: the peak resets, so one bad week does not stop trading for good. | 2026-10-22 | Claude |
| D26 | `wx backtest` trades 5,000,000 TMN hour by hour over the saved history, with the risk check. Two order models. Taker: buy at the mid price, pay round_trip_cost_pct. Limit: a buy at the bid fills only if the price trades below the bid within an hour (maker fee 0.25%). A sell after 24 hours pays the maker fee. A stop pays the taker fee (0.30%) and half the spread. Today's spread stands in for the past spread. | 2026-10-22 | Claude |
| D27 | The AI can call tools (`agent.py`): the features of any market, the last hourly closes of any market, and each setup's record from before now. Every call and its result go in the decision log. In a replay, the tools only see data up to the moment, so they can't leak the future. The `agent` role is `veto` plus these tools. The tool loop is our own small loop over the OpenAI-compatible API, so no framework is added. | 2026-10-22 | Claude |
| D28 | Shadow trading (`--shadow`) keeps a fake book in `data/shadow/book.json`. A fake order stores what was known when it was placed. Every cycle, the backtest's own `trade()` replays it over the saved 1-minute candles: waiting, open, stopped, or done after 24 hours. So shadow and backtest use one set of rules. An AI SELL closes a position at the bid with the taker fee. | 2026-10-22 | Claude |

## Checked facts

Facts checked with live Wallex data, our own key, or a real order. Research notes from 2026-10-21 don't count until we check them again.

| ID | Fact | Value | Checked on | How |
|---|---|---|---|---|
| F1 | Our Wallex key in `.env` can read balances and fees. A wrong key gives HTTP 401, code 1201. | works. Whether it can trade is unknown. | 2026-10-22 | `wx account` |
| F2 | Account balance | 5,000,000 TMN, nothing locked, no coins. | 2026-10-22 | `wx account` |
| F3 | Fees on all 187 TMN markets | maker 0.25%, taker 0.30% | 2026-10-22 | `wx account` (`/v1/account/fee`) |
| F4 | Fees on all 186 USDT markets | maker 0.10%, taker 0.13% | 2026-10-22 | `wx account` |
| F5 | A buy and a sell on a TMN market, both as taker | costs 0.60% of the trade, plus the spread | 2026-10-22 | from F3 |
| F6 | Fees depend on recent trade volume. The fee reply has a `metaData` entry with volume levels in Toman: 0, 100M, 1B, 3B, 10B, 20B. Our recent volume is 0. | Rates for the higher levels are unknown. | 2026-10-22 | `/v1/account/fee` |
| F7 | `stepSize` and `tickSize` in `/v1/markets` are numbers of decimals, for quantity and price. They are not step sizes. | All 373 markets: `minQty` = 10^-`stepSize`, and the website's own precision fields are equal. Live books and trades on our 6 markets use exactly these decimals. One odd case: USDTTMN book quantities have up to 8 decimals, but `stepSize` is 2. We use 2. | 2026-10-22 | `/v1/markets`, `/hector/web/v1/markets`, `/v1/depth`, `/v1/trades` |
| F8 | Minimum order value | 50,000 TMN on all 187 TMN markets. 1 USDT on all 186 USDT markets. | 2026-10-22 | `/v1/markets` |
| F9 | `isMarketTypeEnable` is true on only 7 markets: BTCTMN, ETHTMN, USDTTMN, XAUTTMN, BTCUSDT, ETHUSDT, XAUTUSDT. It is false on SOLTMN, XRPTMN and PEPETMN. | It probably means MARKET orders are allowed. Not confirmed. | 2026-10-22 | `/v1/markets` |
| F10 | Rules for our default markets | See the table below. | 2026-10-22 | `wx rules` |
| F11 | Our AI is an OpenAI-compatible gateway (LiteLLM, then vLLM) at `ai-gateway.mohaymen.ir`. The model `mohaymen/qwen3.8-27b` reports itself as `qwen3.8-27b`. | A small call takes 3 to 4 s and about 430 tokens. | 2026-10-22 | `wx ai` |
| F12 | The AI supports JSON mode (`response_format`). It sends its thinking in a separate `reasoning_content` field, not in the answer. | works | 2026-10-22 | `wx ai` |
| F13 | A wrong AI key gives HTTP 401. The error message repeats the key we sent. | Our code replaces it with `***`. | 2026-10-22 | `wx ai` with a wrong key |
| F14 | Round-trip cost on our 6 markets, with taker fees and the live spread | 0.61% (USDTTMN) to 1.17% (ETHTMN). Fees are 0.60% of that. The spread was 0.01% to 0.57%. | 2026-10-22 | `wx features` |
| F15 | One decision call for 6 markets | About 60 s and 7,700 tokens: 3,200 in, 4,500 out, of which 2,800 are reasoning. | 2026-10-22 | `wx decide` |
| F16 | USDTTMN has had no trades for most nights since 2026-09-30, roughly 18:00 to 05:00 UTC. Before that, it had none of these empty hours. The other 5 default markets had at most 2 empty hours in the last 14 days. | In the last 14 days, 120 of 336 USDTTMN hours had zero volume. | 2026-10-22 | 1-hour candles in `data/candles/` |
| F17 | Textbook setups on 5 coin markets, about 87 days of hours. Buy, hold 24 hours, round-trip cost taken off, at most one entry per market per day. No AI. | Every hour: -0.05% average. Sharp drop (24h fall of at least 2 typical days): +0.42%, 82 entries, 52% win, positive in both halves. RSI below 30: +0.21%, 47 entries. Breakout and trend momentum: positive in the first half, negative in the second. Trend pullback: -0.21%. Range dip: -1.33%. All edges are small. Sharp drop is about 1.5 standard errors above 0. | 2026-10-22 | setup study on saved candles |
| F18 | AI replay with the one-day prompt: 40 past moments, 240 market decisions | 16 BUY (7%). Next 24h net: BUY -0.55%, HOLD -0.62%. On coin markets, HOLD -0.75%. The AI bought breakouts and uptrends, and none of the 28 sharp-drop moments. Its choices show no edge yet. It mistyped PEPETMN twice. The check made both HOLD. | 2026-10-22 | `wx replay --moments 40` |
| F19 | `wx study`: the 4 setups on 6 markets, about 88 days of hours. Buy, sell after 24 hours or at the stop, round-trip cost taken off, at most one entry per market per setup per day. +/- is one standard error. | No stop: sharp_drop +0.51% +/- 0.35 (103 entries), oversold +0.26% +/- 0.31, breakout +0.31% +/- 0.42, trend_momentum +0.25% +/- 0.28, any setup +0.14% +/- 0.23. With a 4 ATR stop: +0.34%, +0.08%, +0.30%, +0.15%, +0.06%. In the second half, breakout and trend_momentum lost (-0.47%, -0.16%). Every hour: +0.02%. No setup is clearly above 0. | 2026-10-22 | `wx study` |
| F20 | AI replay with setups: 40 past moments with an active setup, 240 market decisions, 4 ATR stop, net of costs | AI buys: 21, average -0.87%, 38% won. Every active setup without the AI: 96, +0.15%. Setups the AI skipped: 75, +0.44%. The AI took 12 trend_momentum (-0.96% on average) and skipped 45 of 47 sharp_drop (+0.79% on average). The AI made the result worse, by about 2 standard errors. No failures, no problems found. | 2026-10-22 | `wx replay --moments 40` |
| F21 | AI roles in the replay, 40 setup moments each, 4 ATR stop, net of costs | informed: AI buys 40 at -0.64%, skipped 56 at +0.69%, every setup +0.13%. It still chose trend setups (29 of 40). veto (mean-reversion moments): let 91 of 109 through at +0.77%. The rest were stopped by the AI or by failed calls, at +0.78%. Same as taking all. 8 of 80 calls timed out with 6 calls running at once. | 2026-10-22 | `wx replay --role informed`, `--role veto` |
| F22 | `wx backtest` on 6 markets, about 88 days | Taker orders: only sharp_drop made money (+0.30%). Limit orders: sharp_drop +3.05% (drawdown 3.9%), oversold +2.66%, mean reversion +1.85%, trend +5.72% but 9% drawdown. Only oversold was positive in both halves (+1.58%, +1.07%), on 50 trades. Selling dip-buys early, back at the 48h mean or at RSI 50, did worse than holding 24 hours. | 2026-10-22 | `wx backtest`, scratch test |
| F23 | The AI gateway supports tool calls (OpenAI `tools`). One round with a tool call took 1 s, the answer after it 3 s. | works | 2026-10-22 | scratch test |

#### Market rules for the default markets (F10)

| Market | Quantity decimals | Price decimals | Min quantity | Min order | MARKET flag |
|---|---|---|---|---|---|
| BTCTMN | 8 | 0 | 0.00000001 | 50,000 TMN | on |
| ETHTMN | 5 | 0 | 0.00001 | 50,000 TMN | on |
| SOLTMN | 5 | 0 | 0.00001 | 50,000 TMN | off |
| XRPTMN | 1 | 0 | 0.1 | 50,000 TMN | off |
| PEPETMN | 0 | 4 | 1 | 50,000 TMN | off |
| USDTTMN | 2 | 0 | 0.01 | 50,000 TMN | on |

Rules can change. Code reads them from Wallex at start. It does not use this table.

### Still unknown

Check each of these when a change needs it:
- Is the fee on a BUY taken in the coin or in Toman?
- F7 says decimals. Confirm it with the first real order.
- What does `isMarketTypeEnable` = false mean (F9)? Can we send MARKET orders on SOLTMN, XRPTMN and PEPETMN?
- How to send a MARKET order. Is a price required? Can we say "spend X Toman"?
- Order status values and error codes (no money, too small, bad precision, duplicate ID, too many requests).
- The longest allowed `client_id`, and which characters it may use.
- Request limits when using our key, for the API and for the MCP server.
- Does a trading key need a fixed IP address?

Sources: [research/05](research/05-wallex-api-integration.md) and [research/00-index](research/00-index.md).
