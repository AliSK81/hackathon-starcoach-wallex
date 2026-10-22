# Progress Log

[ROADMAP.md](ROADMAP.md) lists the phases. This file records what we actually did.

- Add one entry for every change that ships. Never write entries in advance.
- A "change" is the smallest step that still leaves the project working.
- Decisions that last longer than one change go in [DECISIONS.md](DECISIONS.md), not here.

## Status board

Update this after every change.

- **Current phase:** 4, waiting for a trading key. Phases 2 and 3 done. Phases 6 and 7 in progress. The shadow book keeps running.
- **Live trading:** not live yet
- **Version trading live:** none yet

### What we need from the team

| Item | Needed by | Status |
|---|---|---|
| Wallex key (read) in `.env` | Phase 1 | Works (F1). |
| AI provider, model, URL, and key in `.env` | Phase 2 | Works (F11). |
| A computer that can reach Wallex and the AI and run without stopping | Phase 3 | Unknown |
| Wallex key that can trade but **cannot** withdraw | Phase 4 | Waiting |
| Which account is the competition account | Phase 4 | Done: the account behind `WALLEX_API_KEY` (D14). |

## How to work on the next change

1. Read the status board and the roadmap table. Find the current phase.
2. If the phase has no plan file yet, write one in `docs/phases/`. Keep it short. Mark the phase `planned` in the roadmap.
3. Read the last entry below. Pick the next change. If something in "What we need from the team" blocks it, ask the user now.
4. Explore only this change. Check DECISIONS.md first, and don't ask again what is already decided there. Ask the user what only they can decide.
5. Build it and ship it. Run something that proves it works.
6. Add an entry below. Update the status board and the roadmap table. Put lasting decisions in DECISIONS.md.
7. Stop, unless the user asked you to keep going. Never plan two changes ahead.

## Entry template

```
### Change N — <what shipped, in one line> — <date>
Phase: <e.g. 1, step 2>
How to see it: <the exact command>
Proof it works: <what you ran, and what happened>

Research: <what you checked, or "none". Say if old research was wrong.>
Questions: <question -> answer, or "none">
Decisions: <choices made for this change. Lasting ones go to DECISIONS.md.>

Shipped:
- ...

Not done yet:
- ...

Next change idea:
- <a suggestion only>
```

## Entries

### Change 1 — Python project that runs with one command — 2026-10-22
Phase: 0, whole phase
How to see it: `uv run wx`
Proof it works: `uv run wx` printed the version and "missing" for all four keys, and exited with 0. With `WALLEX_API_KEY=dummy` it printed "set" and not the value. `uv run pytest` passed 4 tests.

Research: research file 10, for layout and how to handle secrets.
Questions: none
Decisions: D9, D10.

Shipped:
- `pyproject.toml` and `uv.lock`, with the `wx` command.
- `src/wx/config.py`: reads `.env` and the environment. It never prints a key.
- `src/wx/cli.py`: `wx` shows which keys are set.
- `.env.example`, `.gitignore`, and a short README. The README is now UTF-8.
- `tests/test_config.py`: works with no `.env`, reads `.env`, hides key values, and checks `.env.example`.
- Phase plan: [phases/phase-0-setup.md](phases/phase-0-setup.md).

Not done yet:
- The Wallex key is still not in `.env`.

Next change idea:
- Phase 1 plan, then read public Wallex market data and log it.

### Change 2 — `wx markets` lists allowed markets and saves a snapshot — 2026-10-22
Phase: 1, step 1
How to see it: `uv run wx markets`
Proof it works: it read 373 markets from Wallex. 120 are allowed and 253 are forbidden, the same as the research found. It printed the top 10 by volume and saved `data/markets/20261021T223710Z.json`. `uv run pytest` passed 10 tests, with no internet.

Research: research file 05, sections 1, 7 and 13. Still true: `/v1/markets` needs no key and has the same fields.
Questions: none
Decisions: D11.

Shipped:
- Phase plan: [phases/phase-1-read.md](phases/phase-1-read.md).
- `src/wx/wallex.py`: GET a public Wallex path. Any error becomes a `WallexError`.
- `src/wx/markets.py`: the allowed-market rule (D3), top by volume, and saving a snapshot.
- `wx markets`: prints the report. On a network error it says so and exits with 1.
- The forbidden-market list moved to `src/wx/inactive_markets.txt`. Links in the docs point there now.
- `data/` is ignored by git.
- `tests/test_markets.py`: 6 tests.

Not done yet:
- The market rules (decimals, minimum size) are saved but not used by any code yet.
- No candle history, no live price loop.
- The keys in `.env` are not tested yet.

Next change idea:
- Save 1-minute and 1-hour candles to disk for a few liquid allowed markets.

### Change 3 — `wx candles` saves 1-minute and 1-hour candles to disk — 2026-10-22
Phase: 1, step 2
How to see it: `uv run wx candles` (or `uv run wx candles BTCTMN --days 60`)
Proof it works: the first run saved 30 days for 6 markets in 2 min 13 s: about 43,100 1-minute and 719 1-hour candles per market. A second run added only 1 new candle. `uv run pytest` passed 15 tests, with no internet.

Research: research file 05, section 8. Two claims were wrong today:
- 1-minute history goes back at least 120 days, not about 19.
- One request can cover up to about 46 hours of 1-minute candles, not 36. 48 hours gives `no_data`.
Also seen: quiet minutes come back as candles with zero volume. Real gaps exist, the same in every market (for example 80 minutes on 2026-09-22 from 12:39 UTC). A narrow re-fetch shows the same gap, so Wallex has no data there.
Questions: none
Decisions: D12.

