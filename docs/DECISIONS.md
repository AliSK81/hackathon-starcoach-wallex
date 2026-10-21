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
