# Repo Structure, Config, CLI and Reproducibility Patterns ("judge can re-run")

**Scope**: how freqtrade, Jesse, LumiBot, NautilusTrader, OctoBot, Haehnchen/crypto-trading-bot structure config, strategies, run scripts, Docker, tests, docs; and a concrete layout/config/CLI/CI/doc outline for our Wallex project to maximise the 25-pt reproducibility score. · **Researched**: 2026-10-21
**Repos+commits** (read only): `freqtrade/freqtrade@0db79d3`, `jesse-ai/jesse@4fcbcdd`, `Lumiwealth/lumibot@05c04fd`, `nautechsystems/nautilus_trader@e88439b`, `Drakkar-Software/OctoBot@c45fdc2`, `Haehnchen/crypto-trading-bot@cb95633`; cross-ref `04-backtesting-shadow-mode.md` (modes, artifacts) and `09-decision-logging-observability.md` (log format).

## TL;DR
- **Winning pattern = one config file + one CLI with sub-commands + one `user_data`-like output dir.** Freqtrade: `freqtrade {trade|backtesting|download-data|lookahead-analysis ...} --config config.json --strategy X`, outputs under `user_data/{backtest_results,data,logs,...}` (`user_data/` dirs; `docker-compose.yml` command block). Mirror it: `wx {backtest|shadow|live|report|verify}`.
- **Secrets never in the committed config**: freqtrade supports `FREQTRADE__{section}__{key}` env overrides (`constants.py:131 ENV_VAR_PREFIX`, `configuration/environment_vars.py:40,79`) while example configs ship placeholders (`config_binance.example.json`: `"api_key": "your_exchange_api_key"`); Nautilus ships `.env.example`; LumiBot `.env.local.example` ("DO NOT COMMIT secrets", `REPLACE_ME`). Ship `.env.example`, load with a loader that fails loudly on missing keys, and never log them.
- **Config validated by a schema, fail-fast**: freqtrade has a full JSON schema (`freqtrade/config_schema/config_schema.py`, e.g. `fee` min 0 max 0.1; `dry_run_wallet` number or per-currency object) and publishes `$schema` in example configs. Use pydantic models; reject unknown keys; hash the resolved config into the run manifest.
- **Pin everything**: freqtrade `requirements.txt` uses exact `==` pins (`numpy==2.5.4`, `pandas==3.0.6`, `ccxt==4.5.88` ...) and Docker base `python:3.14.8-slim-trixie`; Nautilus uses lock files (`Cargo.lock`, `uv.lock`) and a pinned tool catalog (`make install-uv` pins uv). Jesse uses `~=` ranges, LumiBot `>=` ranges (weaker). We pin with exact `==` plus a lock/hash file and a Docker image.
- **Docker for re-run is standard but optional**: freqtrade `Dockerfile` (multi-stage `base` -> `python-deps`; non-root `ftuser`, `ENV PYTHONDONTWRITEBYTECODE=1 PYTHONFAULTHANDLER=1`) + `docker-compose.yml` mounting `./user_data:/freqtrade/user_data`. OctoBot compose mounts `./logs ./backtesting ./tentacles ./user`. Provide both `docker compose run` and a plain `venv` path; judges on Windows without Docker must still run the offline replay.
- **Results are reproducible if the run is identified by a hash**: freqtrade `optimize/backtest_caching.py` makes a sha1 over config+strategy files ("Identical config and strategy file will always return an identical hash") and writes `<result>.meta.json` next to the results (`bt_storage.py:78-79`). Copy: `run_manifest.json` (git sha, config hash, data hash, prompt hash, lib versions, seed).
- **Tests that matter for judges**: freqtrade CI runs `pytest --random-order --durations 20 -n auto` (random order exposes hidden state), on a matrix of OSes/Pythons (`.github/workflows/ci.yml:79`), `pre-commit`, `zizmor` workflow lint. LumiBot keeps *real-model* agent evals as a manual `workflow_dispatch` job separate from CI (`.github/workflows/agent-evals.yml`) - LLM tests must never block deterministic CI. Our CI: unit tests + `make smoke` in replay mode (no network, no keys).
- **Agent-facing docs help**: Jesse, LumiBot, Nautilus, OctoBot, Haehnchen all ship `AGENTS.md`/`CLAUDE.md` describing repo layout and rules. A short `AGENTS.md` (how to run, invariants: "LLM never bypasses RiskGate") makes the repo self-explanatory for judges using AI assistants.
- **Haehnchen/crypto-trading-bot** is the negative example: "Not production ready", web UI + sqlite + ejs views, no fee/slippage model, no seeded determinism, config in `conf.json` outside repo; UI/UX is not scored here. Don't build a UI; build a CLI + static report.