Shipped:
- `fetch_candles` in `src/wx/wallex.py`.
- `src/wx/candles.py`: fetches in windows of 720 candles, oldest first. Each run continues from the last saved candle. On an error it keeps what it has, so the next run continues.
- `wx candles [SYMBOL ...] [--days N]`: refuses any market that is not allowed. Exits with 1 if anything failed.
- `tests/test_candles.py`: 5 tests.

Not done yet:
- Gaps are kept, not filled. A later phase decides how to fill them.
- If `--days` grows later, older candles are not back-filled for a file that already exists.
- Nothing runs `wx candles` on a schedule yet.

Next change idea:
- A loop that reads live prices for the default markets every minute, logs them, and survives network errors.

### Change 4 — `wx watch` logs live prices every minute and survives errors — 2026-10-22
Phase: 1, step 3
How to see it: `uv run wx watch` (Ctrl+C stops it), or `uv run wx watch --cycles 3`
Proof it works:
- Live: `uv run wx watch --cycles 3` logged 6 prices in each of 3 cycles and exited with 0. Cycles 2 and 3 started exactly on the minute.
- Network down: with a proxy that refuses connections, 2 cycles each logged the error for every market, and the loop ended normally.
- `uv run pytest` passed 19 tests, with no internet.

Research: research file 05, sections 1 and 9. `/v1/depth` needs no key. Its prices are JSON numbers, not strings.
Questions: none
Decisions: D13.

Shipped:
- `fetch_best_prices` in `src/wx/wallex.py`: best bid and ask from the order book, as exact decimals.
- `src/wx/prices.py`: one cycle reads every market, then logs bid, ask, mid and spread to `data/prices/<UTC date>.jsonl`. A failed market or a failed cycle is logged and the loop goes on.
- `wx watch [SYMBOL ...] [--interval 60] [--cycles N]`.
- `wx candles` and `wx watch` share one allowed-market check.
- `tests/test_prices.py`: 4 tests.

Not done yet:
- At start, `wx watch` needs Wallex to check the markets. If Wallex is down then, it exits with 1. After that it survives errors.
- Ctrl+C is handled in the code but was not tested by hand.
- No retry inside a cycle. A failed market waits for the next minute.
- Nothing keeps it running after a crash or a reboot.

Next change idea:
- Use the key: read balances and fees, and write them in DECISIONS.md. This is the last Phase 1 item.

### Change 5 — `wx account` reads balances and fees with our key — 2026-10-22
Phase: 1, step 4
How to see it: `uv run wx account`
Proof it works:
- Live: it printed 5,000,000 TMN and the fee rates, and exited with 0. It saved `data/account/20261021T230003Z.json`.
- Wrong key: it printed `HTTP 401 1201 invalid API key format` and exited with 1.
- The key does not appear in the output, the saved account file, or any other file in `data/`.
- `uv run pytest` passed 26 tests, with no internet.

Research: research file 05, sections 5 and 6. Fee rates were unknown. Now they are F3 to F6.
Questions: none
Decisions: none. Facts F1 to F6.

Shipped:
- `src/wx/wallex.py`: the key can go in the `x-api-key` header. HTTP errors now show the Wallex code and message. New: `fetch_balances`, `fetch_fees`.
- `src/wx/account.py`: non-zero balances with free = value - locked, fee groups, and a saved snapshot.
- `wx account`: prints balances and fees. It says so if the key is missing.
- `wx` no longer crashes when it prints a Persian message on a console that can't show it.
- `tests/test_account.py`: 7 tests.

Bug found and fixed: the fee reply has a `metaData` entry that is not a market. The first live run crashed on it.

Not done yet:
- We don't know if this key can trade. We will only learn that in Phase 4.
- The market rules (decimals, minimum size) are still not in DECISIONS.md or used by code.

Next change idea:
- Market rules for the default markets: load them from `/v1/markets`, write them in DECISIONS.md, and add round-to-rules helpers. This finishes Phase 1.

### Change 6 — market rules and round-to-rules helpers. Phase 1 done — 2026-10-22
Phase: 1, step 5 (last)
How to see it: `uv run wx rules` (or `uv run wx rules BTCUSDT`)
Proof it works:
- Live: `wx rules` printed the rules for the 6 default markets. `wx rules TONTMN` refused, with exit 1.
- `wx candles BTCTMN` and `wx watch PEPETMN --cycles 1` still work after the shared market check changed.
- `uv run pytest` passed 32 tests, with no internet.

Research: research file 05, section 7. It guessed that `stepSize` and `tickSize` are decimals. Now checked (F7). New: the MARKET flag is off on most markets (F9).
Questions: none
Decisions: none. Facts F7 to F10.

Shipped:
- `src/wx/rules.py`: `MarketRules` from a `/v1/markets` entry. `round_qty` rounds down. `round_price` rounds a buy down and a sell up. `problems` lists why Wallex would refuse an order.
- `wx rules [SYMBOL ...]`: prints the rules table.
- `wx candles`, `wx watch` and `wx rules` share one market check (`pick_markets`).
- `tests/test_rules.py`: 6 tests.

Not done yet:
- The rules are not confirmed by a real order. That comes in Phase 4.
- We don't know if SOLTMN, XRPTMN and PEPETMN accept MARKET orders. A stop-loss there may need a LIMIT order priced to fill at once.

Next change idea:
- Phase 2 plan. Then test the AI settings in `.env` with one small call.

### Change 7 — `wx candles` keeps 120 days and back-fills older history — 2026-10-22
Phase: 1, follow-up (asked by the team)
How to see it: `uv run wx candles`
Proof it works: one run back-filled about 129,570 1-minute and 2,159 1-hour candles per market in 7 min 41 s. Now every market has 120.0 days: 1-minute data from 2026-06-23 and 1-hour data from 2026-06-24, up to 2026-10-21. `uv run pytest` passed 34 tests.

