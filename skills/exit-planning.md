---
name: exit-planning
description: How to plan the exit of every buy (stop, target, time limit, trend turn, maker or taker), with what our tests found.
---
# Exit planning

Every buy carries its exit plan. Code follows it: the stop and the target are checked on the live price every
minute, the time limit and the trend turn at each cycle. You can also sell any position at any cycle.

## The parts
- `stop_pct` (always): where the idea is wrong. ATR-based is the standard: 2 to 4 times `atr14_pct`.
- `target_pct` (optional): sell when the price is this far above the entry. Our tests: fixed targets of 1.5%,
  2% and 3% did WORSE than no target on trend and dip trades, because they cut the big winners. Use a target only
  when you expect a bounded move (a dip back to its average), and set it near that average.
- `max_hours` (always): the longest hold. Dips: about 12 hours worked. Trends: let them run, but not past the end.
- `exit_on_trend_turn`: sell when the 1h EMA 20 falls under the EMA 50. Right for trend trades, wrong for dips.
- `order`: `maker` (a limit at the bid, cheaper, may not fill for up to an hour) or `taker` (fills now, costs
  about 0.05% more plus half the spread). Use taker only when the move is starting now.

## Rules of thumb (exit-strategies skill)
- Define the stop before the entry. Never move it away from the price.
- Trailing stops did worse than a fixed stop in our tests. Prefer the trend-turn exit for trends.
- Sell early only for a reason in the data: the thesis broke (your invalidation happened), sellers took over the
  book, or the whole market turned. A small loss alone is not a reason: dips often dip more first.
