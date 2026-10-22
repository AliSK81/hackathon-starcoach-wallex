# Shadow trade log

Made with `uv run wx tradelog` on 2026-10-22 09:52 UTC. Fake orders only (Phase 3). Each row: when the order was placed, the setup, the size, the risk check's verdict, the AI's confidence and reason, and how it ended.

| Placed (UTC) | Market | Setup | TMN | Risk check | AI confidence | AI reason | Status | Exit | Result |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-22 01:35 | BTCTMN | trend | 1,250,000 | max per coin | 0.65 | Strong uptrend: ADX 47.5, +DI 34 vs -DI 17, EMA20 slope +0.83%. RSI 68.2 is near but not over 70. 24h move (4.24%) is ~3.8x typical (1.11%), somewhat stretched, but the trend is very strong and no overbought/illiquidity danger. vol_ratio 0.05 is quiet but zero_volume_hours is 0. | closed | stop | -2.83% |
| 2026-10-22 01:35 | ETHTMN | trend | 1,250,000 | max per coin | 0.55 | Trend active: ADX 32.1, EMA20 above EMA50 by 1.59%, slope +0.60%. RSI 56.9 neutral, no overbought risk. MACD hist -0.096 shows short-term momentum fading but the trend structure is intact. 24h move 3.46% is ~2.5x typical 1.37%, moderate stretch. | open | - | - |
| 2026-10-22 01:35 | XRPTMN | trend | 500,000 | max in coins | 0.60 | Solid uptrend: ADX 38.5, +DI 31 vs -DI 21, EMA20 slope +0.82%. RSI 60.2 has room. 24h move 4.49% is ~2.6x typical 1.71%. MACD hist -0.132 shows momentum cooling but trend structure is intact. No overbought or illiquidity danger. | open | - | - |
| 2026-10-22 07:15 | BTCTMN | trend | 1,210,148 | max in coins | 0.55 | Trend setup active (ema20_vs_ema50_pct +1.05, price +1.49% above EMA200). Pullback from 4.45% to 1.69% over last hours, RSI 44.6, ADX 35.7. No veto: spread 0.06%, 0 dead hours, BTC up 24h. Buying the dip within an intact uptrend. | open | - | - |
