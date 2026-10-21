# Per-Trade Decision Logging, Tamper-Evidence and Replay

**Scope**: how existing repos log LLM trading decisions, and a concrete JSONL + hash-chain + record/replay design that proves "algorithmic, not manual" to Wallex judges. · **Researched**: 2026-10-21
**Repos+commits** (read-only): `NoFxAiOS/nofx@4a5e9ac` (AGPL-3.0), `HammerGPT/Hyper-Alpha-Arena@9bdf62d` (Apache-2.0), `alsk1992/CloddsBot@c930628` (MIT), `TauricResearch/TradingAgents@e8f5503` (Apache-2.0), `HKUDS/Vibe-Trading@9081946` (MIT), `nautechsystems/nautilus_trader@e88439b` (LGPL-3.0).

## TL;DR
- **No surveyed repo has hash-chained decision logs.** CloddsBot hashes each record independently (SHA-256) and can anchor hashes on-chain; NautilusTrader's own docs say its event store "does not yet define redaction, encryption-at-rest, or tamper evidence". A prev-hash chain is therefore cheap differentiation (reproducibility 25 pts, "manual trades identifiable").
- Best existing shape for *reasoning storage* is NoFx's `DecisionRecordDB` (system_prompt, input_prompt, cot_trace, raw_response, decision_json, execution_log, account/position snapshots, ai_request_duration_ms) and HAA's `AIDecisionLog` (prompt_snapshot, reasoning_snapshot, decision_snapshot + exchange order ids + realized_pnl). Neither stores a **market-data snapshot or hash**, a **risk-gate verdict**, or **fees**: those are the gaps we fill.
- Best existing *durability* pattern: Vibe-Trading `TraceWriter` (append-only `trace.jsonl`, flush + `os.fsync` per record, large blobs to sidecar files written *before* the referencing record, `agent/src/agent/trace.py`).
- Best existing *run summary* pattern: Vibe-Trading `write_run_card` (config hash, strategy file hash, per-artifact sha256, data sources, schema_version, `run_card.json` + `.md`, `agent/backtest/run_card.py:168`).
- Best existing *replay/audit* idea: NautilusTrader event sourcing: per-run monotonically increasing `seq`, correlation/causation headers, `RunStarted`/`RunEnded` entries, sealed manifest, read-only verifier, fed by commands + raw venue reports (`docs/concepts/event_sourcing.md`).
- **Replayability recipe**: record (a) market snapshots (or a hash + the raw candles/orderbook file), (b) exact prompt + model params, (c) raw LLM response. Replay mode swaps the LLM client for a "recorded-response" client keyed by `prompt_hash`; deterministic code (features, gate, sizing) must reproduce identical parsed decisions and orders.
- Log **every cycle including HOLD and gate-rejected decisions** (HAA records holds; kojott/LLM-trader-test records unrealised PnL/fees on holds). Judges see activity regularity and that rejections come from rules.
- A single, small `verify_log.py` (hash chain + schema + recompute-features + gate re-evaluation) is the strongest artefact for "judges re-run the code".

## Findings

