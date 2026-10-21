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
