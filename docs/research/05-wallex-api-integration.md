# Wallex API Integration (REST, WebSocket, MCP, community clients)

**Scope**: Everything needed to talk to Wallex from our trading engine: auth, endpoints, schemas, limits, markets/precision/min-notional, order types, WebSocket, MCP servers, ccxt, community clients. · **Researched**: 2026-10-21 · **Sources**:
- Official docs https://developers.wallex.ir/docs (all pages in `sitemap.xml` that matter were fetched: `create-api-key`, `basic-services-*`, `spot-*`, `socket-*`; Swagger JSON `/assets/files/spot-b9d06896d1009adc9ebc69b9a5495e7e.json` and `/assets/files/basic-services-89626420b5f06e4d7a2dc9206cdeb192.json`)
- LIVE public GET probes against `https://api.wallex.ir` on 2026-10-21 (no key, no orders): `/hector/web/v1/markets`, `/v1/markets`, `/v1/depth`, `/v1/trades`, `/v1/udf/history`, `/v1/all-fairPrice`
- `SajjadKiani/wallex-mcp-server@3b64501`, `mhsenpc/wallex_mcp_server@8a96c35`, `amiwrpremium/wallex-python@5e30e4f`, `ccxt/ccxt@51dfc97`
- Legend: **[DOC]** = stated in official docs/Swagger; **[LIVE]** = observed by me on a public GET today; **[CODE]** = read in a repo; **[?]** = not verified.

## TL;DR
- Base URL `https://api.wallex.ir`; auth = single header `x-api-key: <key>` (no HMAC, no nonce, no timestamp) **[DOC Swagger securityScheme ApiKeyAuth: in=header, name=x-api-key]**; JSON bodies with `Content-Type: application/json`. Max 3 API keys per account, each with an expiry date and read/trade/withdraw permissions; key is shown once **[DOC create-api-key]**. Create a key with trade permission and WITHOUT withdraw.
- Order placement is `POST /v1/account/orders` (types LIMIT, MARKET, STOP_LIMIT, STOP_MARKET); supports our own `client_id` (must be unique; documented charset: letters, digits, underscore), and order get/cancel are keyed by that `client_id` (`GET|DELETE /v1/account/orders/{client_id}`) -> gives idempotency and crash-recovery for free **[DOC]**.
- Only documented rate limit: **20 order-creations per 10 s** **[DOC spot-create-order]**; docs warn "frequent" `GET /v1/depth` and `GET /v1/trades` polling triggers rate limiting (no numbers) **[DOC]**. Use WebSocket for market data.
- Market data/candles are PUBLIC (no key needed) **[LIVE]** even though Swagger tags them as key-protected. `GET /v1/markets` (public, **[LIVE]**, not in the docs prose) returns the exact trading rules we need: `stepSize` (qty decimals), `tickSize` (price decimals), `minQty`, `minNotional` (**50,000 TMN on all 187 TMN markets; 1 USDT on all 186 USDT markets**).
- 373 spot markets: 187 TMN-quoted, 186 USDT-quoted **[LIVE]**. Liquid TMN markets by 24h TMN volume: USDTTMN, BTCTMN, ETHTMN, PEPETMN, XRPTMN, SOLTMN, DOGETMN, XAUTTMN, BNBTMN, TRXTMN. Whether all are "Wallex-approved" for the hackathon is **NOT stated anywhere** -> must confirm with organizers.
- Candle history (`GET /v1/udf/history`) is shallow and quirky: 1-min data only ~19 days back and `resolution=1` returns `no_data` for windows > ~36 h; hourly ~29 days; daily ~799 days **[LIVE]**. Backtest data must be collected/stored by us early (day 0).
- Private WebSocket (order/balance push) needs a JWT obtained with the **website login cookie** (`POST /v3/auth/token/refresh`), not the API key **[DOC]** -> for a bot, assume REST polling for order/balance state; use public WS for prices.
- Fee rates are NOT in docs; `GET /v1/account/fee` (needs key) returns `makerFeeRate/takerFeeRate` per symbol **[DOC]**. Fees are 2 legs per round trip: must be measured at startup (never hard-code).
- Wallex MCP: **official, Wallex-hosted** at `https://api.wallex.ir/mcp` (Streamable HTTP, header `X-API-Key`, 52 tools; details in [05c](05c-wallex-official-mcp.md)). Use it for the LLM's read tools. Execution still goes through our own thin client and risk gate, because the MCP enforces no order caps. The two community servers (`SajjadKiani/wallex-mcp-server`, `mhsenpc/wallex_mcp_server`) are superseded; the Python one is broken for ordering.
- ccxt has **no** Wallex exchange (no `wallex.ts`/`wallex.py` in repo) **[CODE]**.

