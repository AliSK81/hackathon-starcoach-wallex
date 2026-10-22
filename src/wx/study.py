"""How each buy setup did in the past, without the AI.

Every hour in the saved history, the features are rebuilt as they were then
(as in `wx replay`). Where a setup is active, we pretend to buy and look at
the next 24 hours: held to the end, and with a stop-loss. At most one entry
per market per setup per day, so one move is not counted many times.
"""

from statistics import mean, stdev

from wx.features import HOUR, MIN_HOURS
from wx.replay import HORIZON, History, outcome
from wx.setups import SETUPS


def scan(histories: dict[str, History], spreads: dict[str, float], fees: dict[str, float]) -> list[dict]:
    """Features at every hour where 24 hours of later data exist. One row per market and hour."""
    rows = []
    for symbol, history in histories.items():
        if len(history.hours) <= MIN_HOURS:
            continue
        start = int(history.hours[MIN_HOURS][0]) + HOUR
        end = int(history.minutes[-1][0]) - HORIZON
        for t in range(start - start % HOUR, end, HOUR):
            try:
                features = history.features_at(t, spreads[symbol], fees.get(symbol))
            except ValueError:
                continue
            rows.append({"symbol": symbol, "t": t, "features": features})
    return rows


def entries(rows: list[dict], setup: str | None) -> list[dict]:
    """Rows where the setup is active (any setup if None), at most one per market per day."""
    picked, last = [], {}
    for row in sorted(rows, key=lambda r: (r["symbol"], r["t"])):
        on = row["features"]["setups"] if setup is None else setup in row["features"]["setups"]
        if on and row["t"] - last.get(row["symbol"], -HORIZON) >= HORIZON:
            picked.append(row)
            last[row["symbol"]] = row["t"]
    return picked


def stats(nets: list[float]) -> str:
    if not nets:
        return "no entries"
    se = stdev(nets) / len(nets) ** 0.5 if len(nets) > 1 else 0.0
    return f"{mean(nets):+.2f}% (win {sum(n > 0 for n in nets) / len(nets):.0%}, +/- {se:.2f})"


def report(rows: list[dict], histories: dict[str, History], stops: list[float]) -> str:
    """Per setup: entries, and average net result held 24 hours and with each stop, by half of the period."""
    if not rows:
        return "No hours to study."
    middle = sorted(r["t"] for r in rows)[len(rows) // 2]
    days = (max(r["t"] for r in rows) - min(r["t"] for r in rows)) / 86400
    lines = [f"{len(rows)} market-hours over {days:.0f} days. Buy, then sell after 24 hours or at the stop. "
             f"Net = after the round-trip cost. +/- is one standard error."]
    for name in [*SETUPS, None]:
        picked = entries(rows, name)
        lines.append(f"{name or 'any setup'}: {len(picked)} entries")
        for stop in [None, *stops]:
            results = [(r["t"], outcome(histories[r["symbol"]], r["t"], r["features"], stop)) for r in picked]
            key = "net_stop_pct" if stop else "net_pct"
            label = f"stop {stop:g} ATR" if stop else "no stop"
            first = [o[key] for t, o in results if t < middle]
            second = [o[key] for t, o in results if t >= middle]
            lines.append(f"  {label:<11} all {stats([o[key] for _, o in results])}  "
                         f"| 1st half {stats(first)}  | 2nd half {stats(second)}")
    every = [outcome(histories[r["symbol"]], r["t"], r["features"], None)["net_pct"] for r in rows]
    lines.append(f"Every hour, no stop, for comparison: {stats(every)}")
    return "\n".join(lines)
