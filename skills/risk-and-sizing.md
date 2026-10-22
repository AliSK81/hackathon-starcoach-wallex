---
name: risk-and-sizing
description: The risk rules code applies after you decide. What you control (conviction) and what you don't.
---
# Risk and sizing (code, not you)

Code applies these to every buy. You can't skip or loosen them, but you choose the risk mode (skill risk-modes),
and the mode sets the numbers below.
- A stop 4 ATR below the entry. The size is set so a stop, plus the round-trip cost, loses at most the mode's risk
  per trade (0.75% of equity, or 1.5% in aggressive).
- Defensive only: no buy where the usual 12-hour move is under 1.5 times the round-trip cost.
- At most 12 to 48 buys in 24 hours, by mode.
- Grade B setups risk half that, except in aggressive. Your conviction scales the risk again, from 0.5x (conviction 0) to 1.0x (conviction 1).
- At most 25% of equity in one coin and 60% in coins together (aggressive: 35% and 80%). Never all-in.
- No new buys after losing 2% in a day, or while equity is 6% below its peak.
- No new buys in the last 3 hours of trading. Everything is sold into Toman 30 minutes before the end.
- Data older than 5 minutes: no buy.

`check_order` shows what the risk check would do with a candidate, without ordering. `get_portfolio` shows the
limits in force, the drawdown and the buys so far.

What you control:
- Take or skip (with a checked veto) each candidate.
- Your conviction, which can only shrink an order.
- Selling a held position early, with a checked exit reason.
- Which candidate gets the free cash first: the highest conviction.