Data check: the 90 older days added no gaps. Missing 1-minute candles are 0.06–0.07% per market (mostly the 80-minute outage on 2026-09-22). USDTTMN misses 0.65%, mostly 2 long gaps in October. Files take 52 MB in `data/candles/`.
Research: none new.
Questions: is the balance for the competition? -> yes (D14).
Decisions: D14, D15.

Shipped:
- `update_candles` now also back-fills: if `--days` reaches before the first saved candle, it fetches that part, newest first. A failure leaves no hole, and the next run goes on.
- `--days` default is 120, not 30.
- 2 new tests in `tests/test_candles.py`.

Not done yet:
- If Wallex has no data as far back as `--days`, each run asks again for that empty part. This doesn't happen at 120 days.

Next change idea:
- Phase 2 plan. Then test the AI settings in `.env` with one small call.

### Change 8 — Phase 2 plan, and `wx ai` checks the AI settings — 2026-10-22
Phase: 2, step 1
How to see it: `uv run wx ai`
Proof it works:
- Live: `wx ai` asked the model one small trading question. It answered `HOLD` with a reason in valid JSON, in 4.3 s and 426 tokens. Exit 0.
- Wrong key: it printed `HTTP 401` and exited with 1. The provider repeated the key in its error. Our output showed `***` instead.
- `uv run pytest` passed 42 tests, with no internet.

Research: research files 01, 02 and 06, for the plan. They agree: code computes the indicators, the AI picks and explains, and a bad AI answer becomes "do nothing".
Questions: none
Decisions: D16. Facts F11 to F13.

Shipped:
- Phase plan: [phases/phase-2-decide.md](phases/phase-2-decide.md).
- `src/wx/llm.py`: one chat call to any OpenAI-compatible API. It keeps the model's reasoning, removes `<think>` parts from the answer, and reads the JSON in an answer. Any error becomes an `LLMError` without the key.
- `wx ai`: the check above. It says which settings are missing.
- `tests/test_llm.py`: 8 tests.

Not done yet:
- No retry. A failed call is just reported.
- We don't know the AI's request limits.

Next change idea:
- `wx features`: indicators for each market, from saved candles and the live order book.

### Change 9 — `wx features` computes indicators for each market — 2026-10-22
Phase: 2, step 2
How to see it: `uv run wx features` (or `uv run wx features BTCTMN`)
Proof it works:
- Live: it printed 26 features for the 6 default markets in 10 s, and exited with 0. Five markets were `trend_up` and SOLTMN was `range`.
- The maths matches the `ta` library on the last 500 BTCTMN and PEPETMN hours: RSI, ATR, ADX, +DI, -DI, MACD and EMA 20 are equal. EMA 200 was 0.05% to 0.08% off, because of how the average starts. We now use 1,000 hours, so this matters even less.
- `wx features TONTMN` refused, with exit 1.
- `uv run pytest` passed 53 tests, with no internet.

Research: research file 06, sections 2 and 6 and the feature list. We kept about half of its list.
Questions: none
Decisions: D17. Fact F14.

Shipped:
- `src/wx/indicators.py`: EMA, Wilder average, RSI, ATR, ADX with +DI and -DI, MACD histogram, z-score, percent rank.
- `src/wx/features.py`: `FEATURES` names each feature and says what it means. `build_features` computes them. `market_features` first brings the candles up to date and reads the live book.
- `wx features [SYMBOL ...]`: prints one row per feature. With the key, it adds the round-trip cost.
- `tests/test_features.py`: 11 tests.

Not done yet:
- Round-trip cost is 0.6% to 1.2% (F14). A trade must move more than that just to break even.
- Markets are read one after another, which takes about 10 s.
- No BTC-led or Toman-drift feature across markets yet. The AI sees BTCTMN and USDTTMN among the markets.

Next change idea:
- `wx decide`: send these features to the AI, check its JSON answer, and log the decision.

### Change 10 — `wx decide` asks the AI for a checked, logged decision — 2026-10-22
Phase: 2, step 3
How to see it: `uv run wx decide` (or `uv run wx decide BTCTMN`)
Proof it works:
- Live: the AI said HOLD on all 6 markets, with confidence 0.74 to 0.88. Each reason cites real feature values. For example: the uptrends are strong, but RSI is high and prices are pulling back, so the edge does not cover the round-trip cost. No problems found. Exit 0. It took 73 s in all, and the AI took 60 s of that.
- The log line has the code version, all features, cash (5,000,000 TMN), holdings (none), the raw answer and 6,500 characters of AI reasoning.
- AI unreachable: `wx decide BTCTMN` logged a `fallback` record with HOLD and the error, and exited with 1.
- No key appears in the prompt or the log (tested).
- `uv run pytest` passed 65 tests, with no internet.

Research: research file 01 (decision schema, cited features, fallback to HOLD) and file 02 (strict JSON, never retry into a trade).
Questions: none
Decisions: D18. Fact F15.

Shipped:
- `src/wx/decide.py`: the prompt, the answer check, holdings worth at least the minimum order, and the decision log. The log records the code version (package version and git commit).
- `wx decide [SYMBOL ...]`.
- `wx features` and `wx decide` share one feature loop.
- `tests/test_decide.py`: 12 tests.

Not done yet:
- One decision so far, and it was HOLD everywhere. We have not seen a BUY yet.
- The AI takes about 60 s. That is fine for a cycle of several minutes, but not for every minute.
- The AI does not see its past decisions.

Next change idea:
- `wx run`: a loop that decides on a fixed beat, logs every cycle, and survives errors. This finishes Phase 2.