## Findings

### 1. Endpoint catalogue (paths are relative to `https://api.wallex.ir`)

| Purpose | Method + path | Auth | Source |
|---|---|---|---|
| List markets + 24h stats + `amount_precision`/`price_precision` | `GET /hector/web/v1/markets` | none needed | [DOC basic-services-markets], [LIVE 200, 469 entries, `cache-control: max-age=30`] |
| **Trading rules per symbol** (stepSize, tickSize, minQty, minNotional, bid/ask stats) | `GET /v1/markets` -> `result.symbols{SYMBOL:{...}}` | none needed | [LIVE]; undocumented in prose |
| Order book (50 levels/side) | `GET /v1/depth?symbol=BTCTMN` | Swagger says key; works w/o | [DOC], [LIVE; `cache-control: max-age=1`] |
| All books | `GET /depth/all` | none | [DOC spot Swagger]; [LIVE returned HTTP 503 from nginx] |
| Recent trades | `GET /v1/trades?symbol=` | Swagger says key; works w/o | [DOC], [LIVE] |
| Candles (UDF) | `GET /v1/udf/history?symbol&resolution&from&to` | Swagger says key; works w/o | [DOC], [LIVE] |
| Fair prices (mid) of all markets | `GET /v1/all-fairPrice` | none | [DOC socket-fair-price], [LIVE] |
| Balances | `GET /v1/account/balances` | key | [DOC] ([LIVE no key -> 401 `{"code":1201,"message":"authorization header is missing"}`]) |
| Fee tier | `GET /v1/account/fee` | key | [DOC] |
| Place order | `POST /v1/account/orders` (HTTP 201) | key (trade perm) | [DOC] |
| Order detail | `GET /v1/account/orders/{client_id}` | key | [DOC] |
| Cancel order | `DELETE /v1/account/orders/{client_id}` or `DELETE /v1/account/orders` body `{"clientOrderId": "..."}` | key | [DOC Swagger both] |
| Open orders | `GET /v1/account/openOrders?symbol&page&per_page` | key | [DOC] |
| Order history | `GET /v1/account/orders?from&to&page&per_page&type&side&market` (`from/to` as `2024-10-01`) | key | [DOC] |
| Trade-credit sub-account order | same endpoints + header `sub-account-client-id` (separate API key per sub-account) | key | [DOC spot-intro] — not needed |

Docs state: all request bodies JSON; every request must carry `Content-Type: application/json`; responses JSON; data types use `number string` for decimals (e.g. `"13.78"`) and Unix seconds for timestamps **[DOC index]**. **Docs host mismatch**: Swagger says `host: api.wallex.com`; prose says only `api.wallex.ir`. Use `.ir` (all my probes worked there) **[DOC vs LIVE]**.

Not documented anywhere I could fetch: a server-time endpoint (`/v1/time` -> 404 **[LIVE]**), list of error codes, order-status enum, HTTP 429 body. Because there is no signature, clock skew does not matter for auth.

### 2. Auth
```
x-api-key: <API_KEY>
Content-Type: application/json
```
- Keys: created in web UI (login -> account menu -> API-Key page), fields: name, "active until", permissions (read default / trade / withdraw), SMS/OTP confirm; max **3 keys**; key displayed once; withdraw permission requires IP whitelist **[DOC create-api-key]**. Whether trade-permission keys are IP-restricted is **[?]**.
- Failure shapes seen: missing header -> HTTP 401 `{"code":1201,"message":"authorization header is missing","result":{},"success":false}`; bad key -> HTTP 401 `{"code":1201,"message":"invalid API key format",...}` **[LIVE]**.
- Envelope: success `{"result":{...},"message":"The operation was successful","success":true}`; error has extra top-level `code` (int) **[DOC Swagger `resources.ErrorResponse`: code, message, result, success]**. Status codes per Swagger for orders: 201/200 OK, 400 invalid params, 401 unauthorized, 422 validation, 404 (order detail).
- Community clients all use `X-API-Key` (case-insensitive HTTP header, same thing) **[CODE: wallex-mcp-server client.py:23; wallex_mcp_server client.go:188; wallex-python client.py:23]**.

### 3. Place order — `POST /v1/account/orders`
Request **[DOC spot-create-order]** (all values are strings):

