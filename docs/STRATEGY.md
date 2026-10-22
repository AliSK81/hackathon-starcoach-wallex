# How the bot trades

This is the document for judges. It says what the bot does, why, and how to check it.
Details and dates are in [DECISIONS.md](DECISIONS.md) (D = decision, F = checked fact) and [PROGRESS.md](PROGRESS.md).

## In one paragraph

Every 15 minutes, a LangGraph agent runs one decision cycle on every allowed Toman market that is liquid enough
(21 of 62 on 2026-10-22, picked again each cycle). Code computes 33 named
features per market, adds whole-market context (the Toman's trend, BTC's day), and finds candidates: markets where
one of four 12-hour setups is active. An AI analyst studies each candidate with tools. It reads trader skills,
recalls lessons from past trades, and reads the live order book and trades through the Wallex MCP server. It
answers in JSON. Before it, a bull and a bear analyst argue each candidate in parallel. After it, a risk officer
judges the debate and can only make a buy smaller. Code then checks
every claim against the data, sizes every order with the risk check, and places limit orders on Wallex. A guard
checks stop-losses every minute. After a trade closes, the AI writes a lesson that later cycles can recall. The bot
knows when trading ends: it stops buying 3 hours before and sells everything into Toman 30 minutes before. Every
step is logged.

## Architecture

```
                         every 15 minutes: one LangGraph cycle (brain.py)
               ┌─ bull (AI) ─┐
 ┌──────────┐  │             │  ┌──────────────────────────┐   ┌──────────────┐   ┌──────┐   ┌─────┐   ┌─────────┐   ┌─────────┐
 │  sense   │──┤             ├─>│ analyst  (AI agent)      │──>│ risk officer │──>│ gate │──>│ act │──>│ reflect │──>│ journal │
 │  (code)  │  │             │  │ tools · skills · memory  │   │ (AI judge,   │   │(code)│   │(code)│  │  (AI)   │   │ (code)  │
 └──────────┘  └─ bear (AI) ─┘  └──────────────────────────┘   │  can shrink) │   └──────┘   └─────┘   └─────────┘   └─────────┘
                                                                └──────────────┘
   │ nothing to decide ─────────────────────────────────────────────────────────>│
   │
 Wallex REST: candles, best bid/ask        Wallex MCP: order book, latest trades (read only, no key)
 SQLite checkpointer: short-term memory    SQLite store: closed trades and lessons (long-term memory)

                         every minute: the guard thread (runner.py)
 stop-loss on the live bid · resend unfilled sells · cancel old buys · sell everything before the end
```

| Part | File | What it does |
|---|---|---|
| Wallex client | `wallex.py` | Public data and our account, standard library only. The key goes only in a header. |
| Wallex orders | `orders.py` | Place, read and cancel orders by our own `client_id`. Only code calls it. |
| Wallex MCP | `wallex_mcp.py` | The official MCP server, for the agent's order book and trade reads. Allowlist of 3 read tools. |
| Candles | `candles.py` | Saves 1-minute and 1-hour candles to `data/candles/`. Keeps 120 days. |
| Features | `features.py`, `indicators.py` | 33 named features: 1h, 4h and 15-minute views, plus whole-market context. |
| Setups | `setups.py` | Buy rules with their own exits and an evidence grade. |
| Agent graph | `brain.py` | The LangGraph cycle above: nodes, tools, prompts, checks, memory. |
| Skills | `skills/*.md` | Trader playbooks the AI reads when it needs them. |
| Checked veto | `veto.py` | The vetoes the AI may use, and the code that checks each one. |
| Risk check | `risk.py` | Size, shrink or reject. Daily-loss, drawdown and end-of-trading rules. |
| Execution | `execution.py`, `live.py` | The shadow book, or real orders with a guard and a kill switch. Same methods. |
| Runner | `runner.py` | The beat, the guard thread, the console report. |
| Tests on the past | `backtest.py`, `study.py`, `replay.py`, `scripts/` | Backtests, setup studies, AI replay. |

## How the AI is used

The AI runs in five places in every cycle. Code checks everything it says.

