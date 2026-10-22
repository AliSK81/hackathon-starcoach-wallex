# Phase 5 — Live trading

Goal: the bot trades real money alone for 24 hours, and every decision and order is logged.

## Choices

- One run of 24 hours, ending 2026-10-23 18:00 UTC (D46). Sprint pace (D45).
- `scripts/keep_running.py --live` restarts the agent after any stop. The book, the orders and the memory are on disk.
- Live decisions: `data/live/decisions/`. Orders: `data/live/orders.jsonl`. Output: `data/brain/live_run.log`.
- During the run we only fix bugs. Each fix gets a new tag.
- The kill switch: `wx kill`, or a file `data/KILL`.

## Checklist

- [ ] `wx order-test`: a real order is placed, read back and cancelled.
- [ ] The live run starts on a tagged version.
- [ ] Checks during the run: `wx live`, `wx verify-log --live`, `data/brain/live_run.log`.
- [ ] Restarts lost no order (the book matches Wallex).
- [ ] At the end: everything in Toman, `wx tradelog --live > results/trade_log_live.md`, results in STRATEGY.md.