### How existing repos log
| Repo | Store | What is stored per decision | Missing for our purpose |
|---|---|---|---|
| NoFx | GORM SQL, `store/decision.go:13-30` `DecisionRecordDB` | `trader_id, cycle_number, timestamp, system_prompt, input_prompt, cot_trace, decision_json, raw_response, candidate_coins, execution_log, decisions[], success, error_message, ai_request_duration_ms`; `DecisionAction` adds `action, symbol, quantity, leverage, price, stop_loss, take_profit, confidence, reasoning, order_id, success, error`; `AccountSnapshot`, `PositionSnapshot` (mark, entry, liq price) | no market snapshot/hash, no gate verdict object (only free-text `execution_log`), no model name/params, mutable DB rows, no hash |
| NoFx orders | `trader/auto_trader_decision.go:285 recordAndConfirmOrder`, `createOrderRecord` (l.451), `recordOrderFill` (l.500, with `fee`) | order id, fill price/qty/fee, position change | link from decision -> order is by `order_id` only |
| HAA | SQL `ai_decision_logs` (`database/models.py:331`) | `decision_time, reason(<=1000), operation, symbol, prev_portion, target_portion, total_balance, executed, order_id, prompt_snapshot, reasoning_snapshot, decision_snapshot, hyperliquid_order_id, tp_order_id, sl_order_id, realized_pnl, prompt_template_id, signal_trigger_id, wallet_address, hyperliquid_environment(testnet/mainnet/null=paper)` | no market data, no verdict, no hash; also broadcasts via WebSocket and Telegram |
| CloddsBot | SQLite `trade_ledger` + `ledger_constraints` (`src/ledger/storage.ts:33-70`) | `DecisionRecord` (`ledger/types.ts`): `inputs, analysis{observations, factors, alternativesConsidered, modelUsed}, constraints[]{type,rule,threshold,actual,passed,violation}, confidence, decision(approved/rejected/skipped/blocked/executed/failed), reason, outcome{orderId, filledSize, avgPrice, pnl, error}, hash, anchorTx` | per-record hash only, no chain; hash scope excludes `outcome`; see bug note below |
| TradingAgents | `tradingagents/graph/trading_graph.py:437 _log_state` -> `full_states_log_<date>.json` (analyst reports, bull/bear and risk-debate histories, `trader_investment_plan`, `final_trade_decision`, `final_rating`, `run_settings()` allowlist: version, provider, models, analysts, debate rounds, data vendors) | rich reasoning transcript per run | one file per (ticker,date), overwritten; no hashes; no raw prompts. `memory/log.py TradingMemoryLog` = append-only markdown with `<!-- ENTRY_END -->` separator, idempotent per (ticker,date), later settled with outcome+reflection |
| TradingAgents repro | `_run_signature` (l.140): sha256[:12] of config JSON (sorted keys) + analysts/debate/risk/asset/portfolio fingerprint used as checkpoint thread-id so a resume under changed settings starts fresh; SQLite LangGraph checkpointer | config fingerprint idea is directly reusable | |
| Vibe-Trading | `trace.jsonl` via `TraceWriter` (`agent/src/agent/trace.py`): one JSON per line, `ts` auto-added, fsync per write, offload >50k chars to `trace-blobs/`, tool results to `tool-results/` with `preview`, `status`, `elapsed_ms`, `iter`, `call_id`; `run_card.json` with `reproducibility.config_hash`, `strategy_hash`, `artifacts[].sha256`, `tool_traces[].args_hash/result_hash` | crash-safe append log; hashed artefacts | no chain between records |
| Vibe-Trading shadow | `agent/backtest/binance_shadow_evidence.py`: deterministic read-only drift evidence; schema versions `binance-usdm-drift-evidence-v1`; snapshot "fidelity flags"; sha256 regex checks; "no account action path" | shows how a shadow mode is evidenced and schema-versioned | |
| NautilusTrader | event store (Rust `crates/event_store`, redb): entry = message + replay metadata, per-run `seq`, high-watermark, `RunStarted/RunEnded`, manifest sealed at end, `CrashedRecovered`/`Quarantined` seal states, dedup window by event/command id, read-only verifier; JSON/`.jsonl` log files named `{trader_id}_{date}_{instance_id}.jsonl` (`docs/concepts/logging.md:130,167`); DST doc defines seed-controlled determinism | gold standard for causal ordering | explicitly no tamper evidence; fail-stop does not stop the trader |

**Bug/caveat in CloddsBot hashing** (by JS semantics, not executed): `hashDecision` (`src/ledger/hash.ts`) calls `JSON.stringify(hashData, Object.keys(hashData).sort())`. An *array replacer* is an allow-list applied at **every nesting level**, so nested keys of `inputs/analysis/constraints` that are not also top-level field names (e.g. `size`, `price`, `passed`) are silently dropped from the hashed payload; tampering with them would not change the hash. Also `outcome`/`pnl` are excluded by design. Do not copy this pattern; use a canonical serializer (sorted keys at all levels, e.g. `json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False)`).