| field | req | notes |
|---|---|---|
| `symbol` | yes | e.g. `USDTTMN`, `BTCTMN` |
| `side` | yes | `BUY` \| `SELL` |
| `type` | yes | `LIMIT` \| `MARKET` \| `STOP_LIMIT` \| `STOP_MARKET` |
| `price` | docs table says required "true" for all | for MARKET docs do not say what to send **[?]** — test with tiny order or send current price; confirm on first dry call |
| `quantity` | yes (table) | base-asset quantity. A quote-currency ("spend X TMN") market buy is NOT documented **[?]** |
| `stop_Price` (sic, capital P) | only STOP_* | Swagger confirms spelling `stop_Price` |
| `client_id` | optional | allowed chars "letters, underscore, digits"; if omitted server generates it; **must be unique else the order is not registered** **[DOC]**. Length limit unknown (the community MCP claims 36 **[CODE schemas.py, unverified]**). Real server-generated ids look like `LIMIT-e441b494-730d-11f1-...` (contain hyphens) **[DOC socket-private-channel example]**, so hyphens probably accepted though docs list only letters/_/digits **[?]** — use `[A-Za-z0-9_]` only. |

Example (body): `{"symbol":"BTCUSDT","side":"BUY","type":"LIMIT","price":"82494","quantity":"10","client_id":"test_clientId"}` (doc example values).

Response (HTTP 201), fields **[DOC]**: `message`, `success`, and `result`:
```json
{"active": true, "clientOrderId": "...", "created_at": "...", "executedPercent": 0,
 "executedPrice": "...", "executedQty": "...", "executedSum": "...", "fee": "...",
 "fills": [{"fee":"","feeAsset":"USDT","feeCoefficient":"","isBuyer":true,"makerFeeCoefficient":"",
            "price":"","quantity":"","sum":"","symbol":"","takerFeeCoefficient":"","timestamp":""}],
 "origQty": "...", "price": "...", "side": "BUY", "status": "NEW", "stopPrice": "",
 "stopPriceCondition": "", "sum": "...", "symbol": "...", "transactTime": 0,
 "type": "LIMIT", "updated_at": "..."}
```
(Swagger types: all strings except `active:bool`, `executedPercent:int`, `transactTime:int`.) `status` values mentioned in docs: "NEW, FILLED, CANCELED" (as examples, "مثلا"); WS shows `NEW`, `CANCELED` **[DOC]**. A full enum (PARTIALLY_FILLED? EXPIRED? REJECTED?) is **not documented** — the MCP `OrderStatus` enum (NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED) is a guess **[CODE schemas.py:~95, unverified]**. Our reconciler must treat unknown statuses defensively and derive state from `active` + `executedQty` vs `origQty`.

Rate limit: **max 20 order-creation requests per 10 seconds** **[DOC]**.

Order-type semantics **[DOC spot-types]**:
- LIMIT rests in book. Time-in-force / post-only / IOC parameters are **not exposed** (no field).
- MARKET executes immediately at best available prices, possibly several fills; **auto-cancelled if requested size exceeds book volume or would move last price by 2 %**.
- STOP_LIMIT / STOP_MARKET: order is not in the book until trigger; direction decided by stop vs last trade price at creation (`stopPriceCondition` field in response). Exchange-side stop-loss therefore exists (`STOP_MARKET`), but trigger-by-last-trade price on thin books is risky; detailed behaviour **[?]** — prefer engine-side stops with MARKET exit, optionally add exchange STOP_MARKET as a safety net only after testing.
- No OCO in docs (the community MCP lists `OCO` in an enum **[CODE]** — unsupported claim).

### 4. Order status / cancel / lists
- `GET /v1/account/orders/{client_id}` -> same `OrderResource` as above incl. `fills[]` with per-fill `fee`, `feeAsset`, `price`, `quantity`, `timestamp` **[DOC]**. This is our source of truth for realized price and fee.
- `DELETE /v1/account/orders/{client_id}` -> returns the order object (HTTP 200). Cancel is allowed while not FINISHED, including partially filled **[DOC spot-cancel-order]**.
- `GET /v1/account/openOrders` -> `result` is an object `{additionalProp1:[orders], ...}` keyed by (probably) symbol, not a flat list **[DOC schema OrderListResponseV1: result = map<string, array>]**. Parse accordingly; paginate (`page>=1`, `per_page>=1`; max per_page unknown **[?]**).
- `GET /v1/account/orders` filters: `market` (not `symbol`) **[DOC]**.

