# How the bot trades

This is the document for judges. It says what the bot does, why, and how to check it.
Details and dates are in [DECISIONS.md](DECISIONS.md) (D = decision, F = checked fact) and [PROGRESS.md](PROGRESS.md).

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

## Architecture

```
                         every 15 minutes: one LangGraph cycle (brain.py)
 ┌────────┐   ┌───────────────────────────────┐   ┌─ bull (AI) ─┐   ┌────────────┐   ┌──────┐   ┌─────┐   ┌─────────┐   ┌─────────┐
 │ sense  │──>│ trader (AI agent)             │──>│             │──>│ judge (AI) │──>│ gate │──>│ act │──>│ reflect │──>│ journal │
 │ (code) │   │ tools · skills · memory       │   └─ bear (AI) ─┘   │ approve /  │   │(code)│   │(code)│  │  (AI)   │   │ (code)  │
 └────────┘   │ decides buys, plans, sells    │   argue its buys    │ reduce /   │   │ hard │   └─────┘   └─────────┘   └─────────┘
              └───────────────────────────────┘                     │ reject     │   │limits│
                                                                    └────────────┘   └──────┘
 Wallex REST: candles, best bid/ask, orders      Wallex MCP: order book, latest trades, candles (read only, no key)
 SQLite checkpointer: short-term memory           SQLite store: closed trades, lessons, each position's thesis

                         every minute: the guard thread (runner.py)
 stop and target on the live price · time limits · resend unfilled sells · cancel old buys · sell everything before the end
```

| Part | File | What it does |
|---|---|---|
| Wallex client | `wallex.py` | Public data and our account, standard library only. The key goes only in a header. |
| Wallex orders | `orders.py` | Place, read and cancel orders by our own `client_id`. Only code calls it. |
| Wallex MCP | `wallex_mcp.py` | The official MCP server, for the agent's book, trade and candle reads. Allowlist of 3 read tools. |
| Markets | `universe.py`, `markets.py` | Allowed markets (the exclusion list), the liquid ones, picked again each cycle. |
| Features | `features.py`, `indicators.py` | 33 named features: 1h, 4h and 15-minute views, plus whole-market context. |
| Setups | `setups.py` | Named patterns the trader can cite as evidence (dips, trends). Not gates. |
| Agent graph | `brain.py` | The cycle above: nodes, tools, prompts, the plan format, memory, evidence. |
| Skills | `skills/*.md` | Trader playbooks the AI reads when it needs them. |
| Hard limits | `risk.py` (`Envelope`, `size_plan`) | The only rules the AI can't change, and the sizing ladder. |
| Execution | `execution.py`, `live.py` | The shadow book, or real orders with a guard and a kill switch. Same methods. |
| Runner | `runner.py` | The beat, the guard thread, halts, the kill file, the AI answer cache. |
| Tests on the past | `backtest.py`, `study.py`, `agent_replay.py`, `scripts/` | Backtests, studies, the agent replayed on past moments. |

## How the AI is used

The AI runs in five places every cycle: the trader, the bull, the bear, the judge, and (after closed trades) the
reviewer. It decides; code checks only the hard limits.

**The trader** is an agent (LangChain `create_agent`, a LangGraph subgraph) with these tools:

| Tool | What it gives |
|---|---|
| `get_portfolio` | Equity, cash, positions with their exit plans, today's result, drawdown, buys in 24 hours, the hard limits. |
| `list_markets` | Every allowed Toman market with Wallex's 24-hour volume and change. |
| `get_market` | All 33 features of any allowed market (computed on demand for markets outside the overview). |
| `get_regime` | Volatility, trend, direction, volume, Hurst exponent, and the playbook for that regime. |
| `get_evidence` | What our tests found: each setup over 12 hours, rule sets by horizon, exits, time of day, how big 12 hours can be, the AI's own record, costs. |
| `get_orderbook` | The live book and the last 50 trades from the **Wallex MCP server**: spread, depth, imbalance, buyer share, the cost of our order size. |
| `get_candles` | 5, 15 or 60-minute candles from the **Wallex MCP server**. |
| `get_hourly_closes` | The shape of the last hours. |
| `check_order` | What code would do with a buy at a given risk and stop: the size and the limit that set it. |
| `recall_lessons` | Lessons from our past trades, losses first. |
| `read_skill` | Trader playbooks: core, regimes, exits, risk and sizing, dips, trends, order book, the Toman, the deadline, reviews. |

The core playbook, the playbook for the current pace, the evidence, the hard limits and the setups are already in the trader's instructions, and its result so far is in its facts. So it does not spend a tool call on them. Those instructions are the same every cycle, so the AI provider can cache them (D47).

It also sees, without asking: its last 8 cycles, its lessons (losses first), its own thesis for each position, the
hard limits, and an overview of every liquid market. Middleware caps it at 12 tool calls and retries a failed tool.

It answers with a plan: for each buy, the market, a strategy label, `risk_pct`, `stop_pct`, `target_pct`,
`max_hours`, `exit_on_trend_turn`, maker or taker, conviction, reason, cited features, and what would prove it
wrong; and the positions to sell, with a reason. Nothing is bought unless it asks.

