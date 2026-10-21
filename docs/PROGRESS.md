# Progress Log

[ROADMAP.md](ROADMAP.md) lists the phases. This file records what we actually did.

- Add one entry for every change that ships. Never write entries in advance.
- A "change" is the smallest step that still leaves the project working.
- Decisions that last longer than one change go in [DECISIONS.md](DECISIONS.md), not here.

## Status board

Update this after every change.

- **Current phase:** 1, not started
- **Live trading:** not live yet
- **Version trading live:** none yet

### What we need from the team

| Item | Needed by | Status |
|---|---|---|
| Wallex key (read) in `.env` | Phase 1 | We have one. It is not in `.env` yet. |
| AI provider, model, URL, and key in `.env` | Phase 2 | Waiting |
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