## Findings

### freqtrade (`@0db79d3`)
- Layout: `freqtrade/` (package: `commands/`, `optimize/`, `strategy/`, `exchange/`, `config_schema/`), `config_examples/*.example.json`, `user_data/{backtest_results,data,freqaimodels,hyperopts,logs,notebooks}/.gitkeep` (empty dirs committed so Docker mounts work), `docs/` (mkdocs, `mkdocs.yml`), `tests/` (mirrors package: `tests/optimize`, `tests/exchange`, `tests/strategy`, `conftest.py`), `docker/`, `build_helpers/`, `setup.sh`/`setup.ps1`, `.pre-commit-config.yaml`, `pyproject.toml`, `requirements*.txt` split (`requirements.txt`, `-dev`, `-hyperopt`, `-plot`, `-freqai`).
- Config keys that matter for us (from `config_examples/config_full.example.json`): `max_open_trades`, `stake_currency`, `stake_amount`, `tradable_balance_ratio` (0.99 = keep 1% unused), `available_capital`, `dry_run`, `dry_run_wallet`, `timeframe`, `stoploss` (-0.10), `trailing_stop*`, `minimal_roi` {minutes: ratio}, `unfilledtimeout{entry,exit,unit}`, `entry_pricing/exit_pricing{price_side, use_order_book, order_book_top, price_last_balance, check_depth_of_market}` (`config_schema.py:368-430`), `exchange{name,key,secret,pair_whitelist,pair_blacklist}`, `fee` (backtest only). Multiple `--config` files are merged (secrets in a second private file).
- Strategy interface: `IStrategy` (`strategy/interface.py`) with `populate_indicators`, `populate_entry_trend`, `populate_exit_trend`, plus callbacks `custom_stoploss`, `custom_exit`, `custom_entry_price`, `confirm_trade_entry`; strategy class name selected with `--strategy`. Strategies live in `user_data/strategies/` (user code outside package) - clean separation of engine vs user code.
- Reproducibility tooling: `backtesting` with `--export trades`, result zip + `.meta.json`; `lookahead-analysis`, `recursive-analysis` (`optimize/analysis/`); hyperopt seeds (`random_state`, `hyperopt_optimizer.py:421-428`); JSON/zip results loadable by `backtesting-show`.
- Tests: ~25 test dirs (`tests/commands`, `freqtradebot`, `optimize`, ...) incl. `tests/exchange_online` (live-network, excluded from default CI - CI "Run pytest with live checks" job at `ci.yml:253`).

### Jesse (`@4fcbcdd`)
- Layout: `jesse/` package with `modes/` (`backtest_mode.py`, `optimize_mode`, `monte_carlo_mode`, `significance_test_mode`, `import_candles_mode`), `exchanges/` (`Exchange` base, `sandbox/Sandbox.py`), `services/`, `strategies/Strategy.py` (hooks `should_long`, `go_long`, `update_position`, `should_cancel_entry`, `before`), `config.py`, `store/`; a *project template* is a separate repo (strategies in `strategies/<Name>/__init__.py`, routes and `.env`). Dockerfile + `pytest.ini`, `conftest.py`, `tests/`, `AGENTS.md`, `.claude/skills` (`jesse-strategy-tests`), MCP server in `jesse/mcp/` with `agent_rules.md`.
- Notable: `monte_carlo_mode` and `significance_test_mode` - a built-in answer to "is this luck?" (the exact concern in the requirements: "not dependent on one lucky trade"). Worth re-implementing a tiny version (bootstrap/shuffle of trade returns) in `wx report`.
- Deps use `~=` ranges (`requirements.txt`: `numpy~=1.26.4`, `pandas~=2.2.3`, `pytest~=6.2.5`).

