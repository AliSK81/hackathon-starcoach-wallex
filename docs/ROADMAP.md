# Roadmap — Wallex Trading Engine

This file lists the phases of the project, in order. It says where we are going. It does not say how.

We do not design a phase before we start it. Research, questions, and design choices happen when a phase starts. They are recorded in [PROGRESS.md](PROGRESS.md).

Other files:
- [requirements.md](requirements.md): the hackathon rules.
- [DECISIONS.md](DECISIONS.md): decisions we already made, and facts we checked.
- [research/](research/00-index.md): old research. Use it as a reference. Check it is still true before you use it.

## Goal

Build a bot that trades on Wallex by itself. It must:
- read market data from Wallex;
- use AI to decide when to buy and sell, and explain why;
- pass every AI decision through a risk check written in normal code;
- place orders and track them reliably;
- log every decision, so judges can see no trade was manual;
- be tested on past data and on live data without money.

## Rules for every phase

1. **Go live first.** We earn profit and activity points only while the bot trades live. So live trading comes before the backtest and the write-up. Those happen while the bot trades.
2. **Always keep it working.** Every commit must run and be demoable. Build a thin version that works from start to end. Then improve it.
3. **Don't design ahead.** Only plan the phase you are starting.
4. **Plan a phase when you start it.** Before the first change in a phase, write a short plan in `docs/phases/phase-<N>-<name>.md`. A checklist is enough.
5. **For each change:** check the research, ask the user what only they can decide, build the smallest piece, ship it.
6. **Measure, don't guess.** Fees, order rules, and limits must come from the real Wallex API. Write them in DECISIONS.md before code depends on them.
7. **AI suggests, code decides.** Order size, limits, stop-loss, and the kill switch are normal code. The AI can never skip them.
8. **Log everything.** Log every cycle. This includes "do nothing" and "the AI said buy but the risk check said no".
9. **Tag the code that trades.** Every version that places real orders gets a git tag. The log records which version ran.
10. **Track progress in PROGRESS.md.** This file only shows phase status.

## Status

| Phase | Name | Stage | Status | Plan |
|---|---|---|---|---|
| 0 | Project setup | before live | not started | — |
| 1 | Read from Wallex | before live | not started | — |
| 2 | AI decides, no money | before live | not started | — |
| 3 | Risk check and fake orders | before live | not started | — |
| 4 | First real orders | before live | not started | — |
| 5 | Live trading | live | not started | — |
| 6 | Backtest | during live | not started | — |
| 7 | Docs for judges | during live | not started | — |

Status values: `not started`, `planned` (plan file exists), `in progress` (first change shipped), `done`.

### Which phase earns which points

| Judging item (points) | Phase |
|---|---|
| Profit (90) | 5 |
| Small losses / drawdown (30) | 3, 5 |
| Regular trading (15) | 5 |
| No errors or crashes (15) | 1, 4, 5 |
| Clear strategy (40) | 2, 7 |
| Real AI use (35) | 2, 6, 7 |
| Risk management (30) | 3 |
| Judges can re-run it (25) | 0, 6, 7 |
| Backtest and shadow test (20) | 3, 6 |
| Hard rules: allowed markets only, no manual trades | 3, 4, 5 |
| Deliverables: doc, trade log, tagged code | 2, 4, 7 |

---

## Phase 0 — Project setup

**Why:** We need a project that runs before we can add anything.

**Done when:**
- The project runs with one command.
- It needs no Wallex key and no AI key yet.
- Secrets go in a `.env` file that git ignores.

---

## Phase 1 — Read from Wallex

**Why:** Every later phase needs real market data. We also need real fees and order rules. Without them we can't know if a strategy makes money.

**Done when:**
- The bot reads live market data and logs it without crashing.
- It saves price history to disk, because Wallex keeps only limited history.
- With our key, we read our fees, balances, and market rules. We write them in DECISIONS.md.
- We have the list of allowed markets.

**Not yet:** decisions, orders.

---

## Phase 2 — AI decides, no money

**Why:** Judges give 35 points for real AI use. This is where the AI starts making real decisions.

**Done when:**
- Every cycle, the bot computes indicators from live data.
- The AI makes a decision and explains it using those indicators.
- Every decision is logged, including "do nothing".
- No orders of any kind.

**Not yet:** order size, risk limits, orders.

---

## Phase 3 — Risk check and fake orders

**Why:** This is where risk management and the hard rules live. Running it with fake orders on live data is our shadow test.

**Done when:**
- Every AI decision goes through a risk check. The check can approve, shrink, or reject it.
- The risk check can be tested without internet.
- Approved decisions become fake orders, filled at live prices.
- Every verdict and fake fill is logged.
- It ran alone through several cycles, with at least one rejection, and did not crash.

**Not yet:** real orders.

---

## Phase 4 — First real orders

**Why:** Now the bot trades real money, carefully. Some Wallex rules can only be learned with a real order.

**Done when:**
- The bot places one small real order, tracks it, and still knows about it after a restart.
- The kill switch works on the real account. It goes through the normal logged path.
- What we learned is written in DECISIONS.md.
- The code version is tagged in git.

**Not yet:** running alone without supervision.

---

## Phase 5 — Live trading

**Why:** This is what the judges score.

**Done when:**
- The bot traded live, and everything is logged.
- Restarts did not lose any order.

During this phase we only fix bugs. Each fix gets a new tag.

---

## Phase 6 — Backtest (during live trading)

**Why:** Judges give points for a backtest. It also shows whether the AI does better than simple rules.

**Done when:**
- Anyone can run the backtest from the repo and get a report.
- It uses the same log format as live trading.
- It compares the bot with a version that has no AI.

It can start after Phase 3. We decide then if a quick version should run before going live.

---

## Phase 7 — Docs for judges (during live trading)

**Why:** The rules require a written doc and a trade log.

**Done when:**
- A judge can understand and re-run the project using only the repo.
- The doc covers: architecture, AI and Wallex tool use, buy and sell rules, risk management, how to re-run.

---

## Later, only after live trading works

Do these only after Phase 5 is running:
- a second AI that reviews each entry;
- a machine-learning signal as extra input;
- a log that can't be edited without detection;
- saved AI answers, so re-runs are exact;
- automatic tests on every push (CI);
- Docker.
