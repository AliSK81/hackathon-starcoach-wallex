# Phase 4 — First real orders

Plan:
- [x] Wallex order client: place, read, cancel by our own `client_id` (`orders.py`).
- [x] Live executor with the same methods as the shadow book (`live.py`): limit buys at the bid, sells that fill at once, a guard for stops, a book that survives a restart.
- [x] Kill switch: `wx kill`.
- [x] Sell everything into Toman before the end of trading (`--end-at`).
- [x] Tests with a fake Wallex (`tests/test_live.py`).
- [x] A Wallex key in `.env` (5,000,000 TMN, nothing else). Whether it can trade shows in `wx order-test`.
- [x] The kill switch knows every allowed TMN market. Live decisions have their own log (D46).
- [ ] `wx order-test`: one real order that can't fill, read back and cancelled. Write what we learn in DECISIONS.md.
- [x] Tag the version that trades: `live-1`.
- [ ] Start `wx agent --live` under the supervisor (Phase 5).