### Change 11 — `wx run` decides on a beat and logs every cycle. Phase 2 done — 2026-10-22
Phase: 2, step 4 (last)
How to see it: `uv run wx run` (Ctrl+C stops it), or `uv run wx run --interval 120 --cycles 3`
Proof it works:
- Live: `wx run --interval 120 --cycles 3` ran 3 cycles and exited with 0. Cycles 2 and 3 started exactly on the beat (00:00:00 and 00:02:00 UTC). Each cycle logged one line. The AI took 53 to 64 s.
- All 3 cycles said HOLD on all 6 markets, with no problems found. The reasons cite real values. The markets are in uptrends but pulling back, RSI is high, and a typical hourly move is below the round-trip cost.
- Tests show that a failed AI call logs a `fallback` cycle. An unexpected error logs a `none` cycle with the error, and the loop goes on.
- `uv run pytest` passed 68 tests, with no internet.

Data check: the AI called USDTTMN illiquid. That is true at night (F16). In the first `wx decide`, BTCTMN's 15-minute, 1-hour and 4-hour returns were all -0.07%. That is also real: the last trade price did not change for hours overnight.
Research: research file 02 (decision cadence).
Questions: none
Decisions: D19. Fact F16.

Shipped:
- `src/wx/beat.py`: runs a step on a fixed beat and survives a failed step. `wx watch` uses it too now.
- `wx run [SYMBOL ...] [--interval 900] [--cycles N]`: one decision every beat, logged in `data/decisions/`.
- `wx decide` and `wx run` share one decision cycle. Each log line has the cycle number.
- Output is printed line by line, so a long run's output is never held back.
- `tests/test_run.py`: 3 tests.

Not done yet:
- The AI has said HOLD in all 4 decisions so far. We have not seen a BUY yet.
- Nothing keeps `wx run` going after a crash or a reboot.
- At night, USDTTMN has no trades, and the other markets are thin (F16).

Next change idea:
- Phase 3 plan. Then the risk check: approve, shrink or reject each AI decision, testable without internet.

### Change 12 — Phase 2 reopened: one-day time frame, `wx replay`, and the first real test of the AI — 2026-10-22
Phase: 2, results review
How to see it: `uv run wx replay` (about 10 minutes for 40 moments)
Why: Change 11 closed Phase 2 because the checklist passed. Nobody checked whether the decisions were any use. The AI had said HOLD every time. The prompt asked for gains within a few hours, but over 4 hours prices usually move less than the round-trip cost. The bot would never have traded. ROADMAP rule 11 now makes this check part of every phase.
Proof it works:
- Typical moves over 120 days: 4 hours 0.24% to 0.82%, 24 hours 0.81% to 2.16%. Round-trip cost is 0.61% to 1.17% (F14). So the prompt now uses about a day (D20).
- `wx replay --moments 40`: 40 moments from the last 60 days, 4 AI calls at a time, no AI failure. Results in F18: the AI buys now (7%), but its buys did no better than its holds.
- Setup study without AI (F17): only "buy after a sharp drop" was positive in both halves of the period, and only by +0.42% a trade. The 2026-10-07 drop kept falling 3% to 9% the next day, so dip buying needs a stop-loss.
- `uv run pytest` passed 72 tests. One test proves past features never use later candles.

Research: research file 06, sections 2, 3 and 6, for the textbook setups and thresholds. None were tuned.
Questions: none
Decisions: D20, D21. Facts F17, F18.

Shipped:
- ROADMAP rule 11, and Phase 2 back to "in progress".
- `typical_24h_move_pct` feature. Minimum history is now 750 hours.
- The prompt: judge over about a day, and compare the cost with the typical day move.
- `src/wx/replay.py` and `wx replay [SYMBOL ...] [--moments 40] [--days 60] [--seed 7] [--workers 4]`. Each run is logged in `data/replay/`.
- `tests/test_replay.py`: 4 tests.

Not done yet:
- We have no proven edge. Not from the AI, and only a weak one from one setup.
- Costs eat most of any edge. Limit orders (maker 0.25%, no spread crossing) could cut the round trip to about 0.5%. Whether they fill is a Phase 4 question.
- The replay holds for 24 hours with no stop-loss. Phase 3 adds stops.

Next change idea:
- Setups: code flags the setups from F17 with their past results. The AI decides which to take. The replay compares the AI with taking every setup and with doing nothing, with a stop-loss on each entry.

### Change 13 — buy setups in code, `wx study`, and the AI tested against them — 2026-10-22
Phase: 2, results review
How to see it: `uv run wx study` (30 s, no AI), then `uv run wx replay` (about 10 minutes)
Proof it works:
- `wx study` (F19): no setup is clearly above 0 after costs. The best is sharp_drop, +0.51% +/- 0.35 a trade. Every stop lowered the average. 4 ATR lowered it least.
- `wx replay` on 40 setup moments (F20): the AI's 21 buys averaged -0.87%. Taking every setup averaged +0.15%. The setups the AI skipped averaged +0.44%. The AI made the result worse.
- No AI failure and no problem found in 240 market decisions. Every BUY named an active setup.
- `uv run pytest` passed 78 tests, with no internet.

Bug found by a test and fixed: in a flat market the typical move is 0, so sharp_drop fired on a 0% change. It now needs a real fall.
Research: research file 06, setups and stops.
Questions: none
Decisions: D22, D23. Facts F19, F20.

Shipped:
- `src/wx/setups.py`: 4 buy setups. A new `setups` feature lists the active ones.
- The prompt and check: a BUY must name an active setup. With no active setup and nothing held, the AI is not asked (driver `rules`). This also saves most AI calls in `wx run`.
- `wx replay`: picks moments with an active setup, simulates a stop, and compares the AI with taking every setup and with doing nothing.
- `src/wx/study.py` and `wx study [--stops 2 3 4]`.
- Tests: 78 in all. New ones cover the stop exit, the study, and BUY without an active setup.

