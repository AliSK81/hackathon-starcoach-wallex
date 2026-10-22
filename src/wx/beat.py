"""Run a step on a fixed beat, e.g. at :00, :15, :30 and :45 with 900 s.

The first step runs at once. A step that fails is reported, and the loop
goes on at the next beat. Ctrl+C stops it.
"""

import time
from collections.abc import Callable


def every(interval: int, step: Callable[[int], None], cycles: int | None = None, sleep=time.sleep) -> None:
    """Call step(cycle) every `interval` seconds. Stops after `cycles`, or never if None."""
    cycle = 0
    while cycles is None or cycle < cycles:
        cycle += 1
        try:
            step(cycle)
        except Exception as error:  # e.g. the disk is full; try again next beat
            print(f"cycle {cycle} failed: {type(error).__name__}: {error}", flush=True)
        if cycles is None or cycle < cycles:
            sleep(interval - time.time() % interval)