### 5. Balances
`GET /v1/account/balances` -> `result.balances{ASSET:{asset, faName, fiat, value, locked, is_dust, is_digital_gold, asset_png_icon, asset_svg_icon}}`; contains every listed coin (e.g. "1BBABYDOGE") so filter non-zero. `value` = total, `locked` = frozen in orders/withdrawal (so free = value - locked is my reading **[?]**). TMN balance key is `TMN` (WS example) **[DOC]**. `is_dust` flag exists (threshold undocumented).

### 6. Fees
- Endpoint `GET /v1/account/fee` -> `result{SYMBOL:{makerFeeRate, takerFeeRate, recent_days_sum}}` **[DOC]**. Fee actually charged per fill appears in `fills[].fee/feeAsset/feeCoefficient/makerFeeCoefficient/takerFeeCoefficient`; private WS `tradeDetails` has `feeAmount`, `feeCurrency`, `isMaker` **[DOC]**. Example `tradeDetails`: BUY 2 USDT on USDTTMN, `feeAmount: "0.003"`, `feeCurrency: "USDT"` (=0.15 % of 2 USDT) — **fee on BUY is charged in the received base asset in that example** (single sample; the 0.15 % figure is from the example only) **[DOC, inference]**.
- Public fee page (wallex.ir/fee -> redirect /commission) is client-rendered; I could not extract tier numbers. One news snippet claims 0.15 % for >5 B Toman volume users **[web search, unverified]**. Market flag `is_zero_fee` is true for only `USDSUSDT` **[LIVE]**; DOGE/SHIB zero-fee promos are temporary and not present today **[LIVE: only 1 zero-fee market]**.
- **Action**: at startup call `/v1/account/fee`, log it into the run manifest, and use `max(taker)*2 + spread` as the break-even hurdle in the strategy.

### 7. Markets, precision, min sizes (all [LIVE] snapshot 2026-10-21 ~19:05 UTC)
`GET /v1/markets` entry (XLMTMN) keys: `symbol, baseAsset, baseAssetPrecision(8), quoteAsset, quotePrecision(0), stepSize(1), tickSize(0), minQty(0.1), minNotional(50000), isZeroFee, isMarketTypeEnable, createdAt, stats{bidPrice, askPrice, lastPrice, 24h_ch, 7d_ch, 24h_volume, 24h_quoteVolume, 24h_tmnVolume, 24h_highPrice, 24h_lowPrice, bidVolume, askVolume, bidCount, askCount, direction, lastTradeSide, lastQty}`.
Interpretation (consistent with `/hector/web/v1/markets` where `amount_precision`/`price_precision` equal `stepSize`/`tickSize`): **`stepSize` = number of decimals allowed in quantity; `tickSize` = number of decimals allowed in price** (NOT increments). E.g. `BTCTMN: step 8, tick 0` -> qty up to 8 decimals, integer price in Toman; `PEPETMN: step 0, tick 4` -> integer qty, price with 4 decimals (price ~1.2372 TMN per PEPE) [LIVE; semantics inferred, **confirm with first real order**].

| Symbol | stepSize (qty dec.) | tickSize (price dec.) | minQty | minNotional | 24h TMN vol (B Toman) | top-of-book spread | depth within ±1 % (B Toman, ask/bid) |
|---|---|---|---|---|---|---|---|
| USDTTMN | 2 | 0 | 0.01 | 50,000 | 225.3 | 0.1 bps | 3.15 / 3.89 |
| BTCTMN | 8 | 0 | 1e-8 | 50,000 | 70.5 | 7.1 bps | 16.1 / 0.55 |
| ETHTMN | 5 | 0 | 1e-5 | 50,000 | 39.2 | 5.4 bps | 6.84 / 0.59 |
| PEPETMN | 0 | 4 | 1 | 50,000 | 99.3 | 5.7 bps | 0.24 / 0.14 |
| XRPTMN | 1 | 0 | 0.1 | 50,000 | 35.9 | 50.7 bps | 0.60 / 0.29 |
| SOLTMN | 5 | 0 | 1e-5 | 50,000 | 23.6 | 13.0 bps | 1.21 / 0.50 |
| DOGETMN | 1 | 0 | 0.1 | 50,000 | 20.5 | 30.6 bps | 0.29 / 0.24 |
| TRXTMN | 1 | 0 | 0.1 | 50,000 | 13.2 | 155 bps | 0.39 / 0.56 |
| ADATMN | 1 | 0 | 0.1 | 50,000 | 6.4 | 34.1 bps | 0.25 / 0.18 |
| BTCUSDT | 8 | 2 | 1e-8 | 1 (USDT) | (139.99 TMN-eq.) | 4.6 bps | 125k / 25k USDT |
Spread/depth computed from `GET /v1/depth` top-50 levels at one instant; stale/one-off, re-measure in the shadow phase. (`/v1/markets` `stats.bidPrice/askPrice` for XLMTMN showed a 1.6 % spread with `lastPrice` outside it — stats look partly stale; prefer `/v1/depth`.)

