# hackathon-starcoach-wallex

A bot that trades on Wallex by itself. A LangGraph agent decides every trade with tools, trader skills and memory: which market, how much to risk, the stop and the exit plan. Normal code keeps the hard limits and sizes every order.

Start with [docs/STRATEGY.md](docs/STRATEGY.md): how it trades, the AI's role, risk, and results.

## Set up

You need [uv](https://docs.astral.sh/uv/).

```bash
uv run wx
```

This installs the project and prints which keys are set. Copy `.env.example` to `.env` and fill in the values. Git ignores `.env`.

| Setting | Needed for |
|---|---|
| `WALLEX_API_KEY` | `wx account`, round-trip costs, real balances. Real orders (`wx agent --live`) need a key that can trade. Never give it withdrawal rights. |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | Anything that asks the AI: `wx ai`, `wx decide`, `wx run`, `wx replay`. Any OpenAI-compatible API. |

## Trade with the agent

```bash
uv run wx agent --shadow --end-at 2026-10-23T00:30   # fake orders on live data, every liquid allowed TMN market
uv run wx order-test USDTTMN                          # check real orders: a buy 20% under the price, read back, cancelled
uv run wx agent --live --end-at 2026-10-23T18:00     # REAL orders
uv run python scripts/keep_running.py --live --end-at 2026-10-23T18:00   # the same, restarted after any stop
```

`scripts/keep_running.py` restarts the agent if its process ever stops, until trading ends or `data/KILL` exists. The book, orders and memory are on disk, so a restart loses nothing. Starts and stops are logged in `data/brain/supervisor.log`, and the agent's output in `data/brain/live_run.log`.

Every 15 minutes, one cycle of the LangGraph agent ([docs/STRATEGY.md](docs/STRATEGY.md)): features, candidates, the AI analyst with tools (Wallex MCP order book, skills, lessons), the AI risk officer, the code gate and risk check, orders, lessons after closed trades, the log. Between cycles, a guard checks stops every minute. `--end-at` is when trading ends (UTC): no new buys in the last 3 hours, everything sold into Toman 30 minutes before. Options: `--interval`, `--cycles`, `--no-officer`.

| Command | What it does |
|---|---|
| `uv run wx live` | The live book: positions, results, reasons. |
| `data/market_closes.json` | Markets Wallex will close, e.g. `{"USDTTMN": "2026-10-22T20:15"}` (UTC). No new buys 45 minutes before, held coins sold 30 minutes before (D50). Read every minute. |
| `uv run wx kill` | Kill switch: cancel every open order and sell every position. A file `data/KILL` does the same inside a running agent. |
| `uv run wx verify-log --live` | Check the hash chain of the live decision log (`data/live/decisions/`). Without `--live`: the shadow log. |
| `uv run wx tradelog --live` | The judges' trade report: every live trade with the signal, the AI's reason and plan, the judge, the risk check, the fill, the exit and the result. The live agent also rewrites it after every cycle in `data/live/trade_report.md`. |
| `uv run wx shadow` | The older shadow book (`wx run --shadow`). |

Memory lives in `data/brain/` (SQLite), with every AI call and answer (`llm_cache.sqlite`; `WX_LLM_REPLAY=1` uses saved answers again). The live book is `data/live/book.json`, and every order event is in `data/live/orders.jsonl`.

## Trade (older loop, shadow)

```bash
uv run wx run --shadow
```

Every 15 minutes (at :00, :15, :30, :45): update the candles, compute the features, let the AI agent review every trend buy, run the risk check, and place fake limit orders. Fake orders fill, stop and close on the live candles, with the same rules as the backtest. Every cycle is logged in `data/decisions/`, even one that fails. The book is `data/shadow/book.json`, so a restart loses nothing. No real order is placed.

Options: `--role` (`agent` by default; `veto`, `informed`, `pick`, see DECISIONS D24 to D31), `--interval`, `--cycles`. Without `--shadow`, decisions are only logged.

```bash
uv run wx shadow                          # the book: equity, open positions, closed trades
uv run wx tradelog > results/trade_log.md # per-trade log: setup, AI reason, risk verdict, result
```

## Test on the past

| Command | What it does | Needs |
|---|---|---|
| `uv run wx candles` | Saves 120 days of 1-minute and 1-hour candles to `data/candles/`. Later runs add only what is missing. | nothing |
| `uv run wx backtest` | Trades 5,000,000 TMN hour by hour over the saved history, with the risk check. Each policy, taker and limit orders, each half, and 3-day windows. | candles |
| `uv run wx backtest --hours 12` | A fresh book every 6 hours, trading the agent's setups for 12 hours, then sold into Toman. | candles |
| `uv run wx study` | Each buy setup on its own, with its exit rule and several stops. | candles |
| `uv run wx replay` | Asks the AI about 40 past moments, and compares its buys with the same rules without the AI. `--role`, `--moments`, `--seed`. | candles, AI |
| `uv run wx replay --from results/replay_trend_agent.jsonl` | The summary of a saved replay, without asking the AI. | nothing |

Saved outputs are in [results/](results/README.md). Markets can be named after any command, for example `uv run wx backtest PUMPTMN ARBTMN`.

## Look at Wallex and the AI

| Command | What it does |
|---|---|
| `uv run wx markets` | All Wallex markets, how many we may trade, and a saved copy. |
| `uv run wx rules` | Decimals, minimum quantity and minimum order value per market. |
| `uv run wx account` | Our balances and fee rates (needs `WALLEX_API_KEY`). |
| `uv run wx watch` | Live best bid and ask every minute, logged in `data/prices/`. |
| `uv run wx features` | The 28 features the AI sees, for each market, now. |
| `uv run wx ai` | One small question, to check the AI settings. |
| `uv run wx decide` | One decision cycle, printed and logged. |

## Tests

```bash
uv run pytest                 # about 150 tests, no internet
uvx ruff check src tests      # lint
```

## Docs

- [Strategy](docs/STRATEGY.md): how the bot trades, the AI's role, risk, results. Start here.
- [Results](results/README.md): saved backtest, study and replay outputs.
- [Roadmap](docs/ROADMAP.md): the phases.
- [Progress](docs/PROGRESS.md): what we did, change by change.
- [Decisions](docs/DECISIONS.md): what we decided (D), and facts we checked (F).