**Bull and bear** argue each proposed buy in parallel, with the data and the evidence. **The judge** weighs
them and approves, reduces the risk, or rejects each buy. **The reviewer** writes a lesson after each closed trade.

**Wallex tools.** Prices, candles and orders use the Wallex REST API through our own small clients. The trader
reads the book, trades and candles through the official Wallex MCP server, with no key and only read tools, so
the AI can never place an order. Nothing outside the requirements is used: Wallex, the AI model, LangChain and
LangGraph, and our own analysis (D44).

**Safety around the AI.** If the AI fails or its plan has the wrong shape after one retry, nothing is bought;
positions keep their stops and exit plans. After 3 failed cycles in a row, or over the daily token budget, the
debate and the judge are skipped. Every AI call and answer is saved, so a past cycle can be re-run exactly
(`WX_LLM_REPLAY=1`). The model is set in `.env` (`LLM_BASE_URL`, `LLM_MODEL`); we use the hackathon gateway.

## The pace follows the trading time

The time left until trading ends sets the pace (D45, `horizon.py`):

| Time left | Profile | Decisions | Data read first | Holds | Limit buys wait |
|---|---|---|---|---|---|
| under a day | sprint | every 5 minutes | 1, 5, 15-minute candles, the live book | minutes to 6 hours | 10 minutes |
| up to a week | short | every 15 minutes | 15-minute and 1-hour candles | hours to 2 days | 30 minutes |
| longer, or no end | swing | every 30 minutes | 1-hour and 4-hour candles | a day to a week | 60 minutes |

The profile moves to sprint by itself as the end comes closer. In sprint the trader reads ten fast features (5 and
30-minute returns, the 5-minute EMA 9/21, RSI and z-score, 5-minute ATR and volume, the 4-hour VWAP, the last
hour's range and position) and the sprint playbook. Our tests on 1-minute data showed that standard fast
strategies lose 0.3% to 0.95% a trade on Wallex after costs (F62), so the playbook uses fast data to time good
trades and exit failing ones quickly, not to trade more.

## How trades are decided

The trader decides each trade (D43). The skills give it the playbooks:
- **Which markets:** any allowed Toman market. The overview has every liquid one; `list_markets` and `get_market`
  reach the rest.
- **When to buy:** from the regime (`market-regime`), the evidence (`get_evidence`), the book and the shape.
  Named setups (deep dips, strong trends) are evidence it can cite, with their measured records.
- **How much:** `risk_pct` from the tiers of the position-sizing skill (0.5-1% weak, 1-2% good, up to 3% best).
- **Exit plan:** a stop from about 2 to 4 times the hourly ATR; an optional target; a time limit; an optional exit
  when the trend turns; maker or taker (`exit-planning`). Our tests showed fixed targets and trailing stops did
  worse, and the skill says so.
- **Selling:** any position, any cycle, with a reason.

Code sizes each buy: risk_pct of equity divided by (stop + round-trip cost), then the smallest of the room in one
coin, the room in coins, free cash and half the money resting within 1% on the ask side. A guard sells at the
stop or target on the live price every minute, and at the time limit.

## Risk and capital management: the hard limits

All in `risk.py` (`Envelope`) and `live.py`, normal code. The AI can't change them. Values follow the installed
risk-management and position-sizing skills.

- Every buy has a stop between 1% and 15% under the entry. At most 3% of equity lost if it is hit, costs included.
- At most 40% of equity in one coin and 80% in coins together. Never all-in.
- No new buys after losing 4% in a UTC day, or while equity is 10% below its peak (for 24 hours).
- At most 60 buys in 24 hours. No buys on data older than 5 minutes. No order larger than half the money resting
  within 1% of the price on the ask side. Wallex's minimum order and decimals.
- Allowed markets only: the organizers' exclusion list is applied every cycle, and again at order time.
- No new buys in the last 45 minutes. 30 minutes before the end, everything is sold into Toman, and the guard
  keeps trying every minute.
- Kill switch: `wx kill`, or a file `data/KILL` inside the running bot. After 3 failed cycles or guard rounds in a
  row: no new buys until a clean cycle.
- Each verdict names the limit that set the size, and is logged.

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

## How to re-run

```bash
uv run wx candles                    # 120 days of candles (about 15 minutes the first time)
uv run wx backtest --hours 12        # 12-hour windows: agent setups, dip setups, the old trend rule
uv run wx backtest                   # the multi-day backtest
uv run wx study                      # each setup over the history
uv run wx agent --shadow --end-at 2026-10-23T00:30   # the agent on every liquid allowed market, fake orders
uv run wx agent --live --end-at 2026-10-23T00:30     # the agent with REAL orders (trading key needed)
uv run wx live                       # the live book
uv run wx kill                       # kill switch
uv run wx verify-log                 # check the hash chain of today's decision log
WX_LLM_REPLAY=1 uv run wx agent --shadow --cycles 1   # re-run with saved AI answers where the inputs match
uv run python scripts/test_risk_rules.py              # F48: each risk rule alone, then together
uv run pytest                        # 140+ tests, no internet
uv run --no-project --with pandas --with numpy python scripts/study_12h_signals.py   # F41
```

Saved outputs are in [results/](../results/README.md). The backtest and study need no keys. The agent needs the
AI settings in `.env`. Live orders need a Wallex key that can trade.
