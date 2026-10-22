---
name: toman-usdt-regime
description: The Toman against USDT. Why it moves every coin on Wallex, and how to read usdt_trend_up.
---
# The Toman regime

- Every coin on a TMN market is priced in Toman. When the Toman falls against the dollar, all coins rise in Toman.
- In the 120 saved days, USDTTMN rose 63% (F24). That drift carried much of the bot's trend profit (F36).
- `usdt_trend_up` true means USDTTMN's 1h EMA 20 is above its EMA 50: the Toman is weakening. Good for coin buyers.
- When it was false, coin trend buys did worse: -0.32% per 12 hours against +0.03% (F41).
- Holding USDT itself for 12 hours did not pay: the 0.5% round trip was larger than the drift (F41).
- Holding USDT for 20 hours: -0.16% on average, up in 41% of windows (F67). After USDTTMN already rose over 1.5% in 24 hours, the next 20 hours were -0.03% in the 1st half of the history and +0.46% in the 2nd half. Momentum in the Toman's fall is real some months and absent in others.
- Buying USDT is your choice, inside the same limits as any market. Do it only when you expect the Toman to fall more than the 0.51% round trip before you sell.
- USDTTMN goes quiet at night (F16). Many empty hours make it `illiquid`.