### LumiBot (`@05c04fd`)
- Layout: `lumibot/{strategies,brokers,backtesting,data_sources,entities,components/agents,tools,traders}`, `tests/`, `docs`/`docsrc` (sphinx rst), `examples/`, `agent_eval_cases|baselines|fixtures` (LLM eval corpus), `ci/`, `.env.local.example`.
- Parity trick: user code identical; `MyStrategy.backtest(datasource_class, start, end, parameters=..., budget=...)` vs `Trader().add_strategy(); run_all()` with a broker (`README.md:38,212-225`). `parameters` dict is how config is injected into the strategy.
- LLM-specific reproducibility: replay cache (see file 04), `StubAgentRuntime(scripted_events=...)` (`components/agents/runtime.py`, ~L2290) lets tests run an "agent" with scripted tool events and no network - **copy this for our unit tests/CI** (`FakeLLM` that returns canned JSON).
- Agent evals are `workflow_dispatch`-only with a `qualification.json` artifact upload; CI (`cicd.yaml`) is separate.

### NautilusTrader (`@e88439b`)
- Root has `.env.example` (only `NAUTILUS_PATH=/path/to/nautilus/data`), `Makefile` with self-documenting targets (`target:  #-- description`, e.g. `install`, `build`, `format`, `install-tools`), `.pre-commit-config.yaml`, `deny.toml`, `AGENTS.md`/`CLAUDE.md`, `docs/concepts/*` as the architecture book, `examples/`, `tests/`. Config objects (`BacktestEngineConfig`, `StrategyConfig`, `SandboxExecutionClientConfig`) are typed and serializable; `BacktestNode` runs batches from config. Reproducibility knobs: fill model `random_seed`, `ts_init` pinned in backtest data (`execution-flow.md:219`), deterministic simulation support in docs (`docs/concepts/dst.md`).
- Docs pattern to copy: a "Backtest and live differences" page (`live.md:13`) - judges love an honest list of what is *not* identical between sim and live.

### OctoBot (`@c45fdc2`)
- Layout: `octobot/`, `packages/{trading,backtesting,evaluators,...}`, `tentacles` (plugin strategies), `user/` (profiles and config), `docker-compose.yml` with volumes and `restart: always`, `start.py`, `requirements.txt` (exact `==` pins, e.g. `requests==2.34.2 # sync with ccxt`), `full_requirements.txt`, `dev_requirements.txt`, `pants.toml` build system. Simulator is a config switch (`trader-simulator.enabled`), starting portfolio in config reused for backtests; profiles = directories of JSON settings (good model for "named strategy profile": `profiles/conservative.yaml`).

### Haehnchen/crypto-trading-bot (`@cb95633`)
- TypeScript, esbuild, `npm start`, sqlite store, ejs UI, `test/` with JSON candle fixtures (`test/modules/strategy/v2/fixtures/btc-usdt-15m.json`) - fixtures-in-repo is the one good idea (tiny deterministic candle files for tests). `docs/backtest_v2_migration.md` shows a strategy registry (`strategyRegistry = {'dca_dipper_v2': DcaDipperV2}`; `getStrategyClass(name)`), which we replicate as a decorator registry.

## Comparison table

| Aspect | freqtrade | Jesse | LumiBot | Nautilus | OctoBot | Haehnchen |
|---|---|---|---|---|---|---|
| Config format | JSON + JSON schema, env override | `.env` + routes (python) | python params dict + `.env` | typed config objects | JSON profiles | `conf.json` |
| CLI | sub-commands | `jesse` CLI + dashboard | python entry | python API / CLI | `start.py` | `npm start` |
| Dependency pins | exact `==` | `~=` | `>=` | lockfiles | exact `==` | `package-lock.json` |
| Docker | yes (compose, non-root) | Dockerfile | no (cloud) | `.docker/` | compose | `.dockerignore` |
| Secrets pattern | env override + example config | `.env` | `.env.local.example` | `.env.example` | in `user/` | in conf |
| Result id/hash | yes (`.meta.json`) | DB | cache evidence files | run ids in event store | n/a | none |
| LLM test double | n/a | n/a | `StubAgentRuntime` | n/a | n/a | n/a |

