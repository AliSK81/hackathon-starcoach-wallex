# Phase 2 — AI decides, no money

Goal: every cycle, the bot computes indicators from live data. The AI makes a decision and explains it. Every decision is logged. No orders.

## Choices

- The AI is any OpenAI-compatible API (D4). We call it with the Python standard library, like Wallex.
- Code computes every number. The AI does no maths. It reads the indicators, picks an action, and explains why.
- The AI answers in JSON. Code checks the answer. A bad answer becomes "do nothing", and the reason is logged.
- The AI names the indicators it used. Code checks that each name exists, and logs the real value next to it.
- Spot and long only. The AI can say buy, sell what we hold, or do nothing.
- No order size in this phase. That comes with the risk check in Phase 3.
- The AI never sees a key.

## Checklist

- [x] `wx ai`: one small call checks the AI settings. Write what we learn in DECISIONS.md.
- [ ] `wx features`: indicators for each market, from saved candles and the live order book.
- [ ] `wx decide`: one AI decision from the indicators, checked and logged.
- [ ] `wx run`: a loop that updates candles, computes indicators, asks the AI, and logs every cycle. It survives errors.