- With 5,000,000 TMN capital and min notional 50,000 TMN, a position can be 1 %–100 % of capital; all top-10 TMN books absorb 5 M TMN with <0.5 % impact except TRX/ADA/DOGE where spreads are 30–155 bps (avoid for short-term trading).
- Volume ranking by `quote_volume_24h` from `/hector/web/v1/markets` also shows non-standard markets (USOONTMN, XAUTTMN = tokenized gold, PUMPTMN flagged `flags:["isRisky"]`). `is_spot:true` is the documented test for spot tradability **[DOC spot-active-markets]**: 373 true.
- **Allowed-market list for the hackathon is unknown**; the markets endpoint shows what is tradable, not what is *permitted*. Flag to organizers; hard-code a whitelist config and fail closed.

### 8. Candles / history (for backtests and live features)
`GET /v1/udf/history?symbol=BTCTMN&resolution=60&from=<unix s>&to=<unix s>`; response `{"s":"ok","t":[..],"o":[..],"h":[..],"l":[..],"c":[..],"v":[..]}` (no-data: `{"s":"no_data"}`); numbers returned as strings **[DOC + LIVE]**. Docs list valid `resolution`: `1, 15, 60, 240, 480, 720, 1D, 2D, 3D`. **Observed** behaviour (USDTTMN/BTCTMN/ETHTMN/SOLTMN, today):
| requested | actually returned | max depth observed |
|---|---|---|
| `1` | 1-min candles but only if window <= ~36 h; 48 h+ window -> `no_data` | n/a |
| `15` | **1-min candles** (60 s spacing!) | ~26–27k bars ≈ 18–19 days |
| `60` | 1 h candles | ~696 bars ≈ 29 days |
| `240` / `480` / `720` | **1 h candles** (not 4/8/12 h) | 1439 bars ≈ 60 days |
| `1D` | daily | 799 bars (from 2024-08-14) |
=> Only `1`, `60`, `1D` behave like their names; build 5m/15m/4h bars ourselves by resampling 1-min/1-h data. Candle channel in WS exists for 1m/1h/1d. `mhsenpc` README claims 180/360 also valid **[CODE, unverified]**. Bars may be missing during no-trade minutes (gaps seen: one 180 s and 840 s gap in 27k bars) -> forward-fill.
Data-collection plan: pull and persist 1-min (in <=36 h chunks) + 1-h + 1-D for the shortlisted markets immediately; Wallex will not give us more than ~19 days of minute data later.

### 9. WebSocket (Centrifugo) [DOC socket-*]
- v2 (recommended): `wss://api.wallex.ir/connection/websocket` (no trailing slash -> 404). v1 (deprecated but working): `wss://api.wallex.ir/ws`, frames like `["subscribe",{"channel":"BTCTMN@trade"}]`.
- Public channels (no auth): `public:<SYMBOL>@trade`, `public:all@price`, `public:all@fairPrice`, `orderbook:<SYMBOL>@buyDepth`, `orderbook:<SYMBOL>@sellDepth`, `candle:<SYMBOL>@1m|1h|1d`. Channel name is case-sensitive; wrong text after `@` -> error 102, wrong text before `@` silently never delivers (!).
- Message payloads: trade `{isBuyOrder, quantity, price, timestamp(ISO)}` (`isBuyOrder=true` means the **maker** was the buyer); depth messages are **full snapshots** `[{quantity,price,sum},...]` (replace, not delta), first message arrives only on next change (no initial snapshot -> fetch `/v1/depth` first); candle push `{s,t[1],o,h,l,c,v}` strings, same `t` repeated while candle open (replace by `t`); candle channel keeps last 10 msgs / 2 min via `history`.
- Limits: 64 channels/connection (private counts), connection force-closed after **30 min** (v1 doc) so reconnect+resubscribe logic is mandatory, server ping every 25 s in v2 (client must answer `{}` within 8 s if no SDK), close codes 3000–3499 retryable, >=3500 not; messages missed during disconnects are lost for all non-candle channels; slow consumers dropped (3008) **[DOC]**. Official SDK: `centrifuge-python`.
- Private channel `private:user#<userId>` events `balanceUpdated`, `orderSaved`, `orderRemoved`, `tradeDetails{clientOrderID, feeAmount, feeCurrency, isMaker, price, quantity, side, sum, symbol}`; auth by JWT from `POST /v3/auth/token/refresh` which requires the **logged-in user cookie** (docs: bots must forge a `Cookie` header), token TTL 900 s. v1 uses `stream_key` obtained at login. **API-key-only access to the private stream is not documented** -> treat as unavailable; poll REST.
- Fallback for fair prices: `GET /v1/all-fairPrice` (call at start, re-call if no WS message for 60 s) **[DOC]**.