Not done yet:
- The AI does not add value yet. In both replays it prefers trend setups and avoids buying drops, and the data says the opposite.
- The edges are small. Costs (0.6% to 1.2% a round trip) are the biggest problem.

Next change idea:
- Try two AI roles in the replay, each against "take every setup": (1) the AI gets each setup's past results, computed only from data before that moment, and takes a setup unless it sees a specific warning; (2) code takes the mean-reversion setups, and the AI only vetoes in a market-wide crash. Keep whichever beats the setups alone, and say so honestly if neither does.

### Change 14 — AI roles compared, risk check, and a portfolio backtest — 2026-10-22
Phase: 2 results review, and the first part of Phase 3 (risk check)
How to see it: `uv run wx backtest` (30 s, no AI), `uv run wx replay --role veto`
Proof it works:
- Replays (F21): `informed` made results worse, like `pick`. `veto` was neutral. So the AI's role is `veto` (D24).
- `wx backtest` (F22): with taker orders almost nothing makes money. With limit orders the mean-reversion setups do, but not in both halves of the history, except oversold on few trades.
- `uv run pytest` passed 87 tests. New tests cover the risk limits, the halt reset, limit-order fills, and one backtest trade.

Research: research file 03 (risk limits), 04 (fill model), 06 (exits).
Questions: none
Decisions: D24, D25, D26. Facts F21, F22.

Shipped:
- `decide.py`: roles `pick`, `informed`, `veto`. Each role names the setups it may buy through. `wx replay --role`.
- `study.py`: `SetupRecord`, each setup's record from before a moment.
- `risk.py`: `check_buy` and `update_peak`. This is the Phase 3 risk check. It runs without internet.
- `backtest.py` and `wx backtest`: policies x taker or limit orders x whole history or each half.
- `History.exit_after` now returns the exit time.

Not done yet:
- No setup is proven on markets it was not chosen on. Candles for 12 more markets are downloading for that test.
- `wx run` still uses the `pick` role and does not use the risk check.

Next change idea:
- Out-of-sample test: run `wx study` and `wx backtest` on the 12 new markets. Keep only the setups that hold up there.

### Change 15 — the AI as an agent with tools, and shadow trading — 2026-10-22
Phase: 2 (AI role) and 3 (shadow orders)
How to see it: `uv run wx run --shadow --role veto` (or `--role agent`), and `uv run wx replay --role agent`
Proof it works:
- The gateway supports tool calls (F23). Tests cover the tool loop: a normal call, a failing tool, and the round limit.
- Tests show the tools never see candles after the moment being decided.
- Shadow tests: a fake order waits, fills below the bid, is stopped out with the right costs, survives a save and load, and is cancelled if it never fills. A full shadow cycle with a fake AI places a 937,500 TMN buy, and the next cycle refuses a second buy of the same market.
- `uv run pytest` passed 98 tests, with no internet.

Research: research file 08 (guarded tools), 04 (shadow fills), 05b (order states).
Questions: none
Decisions: D27, D28. Fact F23.

Shipped:
- `llm.chat_with_tools`: a small loop. The AI may call tools a few times, then answers. Every call is kept in the reply.
- `agent.py`: time-safe tools. The `agent` role (veto plus tools).
- `shadow.py`: the fake book. `cycle.py`: the live cycle, moved out of `cli.py`, with the risk check and shadow orders.
- `wx run` and `wx decide` take `--role` and `--shadow`.

Not done yet:
- The agent replay is still running. We don't know yet if tools help.
- The shadow book has not traded live for long.

Next change idea:
- Read the agent replay. Run the out-of-sample test on the 12 new markets. Keep only what holds up.

### Change 16 — the Toman drift, and a trend strategy that holds up on new markets — 2026-10-22
Phase: 2 (strategy) and 3 (risk check, shadow)
How to see it: `uv run wx backtest`, then `uv run wx backtest PUMPTMN ARBTMN BNBTMN DOGETMN TRXTMN STMN APETMN SUITMN LTCTMN UNITMN ADATMN SANDTMN`
Proof it works:
- Prices in Toman rose a lot (F24). Our earlier setups sold after 24 hours, so they missed most of every trend.
- Each setup now has its own exit rule. `trend` rides a 1h uptrend until the EMA 20 falls below the EMA 50.
- Backtest with the risk check and limit orders (F25): +36.8% on our 6 markets and +43.6% on 12 markets not used to pick it. Both halves were positive in both cases. Worst drawdown 7.9% and 12.7%.
- The dip setups lost on the new markets (-8.1%). They are no longer traded (D29).
- `uv run pytest` passed 100 tests. `uvx ruff check src tests` is clean.

Research: research file 06 (EMA trend rules). It warned that the USDTTMN drift may not last. F24 says the same.
Questions: none
Decisions: D29. Facts F24, F25.

Shipped:
- `trades.py`: `History` and `trade()`. One walk decides fills, stops, setup exits and costs for the backtest, replay, study and shadow book.
- `setups.py`: each setup has an entry and an exit rule. New `trend`. `breakout` and `trend_momentum` removed.
- `backtest.py`, `study.py`, `replay.py`, `shadow.py` now use `trade()`.
- Phase 3 plan: [phases/phase-3-risk-shadow.md](phases/phase-3-risk-shadow.md).

Not done yet:
- The veto replay on trend moments is running. We don't know yet if the AI's vetoes help or hurt.
- The live shadow book has just restarted with the trend veto.
- The drawdown on volatile coins (12.7%) is above the 6% halt line. The halt pauses buying, but does not cut open positions.

Next change idea:
- Read the trend veto replay and the shadow cycles. Then look at drawdown: fewer coins at once, or smaller size on volatile coins.

