---
name: risk-and-sizing
description: The risk rules code applies after you decide. What you control (conviction) and what you don't.
---
# Risk and sizing (code, not you)

Code applies these to every buy. You can't skip or loosen them.
- A stop 4 ATR below the entry. The size is set so a stop loses at most 0.75% of equity.
- Grade B setups risk half that. Your conviction scales the risk again, from 0.5x (conviction 0) to 1.0x (conviction 1).
- At most 25% of equity in one coin, and 60% in coins together.
- No new buys after losing 2% in a day, or while equity is 6% below its peak.
- No new buys in the last 3 hours of trading. Everything is sold into Toman 30 minutes before the end.
- Data older than 5 minutes: no buy.

What you control:
- Take or skip (with a checked veto) each candidate.
- Your conviction, which can only shrink an order.
- Selling a held position early, with a checked exit reason.
- Which candidate gets the free cash first: the highest conviction.
