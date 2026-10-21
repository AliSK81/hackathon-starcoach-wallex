"""Textbook indicators on plain lists of floats. Oldest value first.

Each function returns a list as long as its input. Values before an
indicator has enough data are None. Smoothing follows Wilder (RSI, ATR, ADX),
the same as TA-Lib. Nothing here looks at future values.
"""

import math


def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(n - 1, len(values)):
        out[i] = sum(values[i - n + 1 : i + 1]) / n
    return out


def ema(values: list[float], n: int) -> list[float | None]:
    """Exponential average with alpha 2/(n+1), started from the first n-value average."""
    return _smooth(values, n, 2 / (n + 1))


def wilder(values: list[float], n: int) -> list[float | None]:
    """Wilder's average: alpha 1/n, started from the first n-value average."""
    return _smooth(values, n, 1 / n)


def _smooth(values: list[float | None], n: int, alpha: float) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    # Skip leading Nones, so a smoothed series can be smoothed again (MACD signal, ADX).
    first = next((i for i, v in enumerate(values) if v is not None), len(values))
    if len(values) - first < n:
        return out
    prev = sum(values[first : first + n]) / n
    out[first + n - 1] = prev
    for i in range(first + n, len(values)):
        prev += alpha * (values[i] - prev)
        out[i] = prev
    return out


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = wilder([max(c, 0.0) for c in changes], n)
    losses = wilder([max(-c, 0.0) for c in changes], n)
    for i, (g, l) in enumerate(zip(gains, losses), start=1):
        if g is not None:
            out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    out = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        out.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> list[float | None]:
    return wilder(true_range(highs, lows, closes), n)


def adx(highs: list[float], lows: list[float], closes: list[float], n: int = 14):
    """Returns three lists: ADX, +DI and -DI."""
    size = len(closes)
    plus_dm, minus_dm = [0.0], [0.0]
    for i in range(1, size):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    tr = wilder(true_range(highs, lows, closes)[1:], n)
    plus_s, minus_s = wilder(plus_dm[1:], n), wilder(minus_dm[1:], n)
    plus_di: list[float | None] = [None] * size
    minus_di: list[float | None] = [None] * size
    dx: list[float | None] = [None] * size
    for i in range(1, size):
        t, p, m = tr[i - 1], plus_s[i - 1], minus_s[i - 1]
        if t is None:
            continue
        plus_di[i] = 100 * p / t if t else 0.0
        minus_di[i] = 100 * m / t if t else 0.0
        total = plus_di[i] + minus_di[i]
        dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / total if total else 0.0
    return _smooth(dx, n, 1 / n), plus_di, minus_di


def macd_hist(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> list[float | None]:
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line = [f - s if f is not None and s is not None else None for f, s in zip(fast_ema, slow_ema)]
    sig = _smooth(line, signal, 2 / (signal + 1))
    return [l - s if l is not None and s is not None else None for l, s in zip(line, sig)]


def stdev(values: list[float]) -> float:
    """Population standard deviation, as Bollinger bands use."""
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def zscore(values: list[float], n: int) -> float | None:
    """How many standard deviations the last value is from the n-value average."""
    if len(values) < n:
        return None
    window = values[-n:]
    sd = stdev(window)
    return (window[-1] - sum(window) / n) / sd if sd else 0.0


def percent_rank(values: list[float], n: int) -> float | None:
    """Share of the previous n-1 values that are below the last one, from 0 to 1."""
    if len(values) < n:
        return None
    window = values[-n:]
    return sum(v < window[-1] for v in window[:-1]) / (n - 1)