### Change 17 — 3-day windows, the AI's veto checked by code, and the first live shadow fills — 2026-10-22
Phase: 2 (AI role) and 3 (shadow)
How to see it: `uv run wx backtest` (last line per policy), `uv run wx run --shadow --role veto`, `uv run wx shadow`
Proof it works:
- 3-day windows (F28): trend is up in about half of all 3-day windows. The average is positive (+0.87% on our 6 markets), carried by a few big winners. Over 3 days, no strategy here is reliably profitable.
- Free AI veto over trend buys (F27): the AI stopped 70% of buys, and the stopped ones did better. So vetoes are now checked by code (D30).
- Live shadow, first cycles: the AI reviewed 6 markets and explained each one. The risk check approved BTC and ETH at the per-coin cap, shrank XRP to the 60% total cap, and rejected PEPE. The three limit orders filled within 10 minutes.
- Tested ideas that did not hold up on both market sets are listed in F26 (trailing stop, entry filters).
- `uv run pytest` passed 108 tests.

Research: none new.
Questions: none
Decisions: D30. Facts F26, F27, F28.

Shipped:
- `veto.py` and the checked veto in the `veto` and `agent` roles.
- `wx backtest`: 3-day windows from every day.
- `wx shadow`: the shadow book report.
- Shadow buys go in order of the AI's confidence.

Not done yet:
- The checked-veto replay is running.
- Among the AI's buys, the more confident half did better (+1.73% against -0.28%, 49 buys). Too few to use.
- The shadow book has run for less than an hour.

Next change idea:
- Read the checked-veto replay. Let the shadow book run through the night. Then write the doc for judges (Phase 7) with the honest results.

### Change 18 — the checked veto helps a little, repeatable backtests, saved results — 2026-10-22
Phase: 2 (done, see below) and 3
How to see it: `uv run wx replay --from results/replay_trend_checked_veto.jsonl`, `uv run wx backtest`
Proof it works:
- Checked veto replay (F31): buys the AI let through +1.53%, all trend buys +1.44%, the 6 it stopped -0.91%. The first AI role that did not make results worse.
- `wx backtest` twice in a row gives the same output, because past tests now use fixed spreads (F30).
- Without the daily-loss and drawdown halts, the backtest does worse on both market sets (F29).
- The live shadow book filled its first three orders, and `wx shadow` shows them at today's prices.
- `uv run pytest` passed 113 tests. `uvx ruff check src tests` is clean.

Research: none new.
Questions: none
Decisions: none new. Facts F29, F30, F31.

Shipped:
- `results/`: backtest, study and replay outputs, with the commands that make them.
- `wx replay --from <log>`: the summary of a saved replay, without the AI.
- `wx shadow`: open positions valued at the last saved close.
- Decisions carry `decided_at`. Shadow orders carry the same time, so each order links to its decision.
- `cli.py`: shorter, with a dispatch table. The default role is now `veto`.
- Phase 2 checklist: all done. The results review found the time frame, setup and AI-role problems, and each is fixed and measured.

Not done yet:
- The agent replay (checked veto plus tools) is running.
- `wx watch` is collecting live spreads through the night, to update F30 with daytime values later.
- Phase 3: the shadow book must run alone for several cycles with fills and exits.

Next change idea:
- Read the agent replay. Mark Phase 2 done in the roadmap if nothing new comes up. Keep the shadow book running.

### Change 19 — the agent is the default, a per-trade log, and fixes found in live shadow — 2026-10-22
Phase: 3, 6 and 7
How to see it: `uv run wx run --shadow`, `uv run wx tradelog`, `uv run wx shadow`
Proof it works:
- Agent replay (F33): buys it let through +1.64%, every trend buy +1.48%. So `agent` is the default role (D31).
- `wx tradelog` joins each shadow order with the decision that placed it, and shows the AI's reason and the risk verdict.
- Fixes found by reading live shadow logs: tool calls were not saved in the record; a held market was "bought" again when the AI said HOLD; the AI could not cite its own position fields. All three are fixed and tested.
- `uv run pytest` passed 117 tests.

Research: none new.
Questions: none
Decisions: D31. Facts F32, F33.

Shipped:
- `tradelog.py` and `wx tradelog`.
- Phase 6 and 7 plans. Phase 2 marked done in the roadmap.
- STRATEGY.md: why the AI gets our own read-only tools and not the Wallex MCP server.

Not done yet:
- The agent replay is running again, to save its tool calls as evidence.
- The shadow book runs with the agent role. No position has closed yet.

Next change idea:
- Save the agent replay in `results/`. Let the shadow book run until positions close, then check that shadow and backtest agree.

### Change 20 — robustness checks: other EMA pairs work, but the edge leans on the Toman drift — 2026-10-22
Phase: 6 (tests on the past)
How to see it: `uv run wx backtest BTCUSDT ETHUSDT SOLUSDT XRPUSDT PEPEUSDT DOGEUSDT`, and the facts below
Proof it works:
- Other EMA pairs (10/30, 50/100) also made money on both market sets (F35). The rule does not hang on its numbers.
- With the Toman drift removed (coins priced in USDT terms), the same rule made money in the 1st half but lost in the 2nd half on 4 of 5 coins (F36). Wallex's own USDT markets gave a similar answer, but they are much thinner.
- The agent replay with saved tool calls is in `results/` (F33). The live agent uses about 2 million tokens a day (F34).

Research: research file 06 warned that the USDTTMN drift may not last. This confirms it is the main risk.
Questions: for the team, when back: see "Not done yet".
Decisions: none new. Facts F33 to F36.

Shipped:
- Candles for 6 USDT markets, for the drift test.
- STRATEGY.md now says plainly that the result depends on the Toman.
- README rewritten in sections.

Not done yet:
- A team call: the strategy is, in effect, long coins against the Toman while they trend up. That worked in the last 120 days because the Toman fell. Is that the bet we want for the contest? The risk limits keep a 3-day loss near -4% in the backtest.
- The live shadow book has 3 open positions, slightly down overnight. None has closed yet.