## Reusable for our system (patterns; re-implement, mind GPL/AGPL)
- freqtrade: sub-command CLI, `FREQTRADE__SECTION__KEY` env override scheme (GPL: re-implement ~30 lines), `.gitkeep` output dirs, config `$schema`, config-hash result id, `--random-order` pytest, `exchange_online`-style marker for network tests (`@pytest.mark.network`, excluded by default).
- Nautilus: self-documenting Makefile comments; `.env.example`; "differences" doc page.
- LumiBot: `StubAgentRuntime` test double; replay cache; separate manual real-LLM eval workflow.
- Jesse: bootstrap/Monte-Carlo significance of trades.
- Haehnchen: tiny candle fixtures committed for tests; strategy registry.

## Recommended design decisions for the hackathon

### Repository layout
```
wallex-agent-trader/
  README.md                     # 1-page quickstart + link to docs/ARCHITECTURE.md (the required MD doc)
  AGENTS.md                     # invariants + how to run (judges' AI assistants)
  LICENSE
  Makefile                      # setup, test, smoke, backtest, shadow, live, report, verify, docker
  pyproject.toml                # package + ruff/pytest config; console script `wx`
  requirements.txt              # exact == pins (runtime)
  requirements-dev.txt
  requirements.lock             # pip-compile --generate-hashes output (optional)
  Dockerfile  docker-compose.yml  .dockerignore
  .env.example                  # WALLEX_API_KEY=, LLM_API_KEY=, LLM_BASE_URL= (placeholders only)
  .gitignore                    # .env, runs/live-*/, data/raw cache (not artifacts/)
  config/
    default.yaml                # all keys with defaults + comments
    backtest.yaml shadow.yaml live.yaml     # thin overrides: mode, data paths, llm.mode
    profiles/{conservative,base}.yaml      # risk presets
  src/wx/
    cli.py                      # argparse/typer: backtest|shadow|live|report|verify|fetch-data|replay
    config.py                   # pydantic models, env merge, config hash
    clock.py  types.py          # SimClock/WallClock; dataclasses (Candle, OrderBook, Fill, ...)
    data/ {wallex_rest.py, wallex_ws.py, historical.py, store.py}   # fetch/cache/parquet
    features/ builder.py        # pure functions, stable feature ids, no future reads
    agent/ {prompts/*.md, schema.py, llm_client.py (Live|Recorded), decide.py, critic.py?}
    risk/ {gate.py, sizing.py, stops.py, circuit_breaker.py}        # deterministic, LLM-independent
    exec/ {broker.py (Protocol), sim_exchange.py, backtest_broker.py, shadow_broker.py, wallex_broker.py, fill_model.py}
    engine.py                   # the single loop: tick -> features -> LLM -> gate -> broker
    logging/ {decision_log.py (hash chain), metrics.py, report.py, manifest.py}
  data/
    fixtures/ btc_tmn_15m_sample.csv ...   # tiny, committed, used by tests/smoke
    raw/                         # gitignored downloads; `make fetch-data` recreates
  artifacts/                     # COMMITTED evidence judges can verify without keys
    backtest_official/ {run_manifest.json, decisions.jsonl, fills.csv, equity.csv, metrics.json, report.md, llm_cache.jsonl.gz}
    shadow_official/ {...}
    live_trading/ {decisions.jsonl, fills.csv, equity.csv, metrics.json}   # the real 3-day run
  runs/                          # gitignored scratch for new runs
  tests/ {unit/, integration/, conftest.py}   # FakeLLM, fixtures, property tests (no lookahead, gate invariants)
  docs/ {ARCHITECTURE.md, RUNBOOK.md, research/}
  .github/workflows/ci.yml       # lint + pytest + make smoke (replay, offline)
```

