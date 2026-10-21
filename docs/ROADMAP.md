# Roadmap — Wallex Algorithmic Trading Engine

This is a roadmap, not a spec. It defines the big idea and the sequence of destinations toward it — nothing else. Research, questions, design decisions, and tool choices are **not** written down here: they get generated in the flow, one patch at a time, only when that patch is actually being worked on (see [docs/PROGRESS.md](PROGRESS.md)). Writing them now, for phases not yet started, would be exactly the upfront design this project is avoiding.

Prior exploratory research exists in [docs/research/](research/00-index.md). It is a resource bank to consult when a phase is actually picked up — not a source of pre-made answers, since time-sensitive things in it (API behavior, fees, market lists, available history) may have drifted.

## North star

An automated trading engine for the Wallex Algorithmic Trading Challenge ([docs/requirements.md](requirements.md)) that: reads Wallex market data, decides buy/sell algorithmically with a real, explainable AI contribution, never lets that AI decision bypass a deterministic risk/capital check, executes and tracks orders reliably, logs every decision so judges can tell it apart from manual trading, and can be proven correct on history and in a live-but-safe rehearsal before any real capital moves. Everything is measured against the two judging stages in requirements.md: financial performance and technical quality (strategy logic, real AI use, risk management, reproducibility, backtest/shadow evidence).

## Principles (apply at every phase)

- **Continuous delivery**: the system must always be in a releasable, demonstrable state. Never land a phase that breaks the previous one. Prefer the smallest vertical slice that is honestly end-to-end over a wide but half-finished layer. If you can't demo the repo at a given commit, that commit shouldn't exist.
- **No upfront design**: a phase's research, open questions, design decisions, and tool choices are discovered when that phase is picked up, not before. This file only ever names *what kind of thing* needs considering at each destination (research / questions / design / tools), never the content of it.
- **Phases get broken down when started, not before**: a phase here is a destination, not a short task — most of them are too big to ship as one patch. When a phase is picked up, *before any patch for it ships*, break it into sub-phases in this same minimal format (why / in scope / exit criteria / deferred) and save that breakdown as `docs/phases/phase-<N>-<slug>.md`. That breakdown happens then, scoped to the one phase being started — not written now for phases that haven't begun. This is also where the sharper, checklist-style exit criteria and explicit in-scope boundaries belong, instead of in this file.
- **Explore in the flow, every patch**: when a patch is picked up: (1) check [docs/research/](research/00-index.md) for anything relevant and sanity-check it still holds, (2) ask the user whatever is genuinely theirs to decide, right then, (3) design and build only the smallest slice needed, (4) ship it. Repeat per patch. Do not pre-answer step 2 or pre-decide step 3 for a patch that hasn't started.
- **Deterministic things stay deterministic**: as the system grows, keep a hard line between what the AI decides and what code enforces (sizing, caps, stops, kill switches). Don't let this line blur for convenience.
- **Log everything, from day one of having anything to log**: every decision cycle — including "did nothing" and "AI said yes but the gate said no" — should be traceable later.
- **Progress lives in [docs/PROGRESS.md](PROGRESS.md), not here**: this file tracks only which phase is current. What was actually researched, asked, decided, and shipped for each patch is recorded there, once, at the moment it ships.

## Status

| Phase | Theme | Status | Plan |
|---|---|---|---|
| 0 | Project skeleton & ways of working | not started | — |
| 1 | Talk to Wallex (read-only) | not started | — |
| 2 | Make sense of the market (features/signals, offline) | not started | — |
| 3 | First decision, no money on the line | not started | — |
| 4 | The gate that never trusts the AI | not started | — |
| 5 | Prove it on history (backtest) | not started | — |
| 6 | Prove it live, without money (shadow) | not started | — |
| 7 | Real orders, small blast radius first | not started | — |
| 8 | Let it run (the actual live window) | not started | — |
| 9 | Make it judge-able | not started | — |