**0. Bull and bear** argue each candidate in parallel, citing feature names only. Their cases go to the analyst and
to the risk officer.

**1. The analyst** is an agent (LangChain `create_agent`, a LangGraph subgraph). It has these tools:

| Tool | What it gives |
|---|---|
| `read_skill` | A trader playbook from `skills/`: core checklist, deep dips, trend following, order book reading, the Toman regime, risk, trading to a deadline, post-trade review. |
| `get_orderbook` | The live book and the last 50 trades from the **Wallex MCP server**: spread, money within 1% per side, imbalance, buyer share, trades per minute, and the cost of filling 500,000 and 1,250,000 TMN. |
| `get_market` | All 33 features of any market. |
| `get_candles` | 5, 15 or 60-minute candles of any market, from the **Wallex MCP server**. |
| `get_portfolio` | Equity, cash, positions, drawdown, buys in the last 24 hours, losses in a row, the limits in force. |
| `check_order` | What the risk check would do with a candidate now, without ordering. |
| `get_hourly_closes` | The shape of the last hours of any market. |
| `get_setup_record` | The setup's 12-hour record in 120 days of history (F41), and our own closed trades with it. |
| `recall_lessons` | Lessons the AI wrote after past trades, by market or setup (long-term memory). |

It also sees, without asking: its own summaries of the last 8 cycles (short-term memory), its lessons from past
trades with the losses first, its own thesis and invalidation for each position it holds, and the bull and bear
cases. Middleware caps it at 10 tool calls, then
it must answer. A failed tool is tried once more. In the first live cycles it used 8 to 10 tools a cycle (F47).

It answers in JSON: for each candidate TAKE or SKIP, a veto for a SKIP, a conviction, a reason, the features it
cited, and what would prove it wrong. For each position: KEEP, or EXIT with a reason.

**2. The risk officer** judges the debate and challenges each TAKE like a sceptical senior trader. It can answer
AGREE or REDUCE (halve the risk). It can't stop a buy and it can't enlarge one.

**3. Reflect.** When a trade closes, the AI reviews it and writes one concrete lesson. Lessons are stored in SQLite
and come back through `recall_lessons` in later cycles. This is how the agent learns from its mistakes.

**What code checks** ([brain.py](../src/wx/brain.py) `check_plan`):
- A SKIP stops a buy only with a veto the data supports: `illiquid`, `stale_data`, `market_crash`, or
  `sell_pressure` (buyer share under 0.35 and book imbalance under -0.3). Otherwise it is overruled, and the log
  says so. We tested why: when the AI was free to stop buys, it stopped 70%, and those did better than the ones it
  let through (F27).
- An EXIT is done only with a reason the data supports: `take_profit` (at least 1% after costs), `setup_exit`,
  `sell_pressure`, `market_crash`.
- Conviction can only shrink an order. The AI never sets a size, a price or a stop.
- If the AI fails, or its plan has the wrong shape after one retry, nothing is bought (fail closed).
- Safe mode: after 3 failed analyst cycles in a row, or over 3 million tokens in a day, the debate and the officer
  are skipped until the analyst answers again.

**Wallex tools.** Market data and orders use the Wallex REST API through our own small clients. The agent reads the
book and trades through the official Wallex MCP server. We send it no key, and only three read tools are allowed,
so the AI can't place an order (D37). Orders go through code, after the risk check.

The model is set in `.env` (`LLM_BASE_URL`, `LLM_MODEL`). We use the hackathon gateway (F11). Every prompt, tool call,
tool result (shortened), answer and check is in the log.

## Buy and sell rules

A candidate is a market we don't hold where one of these setups is active ([setups.py](../src/wx/setups.py)):

| Setup | Buy when | Sell when | Grade |
|---|---|---|---|
| `capitulation` | 1h RSI under 25 and the close more than 2 standard deviations under its 20-hour average | after 12 hours | A |
| `stretched_dip` | the close more than 2.5 standard deviations under its 20-hour average | after 12 hours | A |
| `dip_toman_weak` | 2 standard deviations under, RSI under 30, and the Toman weakening (USDTTMN trend up) | after 12 hours | A |
| `trend_strong` | EMA 20 above EMA 50, ADX above 25, +DI above -DI, the Toman not strengthening, BTC up over 24h | EMA 20 under EMA 50 | B |

