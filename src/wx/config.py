"""Read settings from the environment and an optional .env file.

Keys are never printed or logged. Code asks `is_set()` instead.
"""

import os
from pathlib import Path

# Every setting the bot knows. .env.example must list the same names.
KEYS = ("WALLEX_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY")


def read_env_file(path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE lines. A missing file gives an empty dict."""
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("\"'")
    return values


class Settings:
    def __init__(self, values: dict[str, str]):
        self._values = {k: v for k, v in values.items() if k in KEYS and v}

    @classmethod
    def load(cls, env_file: Path = Path(".env")) -> "Settings":
        """Values in the real environment win over values in .env."""
        values = read_env_file(env_file)
        values.update({k: os.environ[k] for k in KEYS if os.environ.get(k)})
        return cls(values)

    def is_set(self, name: str) -> bool:
        return name in self._values

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def __repr__(self) -> str:
        return f"Settings(set={sorted(self._values)})"
