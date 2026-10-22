---
name: order-book-and-flow
description: Reading the Wallex order book and the latest trades (from the Wallex MCP server). Depth, imbalance, buy share.
---
# Order book and trade flow

`get_orderbook(symbol)` reads the live book and the last 50 trades from the Wallex MCP server.

## The numbers
- `spread_pct`: the gap between best ask and best bid. Above 0.5% is expensive.
- `bid_tmn_within_1pct`, `ask_tmn_within_1pct`: Toman resting within 1% of the price, per side.
- `imbalance_1pct`: (bids - asks) / (bids + asks). +1 is all bids, -1 is all asks.
- `buy_share`: the share of traded Toman where the buyer hit the ask. Above 0.6 buyers push. Under 0.4 sellers push.
- `trades_per_min`: how alive the market is.
- `buy_500k_cost_pct`, `buy_1250k_cost_pct`: how far from the mid our order would fill on average. Add it to the cost.

## How to use it
- Big walls on Wallex are often market makers. One side 5 times the other is normal on BTCTMN. Don't overreact.
- Sell pressure is real only when both hold: `buy_share` under 0.35 and `imbalance_1pct` under -0.3.
  Then wait, or skip the buy.
- Thin book: if `bid_tmn_within_1pct` is smaller than our order, we may not exit well. Say so.
- For a dip buy, sellers fading (buy_share rising across cycles) is a good sign.