### Config schema (YAML; one resolved file hashed into manifest)
```yaml
run:        { mode: backtest|shadow|live, seed: 42, run_dir: runs, tz: UTC }
capital:    { initial_tmn: 5000000, currency: TMN, end_flat_to_tmn: true, flatten_lead_min: 60 }
universe:   { symbols: [BTCTMN, ETHTMN, USDTTMN], quote: TMN, source: wallex_allowed_markets }  # symbol naming unverified
data:       { timeframe: 15m, lookback_candles: 200, history_days: 30, depth_levels: 20,
              historical_path: data/raw, fixtures_path: data/fixtures }
decision:   { cadence_min: 15, max_symbols_per_cycle: 3, prefilter: {min_vol_z: 0.5} }
llm:        { mode: live|record|replay, provider: anthropic|openai, model: <pinned id>, temperature: 0,
              max_tokens: 800, timeout_s: 30, prompt_version: v1, cache_path: artifacts/backtest_official/llm_cache.jsonl.gz,
              strict_replay: true, fallback: no_trade }
risk:       { max_position_pct: 0.20, max_total_exposure_pct: 0.60, max_open_positions: 3,
              per_trade_risk_pct: 0.01, stop_loss_atr_mult: 1.5, min_stop_pct: 0.8, max_stop_pct: 4.0,
              trailing: {enabled: true, activate_pct: 1.5, distance_pct: 1.0},
              time_stop_min: 360, max_daily_loss_pct: 3.0, max_drawdown_pct: 8.0, cooldown_after_loss_min: 60,
              max_trades_per_day: 12, min_net_edge_x_cost: 2.0, max_participation_pct_depth: 10 }
execution:  { order_type: limit_then_market, limit_offset_bps: 2, ttl_s: 60, max_slippage_bps: 100, retries: 2 }
fees_fill:  { maker_bps: <wallex>, taker_bps: <wallex>, half_spread_bps_default: 10, impact_k_bps: 20,
              latency_s: {decision: 10, exchange: 1}, limit_fill_prob_touch: 0.5, source: wallex_api|config }
backtest:   { start: 2026-..-.., end: 2026-..-.., walk_forward_split: 0.7, baselines: [buy_hold, rules_only, random_gated] }
logging:    { decision_log: jsonl, hash_chain: true, redact: [api_key] }
secrets:    from env only: WALLEX_API_KEY, WALLEX_API_SECRET?, LLM_API_KEY
```
Config precedence: `default.yaml` < mode file < `--config extra.yaml` < `WX__SECTION__KEY` env < CLI flags. Fail on unknown keys; print resolved config + sha256 at start.

### CLI and Makefile
```
make setup            # python -m venv .venv && pip install -r requirements.txt -r requirements-dev.txt   (or `docker compose build`)
make test             # pytest -q --random-order           (offline, FakeLLM)
make smoke            # wx backtest --config config/backtest.yaml --data data/fixtures --llm replay --out runs/smoke && wx verify runs/smoke   (<60 s, no keys)
make fetch-data       # wx fetch-data --symbols ... --days 30           (needs network, no key if public endpoints)
make backtest         # wx backtest --llm replay   (official, uses committed cache) ; LLM=record to regenerate (needs LLM key)
make shadow           # wx shadow --duration 24h          (needs LLM key; Wallex public data only)
make live             # wx live --confirm-live            (needs keys; refuses without --confirm-live and a non-empty kill-switch path)
make report RUN=...   # wx report runs/<id>  -> report.md, equity.png, metrics.json
make verify RUN=...   # wx verify: hash chain, schema, recompute features+gate from log, compare fills to metrics
make docker-smoke     # docker compose run --rm wx make smoke
```
- Single entry point `python -m wx ...`; every command prints the run directory and writes `run_manifest.json` first (so a crashed run is still identifiable).
- `--llm replay` is the default for `backtest` and `smoke`; a cache miss in strict mode raises (never silently calls the API).

### Seeding and determinism
- `run.seed` seeds `random`, `numpy`, and the sim fill model RNG (separate `Random(seed)` instance, Nautilus `random_seed` style); never use global RNG in core.
- Sort universes and iterate in fixed order; use `Decimal`/int TMN for money; canonical JSON (`sort_keys=True, separators=(",",":")`) for hashing prompts/logs (LumiBot `compute_key`).
- Pin `PYTHONHASHSEED=0` in Makefile/Docker; no `datetime.now()` in core (clock injection).
- Replay equality test in CI: run smoke twice, assert `metrics.json` and `decisions.jsonl` hashes identical.
- State honestly: live LLM runs are not deterministic; reproducibility = replay of recorded responses + deterministic everything else.

