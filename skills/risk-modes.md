---
name: risk-modes
description: How to choose the risk mode each cycle (defensive, normal, active, aggressive), by the time left, our result, the market and the evidence.
---
# Choosing the risk mode

You choose the mode every cycle. Code then trades the setups of that mode with its limits. Code always keeps the
stop-loss, the caps per coin and in coins, and the end-of-trading sale. After losses (4% below the peak, or 1.5%
down today) code allows at most `normal`.

## What each mode did (our 6 markets, `get_risk_modes` has the numbers)
- Over 12 hours, every mode lost a little on average. More aggressive modes ended up more often (14% of windows
  for defensive, 36% for aggressive) but had deeper worst windows (-1.4% against -4.2%).
- Over 3 days, aggressive did best on average (+0.73%), and ended at +5% or more in 15% of windows.
- Over 89 days, aggressive made +42.5% with a 15% drawdown. Without the Toman drift (USDT markets) it lost 5.4%.
- The best 12-hour window in any mode was under +5% on our markets. Large gains need days, not hours.

## How the result is scored
- Profit (90 points) is ranked among teams, and a loss scores 0. Ending above the start matters most.
- Loss control (30 points) rewards a small drawdown. Activity (15 points) rewards regular trading.

## How traders think about it (researched agents: NoFx, Vibe-Trading, Alpha Arena)
- Size follows conviction and evidence, inside hard caps. The models that lost most in Alpha Arena were the ones
  that used the most leverage, concentrated in one direction and traded the most.
- Protect a gain: when we are ahead and little time is left, a defensive mode keeps the gain.
- Behind with time left: a more active mode gives more chances to end up, at the price of a deeper worst case.
- A strong, broad market (BTC up, the Toman weakening, many trends) supports active or aggressive.
  A falling or quiet market supports defensive or normal.
- Many hours left: more aggressive modes have had time to work in the past. Few hours left: costs dominate.

Say in `mode_reason` which of these you weighed. Change mode when the facts change, not every cycle.
