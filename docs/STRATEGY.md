# How the bot trades

This is the document for judges. It says what the bot does, why, and how to check it.
Details and dates are in [DECISIONS.md](DECISIONS.md) (D = decision, F = checked fact) and [PROGRESS.md](PROGRESS.md).

## In one paragraph

Every 15 minutes the bot reads live Wallex data for six liquid Toman markets. Code computes 28 named features per market. Code checks one buy rule: the 1-hour EMA 20 is above the EMA 50 (an uptrend). For every market where the rule holds, an AI reviews the buy and writes why. The AI can stop a buy, but only with a reason that code can check in the data. A risk check in normal code then sizes the buy, or rejects it. Buys are limit orders at the bid. A position is sold when the trend turns (EMA 20 below EMA 50) or at a stop-loss. Every step is logged.

## Architecture

```
Wallex REST API ──> candles + order book ──> features (code, 28 per market)
                                                │
                                   setups (code): is "trend" active?
                                                │
                                   AI review (LLM, JSON, may call tools)
                                                │
                                   checked veto (code): is the AI's veto true?
                                                │
                                   risk check (code): size, shrink or reject
                                                │
                     shadow book (fake orders)  or  real orders (Phase 4)
                                                │
                                   logs: data/decisions/, data/shadow/
```

| Part | File | What it does |
|---|---|---|
| Wallex client | `wallex.py` | Public data and our account, standard library only. The key goes only in a header. |
| Candles | `candles.py` | Saves 1-minute and 1-hour candles to `data/candles/`. Keeps 120 days. |
| Features | `features.py`, `indicators.py` | 28 named features. Matches the `ta` library (change 9). |
| Setups | `setups.py` | Buy rules with their own exit rules. Only `trend` is traded (D29). |
| AI | `llm.py`, `decide.py`, `agent.py` | Any OpenAI-compatible model. JSON answers, checked by code. Optional tools. |
| Checked veto | `veto.py` | The AI's veto must be one of three, and code checks it (D30). |
| Risk check | `risk.py` | Size, shrink or reject. Daily-loss and drawdown halts (D25). |
| Trade walk | `trades.py` | One function decides fills, stops, exits and costs, for every test and the shadow book (D28). |
| Shadow book | `shadow.py`, `cycle.py` | Fake limit orders on live data. Survives restarts. |
| Tests on the past | `backtest.py`, `study.py`, `replay.py` | Backtest, setup study, AI replay. |

## How the AI is used

- The model is set in `.env` (`LLM_BASE_URL`, `LLM_MODEL`). We use the hackathon gateway (F11).
- Each cycle with something to decide, the AI gets all features with their meanings, our cash and positions, and the list of vetoes. It answers in JSON: for each market BUY, SELL or HOLD, a confidence, a reason, the features it used, and a veto if it stops a buy.
- Code checks every answer (D18). Unknown actions, made-up features, a SELL of a coin we don't hold, or a buy through a setup that is not active: all become HOLD, and the problem is logged. The values of the cited features in the log come from our data, not from the AI's text.
- The AI can call tools (role `agent`, D27): the features of any market, recent hourly prices, and each setup's past record. The tools only see data up to the moment being decided.
- If the AI fails, nothing is bought (fail closed).
- The AI's full answer and its reasoning text are logged with every decision.

### Why the AI may not simply decide

We tested five ways for the AI to choose trades, on past moments the AI could not know (`wx replay`). In every one, its own judgement made the result worse or no better (F20, F21, F27). For example, when free to stop trend buys, it stopped 70% of them, and the ones it stopped did better than the ones it allowed. So the AI's power is limited to vetoes that code can check: `illiquid`, `stale_data`, `market_crash` (D30). This keeps the AI in every decision, and it explains every trade. It cannot make the strategy worse on a hunch.

## Buy and sell rules

- **Buy:** the 1-hour EMA 20 is above the EMA 50, we don't hold the market, the AI gives no checked veto, and the risk check approves a size.
- **Order:** a limit buy at the bid. It waits up to one hour, then is cancelled.
- **Sell:** when the 1-hour EMA 20 falls below the EMA 50 (limit sell), or at the stop-loss (market sell).
- **Stop-loss:** 4 times the 1-hour ATR below the entry (D23).
- **Markets:** BTCTMN, ETHTMN, SOLTMN, XRPTMN, PEPETMN, USDTTMN. All are allowed (D3), liquid, and have narrow spreads (D12).

## Risk and capital management

All in `risk.py`, normal code. The AI can't skip it (ROADMAP rule 7).

- At most 0.75% of equity is lost if a stop is hit. The size follows from the stop distance.
- At most 25% of equity in one coin. At most 60% in coins together. Never all-in.
- No new buys after losing 2% in a UTC day, or while equity is 6% below its peak. The drawdown halt ends after 24 hours.
- No buys on data older than 5 minutes. Orders below the Wallex minimum (50,000 TMN) are refused.
- Each verdict names the rule that decided, and is logged.
- In the backtest, turning the halts off lowered the return and raised the drawdown on both market sets (F29).

## Results so far

All numbers are after fees (Wallex maker 0.25%, taker 0.30%, F3) and spread.

| Test | What | Result |
|---|---|---|
| Backtest, 88 days, our 6 markets | trend, limit orders, with the risk check | +36.8%, worst drawdown 7.9%. Both halves positive. (F25) |
| Backtest, 88 days, 12 other markets | the same rule, never tuned on them | +43.6%, worst drawdown 12.7%. Both halves positive. (F25) |
| 3-day windows, our 6 markets | a fresh book every day, run for 3 days | Up in 49% of windows. Average +0.87%. Worst -4.2%, best +14.8%. (F28) |
| AI replay | 40 past moments per role | The AI's free choices did not beat the rules (F20, F21, F27). |

What this means:
- The trend rule made money over the last months, on markets it was not chosen on. Much of this comes from the Toman losing value: in these 120 days USDTTMN rose 63% (F24). That may not continue.
- Over a single 3-day window the result is close to a coin flip. The edge shows in the average, through a few large winners.
- In the 88-day backtest on our 6 markets, the profit came from 5 of them: ETH 37%, SOL 24%, USDT 19%, BTC 13%, PEPE 6%, XRP about 0. 74 of 93 trades ended by the trend rule, 15 at the stop. The 60% limit on coins was the rule that most often refused a buy.
- Rules we tried that did not hold up are listed in F26, so nobody repeats them.

## How to re-run

```bash
uv run wx candles            # download 120 days of candles (about 15 minutes the first time)
uv run wx study              # each setup over the history, no AI
uv run wx backtest           # the portfolio backtest, no AI
uv run wx replay --role veto # the AI on 40 past moments (needs the AI settings)
uv run wx run --shadow --role veto   # live shadow trading, every 15 minutes
uv run wx shadow             # the shadow book
uv run pytest                # 100+ tests, no internet
```

The backtest and study need no keys. The replay and the live run need the AI settings in `.env`.