### 10. Account/market-wide risk features worth knowing
- `fair_price` block per market in `/hector/web/v1/markets`: `spot:{threshold:"4.00", max_acceptable_buy:"8.00", max_acceptable_sell:"8.00"}` (PEPETMN sample) — apparently limits on how far an order price may deviate from fair price (percent) **[LIVE; semantics unverified]**. Keep limit prices within ~±2 % of mid to be safe.
- `otc_*` fields (instant-trade market) with `otc_min_notional: 90000`, `otc_max_notional` exist; OTC could be an alternative for dust liquidation (`/docs/otc-*` pages exist, not read in depth) **[?]**.
- Margin, trade-credit, withdraw/IBAN endpoints exist; **out of scope and risky** (do not give the engine a withdraw-capable key).

### 11. Wallex MCP servers (official: see 05c; community servers below are superseded)
**Official MCP exists**: `https://api.wallex.ir/mcp` (source: `https://api.wallex.ir/llm.txt`, `https://wallex.ir/landing/mcp/`, and live `initialize` + `tools/list` calls). Tool list and usage: [05c-wallex-official-mcp.md](05c-wallex-official-mcp.md). The community servers below were found earlier by search and are kept only as reference for their (poor) code quality.

**A. `SajjadKiani/wallex-mcp-server@3b64501`** (Python, FastMCP, 2 stars; mcp.so listing "Wallex MCP Server") **[CODE]**
- Tools registered: `health` (server.py:8), `get_balance` (tools/balance.py:6), `get_markets` (tools/markets.py:6), `place_order(order: OrderRequest)` (tools/order.py:6), `get_order_status(order_id)` (order.py:18), `cancel_order(order_id)` (order.py:30). README lists "resources" (`wallex://market/{symbol}` etc.) that **do not exist** in the code (README structure mismatch).
- Config (`config.py`): env prefix `WALLEX_`: `WALLEX_API_KEY`, `WALLEX_BASE_URL` (default `https://api.wallex.ir/v1`), `WALLEX_HOST` 0.0.0.0, `WALLEX_PORT` 8000. Header `X-API-Key`. A fresh `httpx.AsyncClient` per tool call; timeout 10 s; no retry, no rate limiting.
- Bugs/gaps (verified by reading): (1) `place_order` does `order.get('order')` on a Pydantic model -> `AttributeError`, so ordering cannot work as written (tools/order.py:11); (2) body field is `client_order_id`/`clientOrderId`, but Wallex wants `client_id`; no `stop_Price` field; `OrderType` includes `OCO` which Wallex does not document; (3) `get_order_status` calls `GET /v1/orders/{id}` and `cancel_order` calls `DELETE /v1/orders/{id}` but real paths are `/v1/account/orders/{client_id}` (order.py:22,34) -> 404; (4) `Order` schema requires `orderId:int` and `origSum`, which Wallex responses do not contain (they use `clientOrderId`, `sum`) so parsing falls to bare `except` returning raw dict; (5) `get_markets` returns the whole 600 KB blob to the LLM (no filtering); (6) `get_balance` returns all ~370 assets including zeros; (7) `BalanceItem`/`MarketStats` schemas mark many fields required -> `ValidationError` string returned. Only `get_markets` and (probably) `get_balance` work.
- Only good use: as a reference for the tool-surface idea.

**B. `mhsenpc/wallex_mcp_server@8a96c35`** (Go, 0 stars) **[CODE]**: read-only; tools `get_account_balances` and `get_historical_data_ohlc(symbol,resolution,from,to)`; base `https://api.wallex.ir`; header `X-API-Key`; 15 s timeout; handles `s:"no_data"`. Correct paths (`/v1/account/balances`, `/v1/udf/history`) but cannot trade.

