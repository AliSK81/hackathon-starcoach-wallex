---
name: session-end
description: Trading against a deadline. How hours_left changes what is worth doing.
---
# Trading to a deadline

- The result is counted in Toman at the end. Coins are sold before it, and that sale costs fees and spread.
- `hours_left` is the time to the end. A dip setup needs up to 12 hours. A buy with 4 hours left has less time to work.
- With under 3 hours left, code blocks new buys. With under 30 minutes left, code sells everything.
- With little time left, a position in profit is worth keeping only if its reason still holds.
  The exit reason `take_profit` (net gain above 1%) is allowed at any time.
- Don't chase. A missed trade costs nothing. A bad trade near the end has no time to recover.