### Dependencies, Docker, secrets
- `requirements.txt` exact pins (freqtrade/OctoBot style) for Python 3.11 or 3.12 (pick the version available on judge machines; pin it in `.python-version`, Docker `python:3.12.x-slim`). Optionally `pip-compile --generate-hashes`.
- Dockerfile: multi-stage, non-root, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONFAULTHANDLER=1`, `PYTHONHASHSEED=0`, copy `requirements.txt` first for layer cache, mount `./runs` and `./artifacts`. Default `CMD ["make","smoke"]` so `docker compose up` proves it works.
- `.env.example` with placeholders, a `wx doctor` command that checks keys are present (never prints them) and can reach Wallex public endpoints; `.gitignore` for `.env`; pre-commit hook `detect-secrets` or a 10-line grep test that fails CI if a string matching the key pattern appears in the repo or in `artifacts/`; decision logs redact headers.
- Judges without LLM keys: all of `make test`, `make smoke`, `make backtest` (replay), `make verify` work offline. That is the key reproducibility promise.

### CI smoke test (`.github/workflows/ci.yml`)
1. checkout; setup-python (pinned); `pip install -r requirements.txt -r requirements-dev.txt`.
2. `ruff check`, `pytest -q --random-order`.
3. `make smoke` (fixtures + replay), `wx verify runs/smoke`.
4. compare `runs/smoke/metrics.json` to `tests/golden/smoke_metrics.json` (golden file updated deliberately).
5. Separate manual `workflow_dispatch` job for real-LLM record (LumiBot pattern) - not required to pass.
Tests to include: no-lookahead property test (features at t unchanged if future candles appended), gate invariants (never exceeds caps, never trades non-allowed symbol, always has stop, never all-in), fill model unit tests (order-book walk, fee on both legs, min notional), hash-chain verification, `FakeLLM` malformed-JSON -> NO_TRADE, flatten-to-TMN at end.

### Required MD doc outline (`docs/ARCHITECTURE.md`; README links it; matches the deliverables list)
1. **Overview and results at a glance**: one table (backtest, shadow, live: period, trades, net return %, max DD, fees) + link to artifacts.
2. **Architecture and main logic**: diagram (data -> features -> LLM agent -> critic? -> RiskGate -> Broker -> log), module map to `src/wx/*`, cycle timing, mode parity statement (same engine; what differs - copy Nautilus "differences" list).
3. **AI and Wallex tool usage**: which model, prompt template(s) (excerpt + path), JSON schema of the decision, what the LLM decides vs what code decides, tool/MCP calls used (Wallex MCP/API endpoints list), fallback on LLM failure, cost/latency numbers; how we know it is "real AI" (baselines comparison, ablation: rules-only vs LLM).
4. **Buy/sell decision conditions**: entry (features cited, min net edge vs cost, regime filters), exit (LLM exit, stop, trailing, time stop, flatten-to-TMN), explicit worked example of 2-3 real logged decisions with their `decision_id`.
5. **Capital and risk management**: capital 5,000,000 TMN, per-trade cap, exposure cap, stop loss rule, drawdown breaker, cooldowns, trade caps, no all-in, kill switch, error handling, what the gate rejected in the backtest (counts).
6. **Backtest and shadow testing**: data windows, fill/fee model parameters, biases handled (lookahead test, cutoff leakage control), results, limitations (small sample).
7. **How to re-run and evaluate**: prerequisites, `.env`, `make setup`, `make smoke`, `make backtest` (replay), `make verify`, `make shadow`, expected outputs and where, how to compare to `artifacts/`, how to read the decision log (field dictionary), how to confirm no manual trades (hash chain + order `client_order_id` prefix `wx-<run>-<seq>` matched against Wallex order history).
8. **Reproducibility notes**: pins, seeds, LLM nondeterminism and replay cache, known divergences sim vs live.
9. **Compliance statement**: only approved markets, no manual trades, no wash trading, one account.

## Unverified / open questions
- Wallex API/MCP details (symbol naming, fee values, auth scheme, WebSocket availability) are not verified in this file; config placeholders (`<wallex>`) must be filled from the API docs/other research files.
- Python version available on the judges' machines is unknown; choose a widely available one (3.11/3.12) and avoid compiled deps (TA-Lib) - freqtrade itself needs `ta-lib` (`requirements.txt`), a known installation pain; prefer pure-Python/NumPy features.
- I did not read Jesse's project-template repo (strategies/routes layout is from general knowledge of `jesse-ai/project-template`, unverified) nor OctoBot's profile JSON schema in detail.
- Licenses (GPL-3.0 freqtrade/LumiBot/OctoBot, LGPL Nautilus, MIT Jesse/Haehnchen) from memory; confirm before copying anything beyond patterns.
- Whether the hackathon organisers require a specific repo layout or accept committed artifacts with large LLM caches (size limits) is unknown; keep `llm_cache.jsonl.gz` small (compact features, short outputs).
