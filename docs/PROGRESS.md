# Progress Log

[docs/ROADMAP.md](ROADMAP.md) defines the destinations. This file is the trail: one entry per shipped patch, written only when that patch ships — never ahead of it. A patch is the smallest change that leaves the system in a new, still-releasable state (see ROADMAP.md's continuous-delivery principle).

## How a session uses this file

1. Read [ROADMAP.md](ROADMAP.md)'s status table to see which phase is current.
2. If that phase has no sub-phase plan yet (no `docs/phases/phase-<N>-<slug>.md`), create one now, before shipping anything: break the phase into sub-phases using the roadmap's own minimal format (why / in scope / exit criteria / deferred) — no research/questions/design/tools content, same as the roadmap. Mark the phase `planned` in ROADMAP.md and link the file. This happens once per phase, not once per patch.
3. Read the most recent entry below (if any) for where things stand and its "Next smallest patch candidate," and the phase's sub-phase plan for which sub-phase is next.
4. Do the exploration for **only that next patch** — research, questions, design, tool choice — scoped to just it. Nothing further ahead. Ask the user in-flow whatever is genuinely theirs to decide; don't carry pre-made answers in from an earlier session.
5. Build and ship that patch, keeping the system demoable throughout.
6. Append a new entry below using the template. Never edit past entries except to correct a factual error (note the correction inline). Update ROADMAP.md's phase status table if a phase's state changed (e.g. first patch shipped -> `in progress`; last sub-phase done -> `done`). If a sub-phase was completed, note it in the phase's plan file too.
7. Stop. Do not start designing the patch after next, or the next phase's breakdown, ahead of time — that happens in its own turn, in its own flow, possibly in a future session.

If a session is asked to "continue toward the roadmap" with no further detail, this is the procedure: steps 1–7, for exactly one patch (plus step 2 if the phase has no plan yet).

## Entry template

```
### Patch N — <one-line summary of what shipped> — <date>
Phase: <roadmap phase this belongs to>
Release state: <how to see/run/demo it right now — e.g. the exact command>

Research:
- <what was actually checked/found for this patch; note if something from docs/research/ turned out stale>

Questions asked in-flow (and answers):
- Q: ... -> A: ...

Design decided (scoped to this patch only):
- <only what this patch needed; do not record decisions for future patches here>

Tools/choices made (scoped to this patch only):
- ...

What shipped:
- ...

Known gaps / explicitly not done yet:
- ...

Next smallest patch candidate:
- <a proposal, not a commitment — the next session re-explores before building it>
```

## Entries

_None yet. Phase 0 has not started._
