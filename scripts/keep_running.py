"""Keep the agent running: restart it whenever it stops, until trading ends or data/KILL exists.

The book, the orders and the memory are on disk, so a restart loses nothing. Every start and stop is logged in
data/brain/supervisor.log. Use the same arguments as `wx agent`, for example:
    uv run python scripts/keep_running.py --live --end-at 2026-10-23T00:30
"""
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

LOG = Path("data/brain/supervisor.log")
PAUSE = 15  # seconds before a restart


def log(text: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC {text}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def end_time(args: list[str]) -> float | None:
    if "--end-at" not in args:
        return None
    t = datetime.fromisoformat(args[args.index("--end-at") + 1])
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).timestamp()


def main() -> int:
    args = sys.argv[1:]
    end = end_time(args)
    starts = 0
    while True:
        if Path("data/KILL").exists():
            log("data/KILL exists: not starting the agent")
            return 0
        if end is not None and time.time() > end + 600:
            log("trading has ended: supervisor stops")
            return 0
        starts += 1
        log(f"start {starts}: wx agent {' '.join(args)}")
        code = subprocess.call([sys.executable, "-m", "wx.cli", "agent", *args])
        log(f"the agent stopped with exit code {code}")
        if code == 0 and end is not None and time.time() > end:
            return 0
        time.sleep(PAUSE)


if __name__ == "__main__":
    raise SystemExit(main())
