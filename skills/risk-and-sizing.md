---
name: risk-and-sizing
description: How much to risk on a buy, how code turns your risk and stop into a size, and the hard limits you can't cross.
---
# Risk and sizing

## You choose
- `risk_pct`: the % of equity you accept to lose if the stop is hit, costs included. Tiers from the
  position-sizing skill: 0.5-1% for unproven or weak trades, 1-2% for good ones, 2-3% only for the best evidence.
- `stop_pct`: the stop distance under the entry. Wider than normal noise: about 2 to 4 times `atr14_pct`.
  A tighter stop gives a bigger size for the same risk, but gets hit more often.

## Code sizes it
Size = risk_pct of equity / (stop_pct + round-trip cost), then the smallest of:
- the room in one coin (40% of equity), the room in coins (80% of equity), free cash,
- half of the Toman resting within 1% on the ask side (what the book can take).
`check_order` shows the size and which limit set it. Nothing is ordered.

## Hard limits (envelope): code keeps these whatever you decide
- Risk per buy at most 3%. Stop between 1% and 15%. Hold at most 72 hours.
- At most 40% of equity in one coin, 80% in coins. Never all-in.
- No new buys after losing 4% in a day, or while 10% below the peak (for 24 hours).
- At most 60 buys in 24 hours. No buys on data older than 5 minutes.
- No new buys in the last 45 minutes. Everything is sold into Toman 30 minutes before the end.

## Drawdown response (risk-management skill)
- 0-5% below the peak: normal size.
- 5-10%: cut your risk by a quarter to a half.
- Near 10%: code stops new buys.