### What "proving algorithmic" requires (reading requirements.md)
Judges want: signal seen + reason per trade; manual trades identifiable; re-runnable; explainable. Therefore the log must tie each exchange order to a prior machine decision (same `decision_id`), show timing (decision ts < order ts < fill ts), and show orders that exist on the exchange but not in the log are *absent* (completeness check against Wallex order history).

## Recommended JSONL schema (one line per event, append-only)
File layout per run: `runs/<run_id>/decisions.jsonl` (+ `blobs/<sha256>` for big payloads, `manifest.json`, `run_card.json`). Event types share an envelope; one *decision cycle* emits a linked group.

```jsonc
// Envelope (every line)
{ "schema": "wlx-decision-log/1", "run_id": "2026-10-22T09:00Z-ab12", "seq": 41, "ts": "2026-10-22T09:15:00.123456Z",
  "type": "cycle|order_request|order_response|fill|fee|position_close|equity_snapshot|run_started|run_ended|error|override",
  "cycle_id": "c-000041", "decision_id": "d-000041-1",   // links all rows of one decision
  "prev_hash": "<hex sha256 of previous line's canonical bytes>", "hash": "<sha256(prev_hash + canonical(body))>",
  "body": { ... } }
```
`type=cycle` body (the core record; one per LLM invocation, including HOLD):
```jsonc
{ "mode": "live|shadow|backtest|replay",
  "code": { "git_sha": "...", "config_sha256": "...", "strategy_file_sha256": "...", "prompt_template_id": "v3", "prompt_template_sha256": "..." },
  "market": { "source": "wallex", "fetched_at": "...", "age_ms": 420, "symbols": ["BTCTMN","USDTTMN"],
              "snapshot_sha256": "...", "snapshot_ref": "blobs/<sha>", "best_bid": ..., "best_ask": ..., "spread_bps": ..., "depth_top5_tmn": ... },
  "features": { "BTCTMN": { "rsi14": .., "ema20_ema50": .., "atr14_pct": .., "ret_1h": .., "vol_ratio": .. } },   // exactly what the prompt shows
  "portfolio": { "equity_tmn": ..., "cash_tmn": ..., "positions": [ {...} ], "day_pnl_pct": ..., "drawdown_pct": ... },
  "llm": { "provider": "...", "model": "exact-id", "params": {"temperature":0,"max_tokens":..., "seed":...},
           "system_prompt_sha256": "...", "user_prompt_sha256": "...", "prompt_ref": "blobs/<sha>",
           "raw_response_ref": "blobs/<sha>", "raw_response_sha256": "...", "latency_ms": 5800, "usage": {"in":..,"out":..},
           "request_id": "provider-id", "attempt": 1 },
  "parsed": { "valid": true, "errors": [], "decisions": [ { "action":"buy|sell|hold", "symbol":"BTCTMN", "size_tier":"M", "confidence":0.72,
              "thesis":"<=500 chars", "invalidation":"...", "stop_pct": .., "target_pct": .. } ] },
  "gate": { "version": "gate-1.2", "verdicts": [ { "decision_idx":0, "approved": true, "adjusted_qty": ..,
              "checks":[ {"name":"max_position_pct","limit":0.25,"actual":0.18,"passed":true}, {"name":"fee_edge","limit":3.0,"actual":4.1,"passed":true}, {"name":"cooldown","passed":true}, {"name":"data_fresh","limit":5000,"actual":420,"passed":true} ],
              "reasons":[] } ] } }
```
`order_request`: `{decision_id, client_order_id (deterministic: hash(run_id,cycle_id,idx)), symbol, side, type, price, qty, tif, computed_from:{equity, tier, stop_level}}`.
`order_response`: `{http_status, exchange_order_id, status, raw_ref/raw_sha256, latency_ms, error}`. `fill`: `{exchange_order_id, trade_id, price, qty, fee, fee_currency, liquidity, filled_at}`. `position_close`: `{entry, exit, gross_pnl_tmn, fees_tmn, net_pnl_tmn, hold_s, exit_reason: "llm|stop|target|time|gate_flatten|final_flatten"}`. `equity_snapshot`: every N min, equity in Toman (used for drawdown proof). `override`: any operator action must be logged here (should be empty; its absence is evidence).

