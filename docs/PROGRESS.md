# Progress Log

[ROADMAP.md](ROADMAP.md) lists the phases. This file records what we actually did.

- Add one entry for every change that ships. Never write entries in advance.
- A "change" is the smallest step that still leaves the project working.
- Decisions that last longer than one change go in [DECISIONS.md](DECISIONS.md), not here.

## Status board

Update this after every change.

- **Current phase:** 2, not started (Phase 1 done)
- **Live trading:** not live yet
- **Version trading live:** none yet

### What we need from the team

| Item | Needed by | Status |
|---|---|---|
| Wallex key (read) in `.env` | Phase 1 | Works (F1). |
| AI provider, model, URL, and key in `.env` | Phase 2 | In `.env`. Not tested yet. |
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
