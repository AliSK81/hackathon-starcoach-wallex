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
- [x] `wx features`: indicators for each market, from saved candles and the live order book.
- [x] `wx decide`: one AI decision from the indicators, checked and logged.
- [x] `wx run`: a loop that updates candles, computes indicators, asks the AI, and logs every cycle. It survives errors.
- [x] Results review. The AI said HOLD in every decision. The prompt asked for gains within a few hours, but over 4 hours prices usually move less than the round-trip cost. Fixed: the AI now judges over about a day (D20).
- [x] `wx replay`: ask the AI about past moments. Report how often it buys, and what happened in the next 24 hours after each BUY and each HOLD.
- [ ] Setups. The AI now buys 7% of the time, but its buys did no better than its holds (F18). Code flags the setups from F17, with their past results. The AI decides which to take. Every entry has a stop-loss in the test. `wx replay` compares the AI with taking every setup and with doing nothing.
