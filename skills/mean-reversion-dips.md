---
name: mean-reversion-dips
description: Buying deep dips (capitulation, stretched_dip, dip_toman_weak). When a dip is a chance and when it is a falling knife.
---
# Mean reversion: deep dips

## The idea
After a fast, deep fall, sellers are often exhausted. Price tends to win back part of the fall within 12 hours.
In our 120 days of data, deep dips (RSI under 25 and 2 standard deviations under the 20-hour average) beat the
costs in both halves, and on markets not used to pick them (F41). They are rare: about one a day across all markets.

## Good signs
- The fall came fast, in a few hours, not as a slow slide for days.
- Volume rose in the fall (`vol_ratio_20` above 1.5): a flush, not a quiet bleed.
- The book has buyers near the price (`imbalance_1pct` near 0 or above).
- The 15-minute RSI (`rsi14_15m`) is turning up: the selling is slowing.
- The Toman is weakening (`usdt_trend_up` true). Coins tend to recover faster then.

## Falling knife: warning signs
- BTCTMN is down 5% or more in 24 hours: the whole market is falling.
- Sellers keep hitting the bid: `buy_share` under 0.35 and `imbalance_1pct` under -0.3.
- The market is empty: many hours with no trades, or a wide spread.

## Exit
A time limit of about 12 hours worked in our tests, with a stop near 4 ATR. A target at the 20-hour average is
reasonable. Don't sell early just because it is down a little: a dip often dips more before it turns.