Design rules: UTC ISO-8601 with microseconds; Decimals as strings (NoFx uses `decimal.go` for order precision for the same reason); one fsync per line (Vibe-Trading pattern); big payloads (prompts, raw responses, market snapshots) in content-addressed `blobs/<sha256>` written and fsynced **before** the referencing line; never log API keys (TradingAgents `run_settings` is an allow-list for that reason).

## Tamper-evidence
1. **Hash chain**: `hash_n = sha256(prev_hash || canonical_json(envelope_without_hash_and_prev))`, genesis `prev_hash = sha256(run_id || git_sha || config_sha256)`. Verification is O(n), 20 lines of Python, stdlib only.
2. **Periodic external anchor** (cheap, no chain needed): every K lines or hourly, write head hash to somewhere the team cannot silently rewrite later: git commit/tag pushed to the repo (timestamped by GitHub), a GitHub issue/gist comment, or an email to organisers; CloddsBot's Solana/Polygon/Base anchoring (`src/ledger/anchor.ts`) is the heavy version. For judges, a pushed head hash at each day boundary is enough.
3. **Cross-source reconciliation**: the verifier fetches Wallex order/trade history for the dedicated account and checks every exchange order maps to exactly one `order_request` with a `decision_id` whose `cycle` precedes it, and that the log lists no fill absent on the exchange. A manual trade would appear as an exchange order with no log line (the "manual trades identifiable" requirement).
4. **Deterministic client order ids** (`hash(run_id,cycle_id,idx)` as Wallex `client_order_id`, if the API supports one: unverified) so ids prove origin.
5. **Seal**: `run_ended` line + `manifest.json` {first/last seq, head hash, line count, sha256 of each blob}. Mirror NautilusTrader's `RunStarted/RunEnded` + `CrashedRecovered` states so a crash does not look like tampering (on restart, append `run_resumed` referencing last durable hash).
6. Limits to state honestly: a hash chain proves *internal consistency and ordering*, not that the log was written live; combine with exchange reconciliation and anchors.

