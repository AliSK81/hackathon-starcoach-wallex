# Wallex Official MCP Server

**Scope**: the official Wallex MCP endpoint, its tool surface and how our system should use it. · **Researched**: 2026-10-21
**Sources**: https://api.wallex.ir/llm.txt · https://wallex.ir/landing/mcp/ · live public calls to `https://api.wallex.ir/mcp` (`initialize`, `tools/list`; no API key, no orders) · full tool schemas saved in [wallex_mcp_tools.json](wallex_mcp_tools.json)

## TL;DR
- An **official** MCP exists: `https://api.wallex.ir/mcp`, **Streamable HTTP**, server name `api.wallex.ir` v1.0.0, protocol `2025-03-26`, `tools.listChanged=false`. Files 05, 08 and 12 said none existed; they only found community servers. The landing page links no GitHub repo.
- Auth: header `X-API-Key`. `initialize`, `tools/list` and public tools work without a key. Use a key **without withdrawal permission**; restrict allowed IPs if possible. WebSocket and withdrawals are not available through MCP.
- **52 tools**, in groups: basic (market data, balances, fees), spot (orders), margin (long/short positions), credit (prop-trading packages and sub-accounts), OTC. Tools that change state carry the prefix `STATE-CHANGING: requires explicit user confirmation` in their descriptions.
- Unauthenticated calls are rate-limited: response headers showed `x-ratelimit-limit: 5`. The limit for keyed calls is unknown.
- The page states no order caps, rate limits or fees. `llm.txt` says to treat https://developers.wallex.ir/ as authoritative for endpoint behavior.
- The MCP server itself enforces no size cap. Our own risk gate must sit between the LLM and any state-changing tool.

## Findings: tools relevant to us

**Market data (public)**
| Tool | Args |
|---|---|
| `wallex_basic_get_markets`, `wallex_spot_get_markets` | none |
| `wallex_basic_candle_history` | `symbol*, resolution*, from*, to*` |
| `wallex_basic_get_market_depth` | `symbol*` |
| `wallex_spot_get_depth` | none (all markets in one response) |
| `wallex_basic_get_latest_trades` | `symbol*` |

**Account (key required)**
| Tool | Args |
|---|---|
| `wallex_basic_get_account_balances` | none |
| `wallex_basic_get_account_fees` | none (maker/taker rate per market plus recent volume). This answers the open fee question once we have a key. |

**Spot orders (key required)**
| Tool | Args |
|---|---|
| `wallex_spot_post_account_orders` | `symbol*, side*, type*, quantity, price, stop_Price, client_id` |
| `wallex_spot_delete_orders_client` | `client_id*` (path form) |
| `wallex_spot_delete_account_orders` | `clientOrderId*` (body form) |
| `wallex_spot_get_open_order` | `symbol, page, per_page` |
| `wallex_spot_get_orders` | `market, type, side, page, per_page, from, to` |
| `wallex_spot_get_orders_client` | `client_id*` |

**Margin (key required).** Margin trading exists (long and short): `wallex_margin_open_position`, `_close_position_id`, `_edit_sltp`, `_edit_colateral`, `_get_positions`, `_get_pnl`, `_get_levels`, `_public_ratio`, `_calculate_loan`, `_detailed_information` (a dry-run calculation including stop-loss and take-profit).

**Credit / prop trading.** Prop-trading packages and sub-accounts (`wallex_credit_*`: package list, availability, activate/cancel, sub-account transfers). Not needed unless the organizers provide the competition account this way.

**OTC.** `wallex_otc_get_otc_price`, `wallex_otc_place_easy_trade_order`.

**Other tools we must never expose to the LLM:** bank IBAN and card tools, wallet deposit addresses, sub-account transfers, and all `credit_*` state-changing tools.

## Reusable for our system
- **Use the MCP for the LLM's read tools** (markets, depth, trades, candles, balances, fees) so the "Wallex MCP usage" is real and demonstrable to judges.
- **Do not hand the LLM the raw `wallex_spot_post_account_orders`.** Expose only our own `propose_order` tool (size bucket, not Toman amount), which passes the risk gate and then calls Wallex. This follows file 08's guarded-write pattern. A tool allowlist should block everything else in the 52 tools.
- Because the MCP descriptions say "requires explicit user confirmation", a fully automated bot must not rely on an interactive client's confirmation prompt. Our executor calls the order endpoint directly (REST `POST /v1/account/orders` or MCP), under our own gate, with a logged `decision_id`.
- Keep our thin REST client (file 05) for execution and polling, since it is deterministic and testable; use MCP for agent-facing reads.

## Recommended design decisions
1. Day 0: call `wallex_basic_get_account_fees` with the real key and write the result into the run manifest. Recompute all fee-dependent numbers (files 03, 06).
2. **Spot only, no leverage** (organizer rule). Never expose margin, credit or OTC tools. Tradable markets are all Wallex markets except [wallex_inactive_markets.txt](wallex_inactive_markets.txt); see 05 section 13.
3. Rate limit: unauthenticated MCP calls showed a limit of 5; poll REST market endpoints with caching, and keep the LLM's per-cycle tool calls few.
4. Store the key only in `.env` and the `X-API-Key` header; never in prompts, logs or tool arguments.

## Unverified / open questions
- The exact JSON shape of tool results. I did not call any tool beyond `initialize` and `tools/list`.
- Whether keyed MCP calls have a higher rate limit than 5.
