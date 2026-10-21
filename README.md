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

This saves 1-minute and 1-hour candles for six markets in `data/candles/`. The first run gets 30 days. Later runs add only new candles. It needs no key.

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
