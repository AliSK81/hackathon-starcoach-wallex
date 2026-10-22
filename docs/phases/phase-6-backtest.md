# Phase 6 — Backtest

Goal: anyone can run the backtest from the repo and get a report. It compares the bot with a version that has no AI.

## Choices

- Rules-only backtest: `wx backtest`. The AI can't be run on every past hour (cost, time), so the AI is tested on sampled past moments: `wx replay`.
- Both use `trade()` and the same risk check as shadow trading (D28).
- Fixed spreads, so a re-run on the same candles gives the same numbers (F30).
- Out of sample: 12 markets that were not used to pick the strategy (F25).

## Checklist

- [x] `wx backtest`: policies, taker and limit orders, whole history, each half, 3-day windows.
- [x] `wx study`: each setup on its own, with several stops.
- [x] `wx replay`: the AI on past moments against the same rules without the AI, for each AI role.
- [x] Saved outputs in `results/`, with the commands that make them.
- [ ] A replay of the final AI role (`agent`) on the same moments.