Status values: `not started` -> `planned` (sub-phase plan exists in `docs/phases/`) -> `in progress` (at least one patch shipped) -> `done`. The `Plan` column links to `docs/phases/phase-<N>-<slug>.md` once it exists.

---

## Phase 0 — Project skeleton & ways of working

**Why**: nothing can be continuously delivered without a place to deliver it, and without a shared convention for what "releasable" means here.

**Exit / releasable when**: an empty-but-running scaffold exists; one trivial command proves the loop works without needing any Wallex or AI access yet.

---

## Phase 1 — Talk to Wallex (read-only)

**Why**: every later phase needs real market truth; this also seeds the "uses Wallex's tools" scoring angle.

**Exit / releasable when**: the system reliably fetches and logs live market state (and some history) continuously without crashing. Demoable as "it watches the market."

**Explicitly deferred**: any decision-making, any order.

---

## Phase 2 — Make sense of the market (features & signals, offline)

**Why**: strategy logic and real-AI-use scoring both need something worth reasoning over; this phase builds that substrate without risking anything.

**Exit / releasable when**: the system can compute and show features and candidate setups over historical and live data — no decisions made yet. Demoable as "it understands the market."

**Explicitly deferred**: letting anything decide to trade.

---

## Phase 3 — First decision, no money on the line

**Why**: this is where "AI genuinely drives decisions" becomes real or stays decoration — the single highest-leverage phase for the technical score.

**Exit / releasable when**: the system produces a logged, explainable decision every cycle, live, with zero financial risk. Demoable as "watch it think."

**Explicitly deferred**: sizing, risk limits, real orders.

---

## Phase 4 — The gate that never trusts the AI

**Why**: this is where risk/capital management, loss control, and the hard constraints (no all-in, no manual trades, etc.) actually live.

**Exit / releasable when**: every decision from Phase 3 passes through a gate that can approve/resize/reject it, every verdict is logged, and the gate is testable entirely offline.

**Explicitly deferred**: actually placing orders.

---

## Phase 5 — Prove it on history (backtest)

**Why**: direct evidence for the backtest/shadow and reproducibility scoring, and the cheapest place left to catch bugs before money is at risk.

**Exit / releasable when**: a backtest run anyone can reproduce from the repo produces a report with metrics, using the same decision-log format as live. Still fully offline and safe.

**Explicitly deferred**: live orders, real money.

---

## Phase 6 — Prove it live, without money (shadow)

**Why**: the second half of "backtest + shadow" evidence, and the last safety net before real capital is involved.

**Exit / releasable when**: the full pipeline runs live and continuously, against real market data, with simulated orders, using the same decision-log and reporting pipeline already built for backtest.

**Explicitly deferred**: real orders.

---

## Phase 7 — Real orders, small blast radius first

**Why**: this is the step that turns the system into an actual entrant, carefully.

**Exit / releasable when**: the system can place, track, and recover from a single small real order correctly and safely. A legitimate stopping point on its own — "a trading system" already exists here.

**Explicitly deferred**: running it unattended for the full window.

---

## Phase 8 — Let it run (the actual live window)

**Why**: this is the graded event itself — profit, loss control, activity, and execution stability are all measured here.

**Exit / releasable when**: the live run happened, is fully logged, and the account is left in a state consistent with the requirements by the time it's over.

**Explicitly deferred**: nothing — this is the deliverable.

---

## Phase 9 — Make it judge-able

**Why**: the required architecture/decision/risk-management write-up, the per-trade decision log, reproducibility, and the demo video are all explicit deliverables in requirements.md.

**Exit / releasable when**: a judge with only the repo and the video can understand, re-run, and verify the claims made.

---

## After that (only if time remains)

Things worth returning to once everything above is real, each deserving its own small phase if and when picked up: a second "critic" AI pass on entries, a learned signal model as an additional input, a tamper-evident/hash-chained decision log, CI, containerization, a richer evaluation/robustness suite. None of these block the core deliverable; don't start them before Phase 8 has run.
