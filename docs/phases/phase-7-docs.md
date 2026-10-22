# Phase 7 — Docs for judges

Goal: a judge can understand and re-run the project using only the repo.

## Choices

- One document for judges: [STRATEGY.md](../STRATEGY.md). Short sentences. Every number points to a fact in DECISIONS.md.
- Saved evidence in `results/`, each file with the command that makes it.
- The per-trade decision log comes from `wx tradelog`.

## Checklist

- [x] Architecture, AI and Wallex use, buy and sell rules, risk management, how to re-run, results.
- [x] Honest limits: the Toman drift, 3-day windows, the AI roles that did not work.
- [ ] Update the results with the shadow and live trading numbers.
- [ ] The trade log from live trading.