Next change idea:
- Keep the shadow book running. When a position closes, compare it with the backtest's trade() on the same candles.

### Change 21 — Phase 3 done: 40 shadow cycles alone, a stop-out that matches the backtest, two AI failures fixed — 2026-10-22
Phase: 3 (last), and fixes found live
How to see it: `uv run wx shadow`, `uv run wx tradelog`
Proof it works:
- 40 shadow cycles with the agent role, through the night and the Tehran morning, with no crash. 36 asked the AI, 2 had nothing to decide, 2 failed and held every market.
- Orders: 4 placed, 4 filled within minutes, 1 stopped out. BTCTMN closed at -2.83% net, exactly the stop plus fees and half the spread (F39). The bot then bought BTCTMN again, lower, because the trend was still up. That position is up since.
- The risk check refused 74 buys at the 60% and 25% limits. The AI gave 33 `illiquid` vetoes on USDTTMN at night, all supported by the data.
- The two failures: a gateway HTTP 500 (now retried once, F37) and broken JSON after tool calls (now asked for once more in JSON mode, F39).
- Typical spreads now come from 237 live samples per market, night and day (F38).
- `uv run pytest` passed 122 tests. `uvx ruff check src tests` is clean.

Research: none new.
Questions: none
Decisions: none new. Facts F37 to F39.

Shipped:
- `llm.post`: one retry on a server error, lost connection or timeout.
- `chat_with_tools`: one more try in JSON mode if the final answer is broken.
- `cycle.run_cycle`: the book is saved right after settling.
- `shadow.Order.value`: a held market without a fresh price counts at its entry.

Not done yet:
- Phase 4 needs a Wallex key that can trade but not withdraw.
- The team decision from change 20 (the Toman drift) is still open.

Next change idea:
- Phase 4 plan, once the trading key is in `.env`. Until then, keep the shadow book running.

### Change 22 — a LangGraph agent with tools, skills and memory, 12-hour setups, and real orders — 2026-10-22
Phase: 4 (first real orders), 2 and 6 (the AI and tests on the past), 7 (docs)
How to see it: `uv run wx agent --shadow --end-at <end>`, `uv run wx backtest --hours 12`, `uv run pytest`
Proof it works:
- The agent graph ran live in shadow: 8 to 10 tool calls a cycle, including the order book from the Wallex MCP server, skills and lessons (F47). It placed a fake buy that code sized.
- Over 12 hours, no simple rule beat its costs (F41, F42). Holding USDT and trading USDT pairs did worse than TMN pairs (D34). The new setups lose less than the old trend rule in 12-hour windows, with a smaller worst case (F45).
- No arbitrage between TMN and USDT books (F43). Most of the Toman drift comes in Tehran daytime (F44).
- `uv run pytest` passed 141 tests, including the agent graph with a fake AI and the live executor with a fake Wallex. `uvx ruff check src tests` is clean.

Research: research files 01, 05c and 08 (agent frameworks, the Wallex MCP server, skills and memory patterns).
Questions: the user asked for a real agent (framework, tools, skills, memory, learning), USDT trading, and a strategy that knows when trading ends.
Decisions: D32 to D37. Facts F41 to F47.

Shipped:
- `brain.py`: the LangGraph graph. Analyst agent (`create_agent` with tool-limit and tool-retry middleware), risk officer, code gate, act, reflect, journal. SQLite checkpointer (short-term memory) and SQLite store (long-term memory).
- `skills/`: 8 trader playbooks the AI reads with a tool.
- `wallex_mcp.py`: the official Wallex MCP server for the order book and the latest trades, read only, with a REST fallback.
- `setups.py`: 4 setups for a 12-hour horizon, with grades. `features.py`: 5 new features (20-hour z-score, 4h trend, 15-minute RSI, the Toman's trend, BTC's day).
- `orders.py`, `live.py`, `execution.py`: real orders, the guard, the kill switch, selling everything before the end.
- `wx agent`, `wx live`, `wx kill`, `wx order-test`, `wx backtest --hours 12`. Study scripts in `scripts/`.

Not done yet:
- A Wallex key that can trade. Then `wx order-test`, then `wx agent --live`.
- The agent has no AI replay over past moments yet. Its live shadow log is the evidence so far.

Next change idea:
- Start live trading with the agent. Keep the shadow agent running next to it for comparison.

### Change 23 — research rules tested one by one, a bull and bear debate, memory fed to the AI, replay and a chained log — 2026-10-22
Phase: 4, 6 and 7
How to see it: `uv run python scripts/test_risk_rules.py`, `uv run wx backtest --hours 12`, `uv run wx agent --shadow`, `uv run wx verify-log`
Proof it works:
- Each risk rule from research file 03 was tested alone in 12-hour windows on both market sets (F48). Three rules won on both and are on (D38). Take-profit lost badly and is off.
- With them, the 12-hour average went from -0.074% to -0.038% on our markets and from -0.176% to -0.077% on the 12 others. The worst window went from -2.69% to -1.43%. It is still not positive on average.
- A real shadow cycle ran with the new graph and tools.
- `uv run pytest` passed 153 tests. `uvx ruff check src tests` is clean.

Research: files 01, 02, 03, 08, 09 and 12 (the union of roles, tools, memory and risk rules of the agents studied).
Questions: the user asked for every missing item and for a profitable system.
Decisions: D38 to D40. Fact F48.