**C. Design lesson for the "AI uses Wallex tools" scoring item**: expose to the LLM agent only *read* tools (markets, depth, candles, balances, open orders) plus a single guarded `propose_order` that routes through our deterministic risk/execution layer; never let the LLM call raw place/cancel.

### 12. ccxt and community clients
- **ccxt@51dfc97**: `ls ts/src | grep -i wallex` and `ls python/ccxt | grep -i wallex` -> empty; no Wallex in README/exchanges.json (grep). So no unified driver; freqtrade/hummingbot/nautilus have no Wallex connector either (not checked individually, but they are ccxt/own-adapter based). We write a ~300-line client.
- **`amiwrpremium/wallex-python@5e30e4f`** (last commit 2022-08-17, `X-API-Key`, methods `place_order(symbol, order_type, side, quantity, price, client_id)`, `get_order_detail`, `cancel_order`, `get_open_orders`, `get_market_orders`) — targets the 2022 API (pre-redesign); low trust, schemas stale. Uses `requests`/`aiohttp` with a bare error handler (no retry).
- Other GitHub hits (not reviewed in depth, quality unverified): `MohZeh/WallexApi`, `beh11111/wallex-bot`, `zeotrix/Arbitrage` (Wallex vs Nobitex price diff), `PhinixHQ/wallex-new-api-docs` (2022). Treat all as unmaintained references.

### 13. Tradable universe (organizer rules, supplied by the team)
- **Spot only, no leverage.** Margin, short and credit/prop tools are out of scope.
- All Wallex markets are tradable except those in [wallex_inactive_markets.txt](../../src/wx/inactive_markets.txt) (345 entries in `BASE/QUOTE` form; the source heading says "credit account" but its sentence says "trading account", so treat the list as forbidden for the competition account, the conservative reading). Normalize by removing `/` to match Wallex symbols (`BTC/TMN` -> `BTCTMN`). 92 listed entries do not exist on `/v1/markets` today.
- Live check on 2026-10-21: of 373 spot markets, **120 remain tradable**. Most liquid tradable by 24h TMN volume: USDTTMN, BTCUSDT, ETHUSDT, PEPETMN, BTCTMN, PUMPTMN, USOONTMN, ETHTMN, XRPTMN, XAUTTMN, XRPUSDT, USOONUSDT, ARBTMN, BNBTMN, SOLTMN, XAUTUSDT, PEPEUSDT, DOGETMN, SOLUSDT, TRXTMN. BTC, ETH, XRP, SOL, PEPE, BNB, ARB and DOGE are not in the excluded list.
- Enforce as a hard allowlist in the risk gate: reject any symbol that is in the excluded file or missing from the live `/v1/markets` response. Re-fetch `/v1/markets` on startup, since the list may change.
- Source: pasted by the team from an organizer message (Telegram); the Telegram link is not fetchable.

## Reusable for our system
- `GET /v1/markets` -> build `MarketRules` cache (step/tick decimals, minQty, minNotional) refreshed every 10 min; use it for all rounding/validation (mirrors freqtrade `amount_to_precision`/ccxt `TRUNCATE` for qty, `ROUND` for price).
- `GET /v1/udf/history` fetcher with chunking (<=36 h for res 1), resampler, gap fill, and parquet/CSV cache for backtests; `data/` snapshot committed or reproducible via script (reproducibility score).
- Thin `WallexClient` (httpx) with: `x-api-key`, per-endpoint token buckets, JSON-envelope check (`success` + `code`), typed exceptions, request/response logging with redaction.
- Public WebSocket (centrifuge-python or raw frames with `{}` pong) for `public:<SYM>@trade`, `orderbook:<SYM>@buy/sellDepth`, `candle:<SYM>@1m`, auto-reconnect every <30 min, REST resync after each reconnect.
- `client_id`-keyed order endpoints = natural idempotency key (see 05b).
- Learnings from the community MCP code: Pydantic models must tolerate extra/missing fields (`extra="allow"`, optional everything) because the live schema differs from docs.

