# Phase 1 — Read from Wallex

Goal: the bot reads real Wallex data, saves it, and knows the trading rules.

## Choices

- Public market data needs no key. Only balances and fees need the key.
- Use only the Python standard library for HTTP for now. Add a library when we need one.
- Saved data goes in `data/`. Git ignores it.
- The list of forbidden markets lives in the code package, so the bot can always find it.

## Checklist

- [x] `wx markets`: read all markets, keep only allowed ones, save a snapshot.
- [x] Trading rules per market (decimals, minimum size) are ready for later code.
- [x] Save candle history to disk for a few markets (1-minute and 1-hour).
- [x] A loop that reads live prices and logs them. It survives network errors.
- [x] With our key: read balances and fees. Write them in DECISIONS.md.
