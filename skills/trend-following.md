---
name: trend-following
description: Riding a confirmed uptrend (trend_strong). Why it is grade B over 12 hours, and when to take it.
---
# Trend following

## The idea
Buy while the 1-hour EMA 20 is above the EMA 50, and sell when it turns. Over 88 days this made money on 18
markets (F25). But much of that came from the Toman losing value (F36). Over a 12-hour window it was a coin
flip: positive in the 1st half of the history, negative in the 2nd (F41). So it is grade B, with half the risk.

## Confirmations that matter
- ADX above 25 and +DI above -DI: the trend has strength.
- The 4-hour trend agrees (`trend_4h_pct` above 0).
- BTCTMN is up over 24 hours, and the Toman is not getting stronger.

## Warning signs
- RSI above 75 and a 24-hour move above 3 typical days: a late, stretched entry.
- The book leans hard to the sell side and buyers are leaving (`sell_pressure`).

## Exit
Code sells when the EMA 20 falls under the EMA 50, at the stop, or before the end of trading.