## Recommended design decisions for the hackathon (tied to scoring)
1. **Execution stability (15)**: single `WallexClient` class, all prices/qty as `Decimal` (API returns decimals as strings, e.g. `"250000.0000000000000000"`), never floats; `client_id = f"{RUN}_{seq:06d}"` with `[A-Za-z0-9_]` only (<=32 chars) to satisfy the documented charset. On timeout of `POST`, `GET /v1/account/orders/{client_id}`: found -> adopt it; 404 -> safe to re-POST with the same id (duplicates are rejected, so no double order). Details in 05b.
2. **Markets (hackathon constraint, 150-pt financial block)**: configurable `ALLOWED_SYMBOLS`; default shortlist `USDTTMN, BTCTMN, ETHTMN, SOLTMN, XRPTMN, PEPETMN` (liquidity table above) only after organizers confirm; refuse any other symbol in code (hard-constraint violation removes performance).
3. **Capital & risk (30)**: min order notional 50,000 TMN is trivial vs 5 M capital -> cap per-trade notional at e.g. <=20–25 % of equity (never all-in), max total exposure, daily loss kill-switch. Include fee: break-even move >= 2×taker fee + spread (spread tens of bps on mid-caps).
4. **Order types**: use LIMIT (marketable, priced at best opposite ±1–2 ticks, tight to mid) for entries to cap slippage; MARKET only for emergency/stop exits and final liquidation, remembering the 2 %/book-size auto-cancel rule. Do not depend on STOP_* until tested live with minimum size.
5. **Data**: start a collector on day 0 (1-min candles + depth snapshots + trades) for 3–5 shortlisted symbols; a backtest on <=19 days of 1-min bars is all that Wallex history will offer; document this limit in the README.
6. **Rate budget**: orders <=1 per 1 s sustained (limit is 20/10 s); public reads via WS; REST depth no faster than ~1 Hz per symbol with caching (`max-age=1` on server), global read bucket ~5 req/s; exponential backoff on 429/503 (observed nginx 503 on `/depth/all`).
7. **Private state via polling** (no cookie hack): `GET /v1/account/openOrders` + `GET /v1/account/balances` every 2–5 s while orders are live, else every 30 s; this is the reconciliation loop in 05b.
8. **AI usage**: give the LLM agent read-only Wallex tool wrappers (markets, candles, depth, balance) so "AI uses Wallex tools" is demonstrable; keep order submission behind deterministic risk checks and log every decision (decision-log file keyed by `client_id`).
9. **Startup self-test** (shadow mode, no orders): call `/v1/markets`, `/v1/depth`, `/v1/udf/history`, `/v1/account/balances`, `/v1/account/fee` with the real key and persist responses in the run manifest; fail fast on 401.
10. **Fee/ledger**: on every fill read `fills[].fee/feeAsset`; maintain our own ledger and compare to `GET /v1/account/balances` each loop; BUY fee may be taken in base asset, so quantity available to sell < executedQty.

## Unverified / open questions
- Which markets are "Wallex-approved/permitted" for the competition? (ask organizers; also whether USDT-quoted markets count and whether the final value is measured only in TMN).
- Result shapes of official MCP tool calls (only `initialize` and `tools/list` were called; see 05c).
- Maker/taker fee numbers for our account/tier; fee asset on BUY vs SELL; is a fee discount/zero-fee promo active for the competition account.
- MARKET order request format: is `price` required (docs table says yes)? Can a BUY MARKET be sized by quote amount? Max `client_id` length and whether `-` is accepted (server-generated ids contain hyphens).
- Full `status` enum (PARTIALLY_FILLED? EXPIRED? REJECTED?), HTTP/`code` list for insufficient balance, below-min-notional, bad precision, duplicate `client_id`, rate-limit (429?) — docs list none; capture them by deliberately provoking errors with tiny orders on day 1.
- Rate limits for read endpoints and per-key/IP quotas; is `GET /v1/account/balances` limited.
- Exact meaning of `stepSize`/`tickSize` (decimals vs increment) — inferred as decimal places; confirm with a first order.
- `fair_price.spot.threshold/max_acceptable_*` meaning (order-price band?).
- Do trade-permission keys require IP whitelist? Do API keys work on the private WebSocket? Is a competition sub-account used ("dedicated account")? If a trade-credit sub-account, `sub-account-client-id` header + separate key is required **[DOC spot-intro]**.
- Behaviour of `STOP_MARKET` in practice, `stopPriceCondition` values.
- `resolution=240/480/720` returning hourly bars and `resolution=1` failing for >36 h windows: server quirk or cap? (empirical only; might change).
- Dust handling: is a remaining base balance below 50,000 TMN counted in "final asset value" (requirement text says no coin holdings should remain).
- Whether `depth/all` 503 was transient.
