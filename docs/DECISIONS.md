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
| D3 | We may trade every live Wallex spot market except the ones in [wallex_inactive_markets.txt](research/wallex_inactive_markets.txt). If in doubt, don't trade it. | 2026-10-21 | organizers |
| D4 | The AI provider will be chosen later. The code must work with any OpenAI-compatible API (just change the URL). | 2026-10-21 | team |
| D5 | Keys live only in a `.env` file that git ignores. `.env.example` shows the names with fake values. The team fills `.env` directly. Keys never appear in chat, logs, or AI prompts. | 2026-10-22 | team |
| D6 | Medium risk. Use the defaults from research file 03: risk 0.75% per trade, max 25% in one coin, max 60% in coins in total, stop-loss based on ATR, daily-loss and drawdown limits. Ignore the different numbers in other research files. | 2026-10-22 | team |
| D7 | Build a small first version. These wait until the bot trades live: a second reviewing AI, a machine-learning signal, a tamper-proof log, saved AI answers, Docker, CI. | 2026-10-22 | team |
| D8 | Live trading comes before the backtest and the docs. | 2026-10-22 | team |

## Checked facts

Facts checked with our own key or a real order. Research notes from 2026-10-21 don't count until we check them again.

| ID | Fact | Value | Checked on | How |
|---|---|---|---|---|
| — | _none yet_ | | | |

### Still unknown

Check each of these when a change needs it:
- Our fee rates. Is the fee on a BUY taken in the coin or in Toman?
- Are `stepSize` and `tickSize` numbers of decimals, or step sizes?
- How to send a MARKET order. Is a price required? Can we say "spend X Toman"?
- Order status values and error codes (no money, too small, bad precision, duplicate ID, too many requests).
- The longest allowed `client_id`, and which characters it may use.
- Request limits when using our key, for the API and for the MCP server.
- Does a trading key need a fixed IP address?
- Is the competition account a sub-account with its own key?

Sources: [research/05](research/05-wallex-api-integration.md) and [research/00-index](research/00-index.md).