- Grade A beat the costs over 12 hours in both halves of 120 days, on our markets and on 12 others (F41).
  Grade B was mixed, so it risks half as much.
- **Order:** a limit buy at the best bid. It waits up to one hour, then is cancelled. A part that filled is kept.
- **Stop-loss:** 4 times the 1-hour ATR under the entry, checked on the live bid every minute.
- **Other exits:** the setup's own exit, a checked early exit from the AI, or the end of trading.
- **Sells** are limit orders 0.5% under the best bid, so they fill at once but never far below the price.
- **Markets:** every allowed TMN market with at least 5 billion TMN traded in 24 hours, plus what we hold, plus
  BTCTMN and USDTTMN (D42). Tests on the past use our first 6 (BTC, ETH, SOL, XRP, PEPE, USDT) and 12 others.
  We stay in TMN markets. Moving to USDT pairs costs more than it saves over 12 hours (F42, D34).

## Risk modes: the agent decides how hard to trade

Every cycle the analyst chooses a risk mode, and says why (D41). It reads the skill `risk-modes` and calls
`get_risk_modes`, which gives each mode's limits and its past results over 12 hours, 1 day, 3 days and 89 days.
It weighs the hours left, our result so far, the drawdown and the market.

| Mode | Trades | Risk a trade | Max one coin / in coins | 12 h avg (up) | 3 days avg | 89 days |
|---|---|---|---|---|---|---|
| defensive | 12-hour setups where the move beats 1.5x the cost | 0.75% | 25% / 60% | -0.04% (14%) | -0.03% | +2.8% |
| normal | 12-hour setups | 0.75% | 25% / 60% | -0.06% (23%) | +0.13% | +14.7% |
| active | 12-hour setups and the 1h trend rule | 0.75% | 25% / 60% | -0.13% (34%) | +0.40% | +25.2% |
| aggressive | all, full size | 1.5% | 35% / 80% | -0.19% (36%) | +0.74% | +42.5% (drawdown 15%) |

On the last 12 hours before going live (F56): defensive -0.02%, normal +0.20%, active -0.07%, aggressive -0.62%,
holding every market -0.33%. A perfect trader within our caps could have made about +3.5%.

Code keeps the outer limits in every mode: a stop on every buy, the caps, never all-in, no new buys near the end,
everything sold before the end. After 4% below the peak or 1.5% down in a day, code allows at most `normal`.

A 20% gain in 12 hours is not in the data: even buying the exact low and selling the exact high of one coin
reached 20% in under 1% of 12-hour windows (F52).

## Risk and capital management

All in `risk.py` and `live.py`, normal code. The AI can't skip it.

- At most 0.75% of equity is lost if a stop is hit, costs included. Grade B, a low conviction and the risk
  officer can lower that.
- No buy where the usual 12-hour move is under 1.5 times the round-trip cost. At most 12 buys in 24 hours.
- These came from testing each rule in research file 03 alone (F48). Take-profit, cooldowns, a soft drawdown and
  losing-streak pauses did not help on both market sets, so they are off.
- At most 25% of equity in one coin, and 60% in coins together. Never all-in.
- No new buys after losing 2% in a UTC day, or while equity is 6% below its peak.
- No buys on data older than 5 minutes. Orders below the Wallex minimum (50,000 TMN) are refused.
- No new buys in the last 3 hours before the end of trading. 30 minutes before the end, everything is sold into
  Toman, and the guard keeps trying every minute.
- Kill switch: `wx kill` cancels every open order and sells every position. A file `data/KILL` does the same
  from inside the running bot.
- After 3 failed cycles or guard rounds in a row: no new buys until a clean cycle.
- Each verdict names the rule that decided, and is logged.

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
uv run wx agent --shadow --end-at 2026-10-23T00:30   # the agent on live data, fake orders
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
