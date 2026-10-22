# hackathon-starcoach-wallex

A bot that trades on Wallex by itself.

## Run it

You need [uv](https://docs.astral.sh/uv/).

```bash
uv run wx
```

This installs the project and prints which keys are set. It runs without any key.

```bash
uv run wx markets
```

This reads all Wallex markets, shows how many we may trade, and saves a copy in `data/`. It needs no key.

```bash
uv run wx candles
```

This saves 1-minute and 1-hour candles for six markets in `data/candles/`. It keeps the last 120 days (`--days` changes this). Later runs add only what is missing. It needs no key.

```bash
uv run wx watch
```

This reads live prices for the same six markets every minute and logs them in `data/prices/`. Network errors are logged, and it keeps going. Ctrl+C stops it. It needs no key.

```bash
uv run wx account
```

This reads our balances and fee rates and saves a copy in `data/account/`. It needs `WALLEX_API_KEY` in `.env`.

```bash
uv run wx rules
```

This shows the order rules for the six markets: decimals, minimum quantity, and minimum order value. It needs no key.

```bash
uv run wx ai
```

This asks the AI one small question, to check the AI settings. It needs `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY` in `.env`.

```bash
uv run wx features
```

This updates the candles, reads the live order book, and prints the indicators the AI will use, for the same six markets. With `WALLEX_API_KEY` it also shows the round-trip cost.

```bash
uv run wx decide
```

This computes the features, then asks the AI for BUY, SELL or HOLD on each of the six markets, with a reason. Code checks the answer and logs it in `data/decisions/`. It places no orders. It needs the AI settings. With `WALLEX_API_KEY` the AI also sees our cash and holdings.

```bash
uv run wx run
```

This makes a decision like `wx decide` every 15 minutes, on the beat (at :00, :15, :30 and :45). Every cycle is logged in `data/decisions/`, even one that fails. Errors never stop it. Ctrl+C stops it. It places no orders. `--interval` and `--cycles` change the beat and the number of cycles.

```bash
uv run wx replay
```

This asks the AI about 40 past moments, rebuilt from the saved candles. Then it shows how often the AI bought, and how the price moved in the next 24 hours after each BUY and HOLD, after costs. `--moments`, `--days` and `--seed` change which moments. It needs the AI settings.

## Keys

Copy `.env.example` to `.env` and fill in the values. Git ignores `.env`.

## Tests

```bash
uv run pytest
```

## Docs

- [Roadmap](docs/ROADMAP.md): the phases.
- [Progress](docs/PROGRESS.md): what we did.
- [Decisions](docs/DECISIONS.md): what we decided, and facts we checked.
