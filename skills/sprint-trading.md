---
name: sprint-trading
description: Trading with less than a day left. Fast data, short holds, and what our tests found about scalping on Wallex.
---
# Sprint trading (under a day left)

You decide every 5 minutes. Read the fast features first (`ret_5m_pct`, `ret_30m_pct`, `ema9_vs_ema21_5m_pct`,
`rsi14_5m`, `bb_z_5m`, `atr14_5m_pct`, `vol_ratio_5m`, `vwap_4h_dev_pct`, `range_1h_pct`, `pos_in_1h_range`),
5 and 15-minute candles (`get_candles`) and the live book. Use 1-hour data only for context.

## What our tests on 1-minute data found (get_evidence `short_term`)
Standard fast strategies all lost money on Wallex after costs: 5-minute momentum, breakouts above the 1-hour high,
5-minute dip scalps and VWAP reversion. They lost 0.3% to 0.95% a trade, with profit factors of 0.05 to 0.73,
for every target, stop and hold we tried. The reason: a round trip costs about 0.55% plus the spread, and the moves
these signals catch are smaller. Many quick trades add up to a large loss.

## So, in sprint
- Speed is for timing, not for churning. Use fast data to enter a good trade at a better price and to exit
  quickly when it fails. Don't open a trade just because a fast signal fired.
- A trade needs a move of at least twice the cost: about 1.2% or more. Check `atr14_5m_pct`, `range_1h_pct` and
  `typical_24h_move_pct`: a market that moves 0.3% an hour will not give you 1.2% before the end.
- Prefer moves that are already strong on the 1-hour view (trend, regime) and are starting a new push on the
  5-minute view (`ema9_vs_ema21_5m_pct` turning up with `vol_ratio_5m` above 1.5).
- Plan short: `max_hours` within the time left, a target the market can reach, a stop just past the noise
  (2 to 3 times `atr14_5m_pct` x 3, at least 1%).
- Maker entries save fees but may not fill (they wait 10 minutes in sprint). Taker only when the move is starting now.
- Sell quickly when the reason is gone. A small loss is fine; a loss that grows into the end is not.
- With an hour or less left, only sell. Everything is sold 30 minutes before the end.
