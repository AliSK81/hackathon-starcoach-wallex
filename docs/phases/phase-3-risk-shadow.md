# Phase 3 — Risk check and fake orders

Goal: every AI decision goes through a risk check written in normal code. Approved buys become fake orders on live prices. This is our shadow test.

## Choices

- The risk check is `risk.py`. It sizes, shrinks or rejects each BUY, and names the rule that decided (D25).
- One function, `trade()` in `trades.py`, decides fills, stops, exits and costs. The backtest, the replay, the study and the shadow book all use it, so they can't disagree (D28).
- Fake orders are limit buys at the bid. They fill only if the price trades below the bid within an hour (D26).
- The shadow book is one JSON file. A restart loses nothing.
- No real order is placed in this phase.

## Checklist

- [x] Risk check with the D6 limits, a daily-loss halt, a drawdown halt that ends after a day, and a stale-data check. Tested without internet.
- [x] Portfolio backtest that uses the risk check (`wx backtest`).
- [x] Shadow book with fake limit orders (`wx run --shadow`). Tested without internet.
- [x] Each setup has its own exit rule. Trading is trend-only (D29).
- [x] The shadow book runs alone for several cycles, with fills, exits and at least one rejection, and does not crash. 40 cycles, 4 fills, 1 stop, 74 rejections, no crash (change 21).
- [x] Results review (ROADMAP rule 11): the stop-out came out exactly as `trade()` models it (F39). The checked veto does not make results worse (F31, F33). Both AI failures held every market, and their causes are fixed (F37, F39).
