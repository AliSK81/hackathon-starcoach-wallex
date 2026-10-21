# Phase 0 — Project setup

Goal: a Python project that runs with one command, with no keys.

## Choices

- Language: Python. The research and most trading tools use it.
- Tool: `uv`. One command installs and runs the project.
- Name of the command: `wx`.
- No libraries yet. We add them when a phase needs them.

## Checklist

- [x] `pyproject.toml` with the `wx` command.
- [x] `uv run wx` prints the version and which keys are set. It never prints a key.
- [x] It works when `.env` is missing or empty.
- [x] `.gitignore` ignores `.env`.
- [x] `.env.example` lists every key name, with fake values.
- [x] One test that runs without internet: `uv run pytest`.
- [x] README says how to run it.