Shipped:
- `risk.py`: cost in the size, minimum edge, trade cap, and (off) cooldowns, soft drawdown, losing streak, take-profit. `Ledger` of buys and exits.
- `trades.py`: an optional take-profit in `trade()`.
- `brain.py`: bull and bear nodes in parallel, the officer as judge, lessons losses first, theses per position, `get_candles`, `get_portfolio`, `check_order`, safe mode, a token budget, a halt flag.
- `wallex_mcp.py`: the cost of our order size from the book, and candles from the MCP server.
- `llm_cache.py`: every AI answer saved, and replayed with `WX_LLM_REPLAY=1`. `decide.py`: a hash-chained log and `wx verify-log`.
- `runner.py`: halt after repeated failures, and the kill file.

Not done yet:
- A Wallex key that can trade. Then `wx order-test`, then `wx agent --live`.
- The bull and bear debate has not yet met a live candidate in shadow.

Next change idea:
- Go live with the agent. Keep the shadow agent next to it.

### Change 24 — every test on the current agent, and the whole agent replayed on past moments — 2026-10-22
Phase: 6 (tests on the past)
How to see it: `uv run python scripts/test_all_scenarios.py 6|12|usdt`, `uv run python scripts/test_setup_split.py`, `uv run wx agent-replay --from results/replay_agent_graph.jsonl`
Proof it works:
- Every rule-level test from this project ran on the current agent rules, on 3 market sets (F49). The agent has the smallest drawdown and worst window in every test, is positive over the whole history on both TMN sets, and does not lose without the Toman drift. It earns little: over days, the old trend rule and plain holding made more, through the Toman drift, with 2 to 4 times the worst case.
- Split by setup, dips and trend_strong each win on one market set and lose on the other (F50). Both stay.
- The whole agent graph ran on 20 past moments with no failed cycle (F51). The candidates lost (-2.37% per trade). The AI shrank them to -1.79% weighted by size, but could not stop them.
- `uv run pytest` passed 154 tests.

Research: none new.
Questions: the user asked to test every scenario, not only 12 hours.
Decisions: none new. Facts F49 to F51.

Shipped:
- `scripts/test_all_scenarios.py`, `scripts/test_setup_split.py`.
- `agent_replay.py` and `wx agent-replay`: the whole graph on past moments, against the rules alone.

Not done yet:
- A Wallex key that can trade. Then `wx order-test`, then `wx agent --live`.

Next change idea:
- Go live with the agent, or decide first how much Toman drift to bet on.

### Change 25 — the agent chooses its risk mode by the time left — 2026-10-22
Phase: 2 and 3 (the AI and the risk check)
How to see it: `uv run python scripts/test_risk_modes.py`, `uv run python scripts/how_big_12h.py`, `uv run wx agent --shadow`
Proof it works:
- Four risk modes, each tested on 12-hour, 1-day, 3-day windows and the whole history, on three market sets (F53).
- A 20% gain in 12 hours has no support in the data (F52).
- The agent picks a mode each cycle with a tool and a skill. Code caps it after losses. Tests cover the choice, the cap and a bad answer.
- `uv run pytest` passed 156 tests.

Research: research files 01, 02 and 08: how NoFx, Vibe-Trading, Alpha Arena and TradingAgents let the AI size trades.
Questions: the user asked for rules that follow the trading time and are decided by the agent, not fixed in code.
Decisions: D41. Facts F52 to F54.

Shipped:
- `risk.py`: `RISK_MODES`, `mode_cap`. `brain.py`: the mode in the plan, `get_risk_modes`, candidates tagged with the modes that trade them. `skills/risk-modes.md`.

Not done yet:
- The AI gateway was down when this shipped (F54), so the mode choice has not run with the real model yet.
- A Wallex key that can trade.

Next change idea:
- Check the agent's first real mode choices when the gateway is back. Then go live.

### Change 26 — every liquid allowed market, a backtest bug fixed, the last 12 hours tested — 2026-10-22
Phase: 4 and 6
How to see it: `uv run wx agent --shadow`, `results/*.txt`
Proof it works:
- The agent looks at every allowed TMN market with enough volume, picked again each cycle (D42). A real cycle ran on 21 markets with no errors (F57).
- A backtest bug that bought one market twice is fixed, and every result was run again (F55). Changes are under 1 point.
- The rules on the last 12 hours: between -0.62% and +0.20% by mode; holding lost 0.33% (F56).
- `uv run pytest` passed 158 tests.

Research: none new.
Questions: the user asked for all allowed markets, and for a test on the last 12 hours.
Decisions: D42. Facts F55 to F57.

Shipped:
- `universe.py`. `features.LIVE_DAYS`: a new market downloads only what live features need. `wx agent` with no markets uses every liquid allowed TMN market.
- `backtest.setups_policy`: one buy per market.

Not done yet:
- A Wallex key that can trade. Then `wx order-test`, then `wx agent --live`.

Next change idea:
- Go live.

### Change 27 — the agent decides its trades; code keeps only the hard limits — 2026-10-22
Phase: 2, 3 and 4
How to see it: `uv run wx agent --shadow`, `uv run wx agent-replay --from results/replay_agent_v2.jsonl`
Proof it works:
- The trader proposes full trade plans (market, risk, stop, target, time limit, trend exit, maker or taker) and sells what it wants. Bull and bear argue its buys; a judge approves, reduces or rejects. Code keeps only the envelope (D43).
- New tools and skills from the installed trading skills: regimes, exit planning, sizing tiers, evidence, any allowed market on demand.
- A real shadow cycle ran: 9 tool calls in 25 s. The replay on 20 past moments: no failures; mostly no trades in a falling period (F58).
- `uv run pytest` passed 159 tests.

Research: the installed trading skills (regime-detection, exit-strategies, position-sizing, risk-management, strategy-framework) and research files 01, 02, 08, 12.
Questions: the user asked for agent decisions instead of fixed rules, for maximum profit, and for nothing outside the requirements (D44).
Decisions: D43, D44. Fact F58.

Not done yet:
- A Wallex key that can trade. Then `wx order-test`, then `wx agent --live`.
