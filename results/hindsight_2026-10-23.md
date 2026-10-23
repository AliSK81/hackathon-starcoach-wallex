# What would have earned most since the live start (2026-10-22 18:47 UTC to 2026-10-23 07:25 UTC)

Prices from the saved 1-minute candles; features from the agent's own decision records at the time (what it saw then).
Every allocation: 5 coins at 20% of the account each (our limit in one coin), held to now, 0.75% round-trip cost.
USDT left out (halted).

## Coins since the start, best first (before costs)

| Coin | Return | | Coin | Return |
|---|---|---|---|---|
| PEPE | +4.17% | | SHIB | +2.05% |
| FIL | +3.42% | | DOGE | +1.78% |
| SUI | +3.05% | | XRP | +1.55% |
| UNI | +2.98% | | USOON | +1.29% |
| APE | +2.41% | | BNB | +1.09% |
| LTC | +2.14% | | S | +1.08% |
| | | | TRX | +0.25% |
| | | | XAUT | -0.70% |

Joined the list at 20:47 (from then): DOT +7.06%, BCH +4.00%, PENGU +3.26%, FLOKI +3.20%, AAVE +2.86%, AVAX +2.77%.
Average coin since 18:47: +1.52%.

## Results with the whole account

| Way to choose (at that moment) | From 18:47 | From 20:47 | From 23:01 |
|---|---|---|---|
| Perfect hindsight: the 5 best coins | +2.46% | +2.93% | - |
| Volatile and fallen: move_x_cost >= 2.5, lowest rsi14 | **+1.58%** | +1.38% | +1.42% |
| Volatile and fallen: move_x_cost >= 2.5, lowest zscore_48h | +0.98% | **+1.48%** | **+1.63%** |
| Lowest zscore_48h (most fallen vs 48 h) | +1.65% | +1.70% | - |
| Highest typical_24h_move_pct (moves most) | +1.35% | +1.46% | - |
| Every coin equally, 80% invested | +0.62% | +0.96% | - |
| Highest rsi14 / bb_z_20 / ret_24h (already risen most) | **-0.40%** | -0.18% | - |
| What the agent did | about +0.07% | | |

## The volatile, fallen coins at 18:47 (move_x_cost >= 2.5, lowest rsi14)

| Coin | 20% of the account | What it did | move_x_cost | rsi14 | zscore_48h | 24 h before | Regime |
|---|---|---|---|---|---|---|---|
| APE | 1,000,000 TMN | +2.41% | 3.4 | 34.7 | -1.64 | -7.65% | transition |
| S | 1,000,000 TMN | +1.32% | 3.3 | 36.1 | -1.55 | -7.62% | range |
| PUMP | 1,000,000 TMN | +0.32% | 5.1 | 37.3 | -0.89 | -7.14% | transition |
| FIL | 1,000,000 TMN | +3.42% | 3.0 | 39.0 | -1.40 | -9.15% | transition |
| PEPE | 1,000,000 TMN | +4.17% | 4.3 | 45.8 | -0.35 | -3.67% | range |

## What it shows

- The coins that made the most last night were mostly coins that moved a lot and had fallen the day before
  (down 4 to 9% in 24 hours, RSI 35 to 46, under their 48-hour average). In a market that turned up, they
  bounced hardest.
- Buying the coins that had already risen most (highest RSI, most stretched, biggest 24-hour gain) was the
  worst choice, below zero after costs. The 120-day test (F78) found the same for momentum buys.
- This agrees with our earlier tests: dips on coins that move a lot (`stretched_dip`, `capitulation`,
  `dip_toman_weak`) were the setups positive in both halves (F41).
- One night is one sample. It shows what worked in this market tonight, not a guarantee.

Made with the agent's decision records (`data/live/decisions/`) and the 1-minute candles (`data/candles/`).
