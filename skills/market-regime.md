---
name: market-regime
description: Reading the market's regime (volatility, trend, Hurst) with get_regime, and which play fits each regime.
---
# Market regime

`get_regime(symbol)` returns the four-quadrant regime of the regime-detection skill:
- volatility: ATR percentile over 100 hours (low under 30%, high over 70%);
- trend: ADX over 25 is trending, under 20 is ranging, between is a transition;
- direction: from the EMA 20 slope and its place against the EMA 50;
- volume: last hour against the 20-hour average;
- Hurst exponent over 100 hours: under 0.4 the price reverts, over 0.6 it trends, near 0.5 it is random.

## Playbook
| Regime | Play |
|---|---|
| low or normal volatility, trending up | trend following, normal size, exit on the trend turn |
| high volatility, trending | momentum at half size, wider stop |
| quiet range | mean reversion: buy deep dips, target the average, time limit |
| high volatility range (choppy) | a quarter size or stay out |
| transition | small size or wait |

## In crypto (regime-detection skill)
- Regimes change fast: hours to days. Re-check each cycle.
- Volume confirms: a trend on high volume is real; a trend on low volume drifts.
- On Wallex, the Toman's own trend (`usdt_trend_up`) moves every coin. Read it with BTCTMN.
