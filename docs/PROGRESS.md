# Progress Log

[ROADMAP.md](ROADMAP.md) lists the phases. This file records what we actually did.

- Add one entry for every change that ships. Never write entries in advance.
- A "change" is the smallest step that still leaves the project working.
- Decisions that last longer than one change go in [DECISIONS.md](DECISIONS.md), not here.

## Status board

Update this after every change.

- **Current phase:** 1, in progress
- **Live trading:** not live yet
- **Version trading live:** none yet

### What we need from the team

| Item | Needed by | Status |
|---|---|---|
| Wallex key (read) in `.env` | Phase 1 | In `.env`. Not tested yet. |
| AI provider, model, URL, and key in `.env` | Phase 2 | In `.env`. Not tested yet. |
| A computer that can reach Wallex and the AI and run without stopping | Phase 3 | Unknown |
| Wallex key that can trade but **cannot** withdraw | Phase 4 | Waiting |
| Which account is the competition account | Phase 4 | Unknown |

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