## Making the run replayable
- **Record**: market inputs (candles/orderbook JSON snapshot per cycle in blobs, or the raw candle CSV once + per-cycle cut-off timestamp), full prompt, model id + params, raw response.
- **Replay modes** (same code path, injected clients; Nautilus's backend-opener/MemoryBackend and DST seed ideas):
  - `--mode replay --log runs/X/decisions.jsonl`: market client reads snapshots from blobs, LLM client returns `raw_response` where `prompt_sha256` matches (fail loudly on mismatch = prompt/feature drift), execution client is a simulator with the logged fills or fee model. Assert: recomputed features == logged features; parsed decisions == logged; gate verdicts == logged; orders == logged.
  - `--mode backtest --data candles.csv --llm recorded|live`: historical data with LLM called live (non-deterministic, stored as new recording) or from recording.
  - `--mode shadow`: live data, real LLM, execution client writes `order_request` with `mode=shadow` and simulated fill at best bid/ask +- slippage; same log schema so shadow == live log minus exchange rows (Vibe-Trading's read-only evidence pattern).
- Use temperature 0 and seed where supported but do not claim determinism of the LLM: determinism claim is "given the recorded LLM output, everything downstream is bit-identical". Record `system_fingerprint`/request id if the provider returns one.
- Pin: `requirements.lock`, python version, git sha in `run_started`; config fingerprint like TradingAgents `_run_signature`; run card like Vibe-Trading `write_run_card`.

## What judges can verify (and how)
| Claim | Check | Command (proposed) |
|---|---|---|
| Log not edited after the fact | hash chain + anchored head | `python verify_log.py runs/X` |
| Every trade has a prior machine decision | order_request.decision_id exists, cycle ts < order ts | same |
| No extra/manual trades | Wallex trade history vs log (needs read-only API key or exported CSV) | `verify_log.py --reconcile wallex_trades.csv` |
| LLM really decided | `llm.raw_response_ref` present, parsed == recomputed, prompt hash matches template + features | replay mode |
| Risk gate enforced independent of LLM | `gate.verdicts[].checks` + re-evaluate gate on logged inputs; rejected decisions have no order_request | replay mode |
| Backtest/shadow done | `mode` field, run cards, metrics recomputed from fills | `report.py` |
| PnL in Toman, flat at end | last `equity_snapshot` has no non-TMN positions | verifier |

## Reusable for our system
- Re-implement (no copying of AGPL NoFx): decision record field set from `store/decision.go` + `AccountSnapshot/PositionSnapshot`; `ai_request_duration_ms`.
- Port pattern (MIT, safe): Vibe-Trading `TraceWriter` fsync+sidecar-blob logic and `run_card` hashing (`_json_hash`, `_file_hash`, artifacts list); CloddsBot constraint evaluation record `{type,rule,threshold,actual,passed,violation}` (fix canonicalization).
- Port pattern (Apache-2.0): TradingAgents `_run_signature` config fingerprint, `run_settings` allow-list, append-only memory log with idempotency per key.
- Concepts only (LGPL): Nautilus event-sourcing: `seq`, causation/correlation ids, run lifecycle entries, read-only verifier, raw venue reports captured before derived events.

## Recommended design decisions for the hackathon
1. One writer module `decision_log.py` (~150 lines): `append(type, body)` computes canonical JSON, chain hash, writes line, fsync; blob store by sha256. All components (feature builder, LLM client, gate, executor, fill poller) call it; **no trading code path may place an order without first appending `order_request`** (executor takes a `decision_id` and refuses otherwise). This is the structural proof of "no manual trades".
2. Log HOLDs and gate rejections (activity + risk-management evidence). Expect ~96 cycles/day at 15 min; file stays small (<10 MB/day incl. blobs).
3. Put the *gate verdict checks with limit and actual values* in the log; judges score risk management (30) on evidence, not claims.
4. Daily: commit `runs/<id>/head_hash.txt` + `manifest.json` to git (timestamp anchor). Provide `verify_log.py` and `replay.py` and document both in the required MD.
5. Human-readable view: auto-generate `decisions.md` table (time, symbol, action, thesis, gate result, order, fill, net PnL) from the JSONL for the demo video and for judges who will not run code.
6. Keep an explicit `override` event type and a policy that the operator never touches the account; if an emergency flatten is needed it must go through the same executor with `exit_reason=operator_kill_switch` logged.
7. Also write plain app logs separately (structured JSON like Nautilus `.jsonl`) for execution-stability (15 pts): errors, retries, API latency; do not mix with the audit chain.

## Unverified / open questions
- Whether Wallex's order API accepts a client-supplied order id or exposes full trade history with fees (needed for reconciliation and deterministic ids); not in requirements.md, must check https://developers.wallex.ir/docs.
- Whether judges will be given read-only API access to the dedicated account; if not, an exported trade CSV is the fallback.
- Vibe-Trading `src/agent/grounding/ledger.py` and `evals/harness/*` were not read in depth (may hold additional audit patterns).
- NautilusTrader event-store verifier details (checksums per entry?) were read only at the concept-doc level (`docs/concepts/event_sourcing.md`), not in `crates/event_store` source.
- CloddsBot hash-scope bug is derived from JavaScript semantics of array replacers, not by running code (running was forbidden).
