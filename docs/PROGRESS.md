# Progress Log

[ROADMAP.md](ROADMAP.md) lists the phases. This file records what we actually did.

- Add one entry for every change that ships. Never write entries in advance.
- A "change" is the smallest step that still leaves the project working.
- Decisions that last longer than one change go in [DECISIONS.md](DECISIONS.md), not here.

## Status board

Update this after every change.

- **Current phase:** 2, reopened (see change 12)
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
