"""How each buy setup did in the past, without the AI.

Every hour in the saved history, the features are rebuilt as they were then.
Where a setup is active, we pretend to buy and play the trade out with
trade(): the setup's own exit, the stop, the costs. At most one entry per
market per setup per day, so one move is not counted many times.
"""

from statistics import mean, stdev

from wx.features import HOUR, MIN_HOURS
from wx.replay import STOP_ATR, Lookup
from wx.setups import SETUPS
from wx.trades import History, trade

DAY = 24 * HOUR
NO_STOP = 99.0  # a stop this far below the entry is never hit


def scan(histories: dict[str, History], spreads: dict[str, float], fees: dict[str, float]) -> list[dict]:
    """Features at every hour where the history allows. One row per market and hour."""
    rows = []
    for symbol, history in histories.items():
        if len(history.hours) <= MIN_HOURS:
            continue
        start = int(history.hours[MIN_HOURS][0]) + HOUR
        for t in range(start - start % HOUR, history.end - HOUR, HOUR):
            try:
                features = history.features_at(t, spreads[symbol], fees.get(symbol))
            except ValueError:
                continue
            rows.append({"symbol": symbol, "t": t, "features": features})
    return rows


def lookup_from(rows: list[dict]) -> Lookup:
    """lookup(symbol, hour) over the scanned rows."""
    table = {(r["symbol"], r["t"]): r["features"] for r in rows}
    return lambda symbol, t: table.get((symbol, t))


def entries(rows: list[dict], setup: str | None) -> list[dict]:
    """Rows where the setup is active (any setup if None), at most one per market per day."""
    picked, last = [], {}
    for row in sorted(rows, key=lambda r: (r["symbol"], r["t"])):
        on = row["features"]["setups"] if setup is None else setup in row["features"]["setups"]
        if on and row["t"] - last.get(row["symbol"], -DAY) >= DAY:
            picked.append(row)
            last[row["symbol"]] = row["t"]
    return picked


def play(row: dict, setup: str, histories: dict[str, History], lookup: Lookup, stop_atr: float = STOP_ATR):
    """The trade for one entry row, with taker orders."""
    f = row["features"]
    return trade(histories[row["symbol"]], setup, row["t"], f, stop_atr * f["atr14_pct"], "taker",
                 lambda h: lookup(row["symbol"], h))


class SetupRecord:
    """Each setup's past trades, to tell the AI how a setup did, using only data from before a moment.

    A trade counts once it has closed. Results use the stop (STOP_ATR) and are net of costs.
    """

    def __init__(self, rows: list[dict], histories: dict[str, History]):
        lookup = lookup_from(rows)
        self.results = {name: [play(r, name, histories, lookup) for r in entries(rows, name)] for name in SETUPS}

    def at(self, t: int) -> dict:
        record = {}
        for name, trades in self.results.items():
            nets = [x.net_pct for x in trades if x.exit_t <= t]
            record[name] = {
                "trades": len(nets),
                "average_net_pct": round(mean(nets), 2) if nets else None,
                "made_money_pct": round(100 * sum(n > 0 for n in nets) / len(nets)) if nets else None,
            }
        return record


def stats(nets: list[float]) -> str:
    if not nets:
        return "no entries"
    se = stdev(nets) / len(nets) ** 0.5 if len(nets) > 1 else 0.0
    return f"{mean(nets):+.2f}% (win {sum(n > 0 for n in nets) / len(nets):.0%}, +/- {se:.2f})"


def report(rows: list[dict], histories: dict[str, History], stops: list[float]) -> str:
    """Per setup: entries, and the average net result with no stop and with each stop, by half of the period."""
    if not rows:
        return "No hours to study."
    lookup = lookup_from(rows)
    middle = sorted(r["t"] for r in rows)[len(rows) // 2]
    days = (max(r["t"] for r in rows) - min(r["t"] for r in rows)) / DAY
    lines = [f"{len(rows)} market-hours over {days:.0f} days. Each entry is played out through its setup's exit. "
             f"Net = after the round-trip cost (taker). +/- is one standard error."]
    for name, setup in SETUPS.items():
        picked = entries(rows, name)
        lines.append(f"{name}: {len(picked)} entries. Exit: {setup.exit_meaning}.")
        for stop in [NO_STOP, *stops]:
            results = [(r["t"], play(r, name, histories, lookup, stop).net_pct) for r in picked]
            label = "no stop" if stop == NO_STOP else f"stop {stop:g} ATR"
            first = [n for t, n in results if t < middle]
            second = [n for t, n in results if t >= middle]
            lines.append(f"  {label:<11} all {stats([n for _, n in results])}  "
                         f"| 1st half {stats(first)}  | 2nd half {stats(second)}")
    return "\n".join(lines)
