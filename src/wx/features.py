"""Indicators for one market, ready for the AI.

Hourly indicators use closed 1-hour candles only. Returns use the 1-minute
candles and the live mid price. Every feature has a fixed name, so the AI can
cite it and code can check it. FEATURES says what each one means.
"""

import bisect
import time
from decimal import Decimal
from pathlib import Path
from statistics import median

from wx import indicators as ind
from wx.candles import SIZES, candle_path, load_candles, update_candles
from wx.setups import active
from wx.wallex import fetch_best_prices

HOUR = 3600
MINUTE = 60

# EMA 200 needs a long warm-up. With 1000 hours, how it starts no longer matters.
# The typical 24-hour move needs 30 days plus one day: 744 hours.
MIN_HOURS = 750
HOURS_USED = 1000
# Live features need this much history: 1000 hours, and 5000 minutes. A new market downloads only this
# (seconds), not the 120 days `wx candles` keeps for tests on the past.
LIVE_DAYS = {"1m": 4, "1h": 43}

# Name -> what it means. The AI will see these words. Order is the print order.
FEATURES = {
    "price": "live mid price (between best bid and best ask)",
    "spread_pct": "live gap between best ask and best bid, % of price",
    "round_trip_cost_pct": "cost of a buy then a sell as taker: 2 fees + spread, % (empty without a Wallex key)",
    "ret_15m_pct": "price change over the last 15 minutes, %",
    "ret_1h_pct": "price change over the last hour, %",
    "ret_4h_pct": "price change over the last 4 hours, %",
    "ret_24h_pct": "price change over the last 24 hours, %",
    "ret_72h_pct": "price change over the last 72 hours, %",
    "typical_24h_move_pct": "usual size of a 24-hour price change, up or down, over the last 30 days, %",
    "ema20_vs_ema50_pct": "1h EMA 20 above (+) or below (-) EMA 50, %",
    "price_vs_ema200_pct": "last 1h close above (+) or below (-) EMA 200, %",
    "ema20_slope_5h_pct": "change of the 1h EMA 20 over the last 5 hours, %",
    "rsi14": "1h RSI 14: above 70 is overbought, below 30 is oversold",
    "macd_hist_pct": "1h MACD histogram (12, 26, 9), % of price. Above 0 means momentum is rising",
    "adx14": "1h ADX 14, trend strength: above 25 is a trend, below 20 is a range",
    "plus_di14": "1h +DI 14, strength of up moves",
    "minus_di14": "1h -DI 14, strength of down moves",
    "atr14_pct": "1h ATR 14, the usual size of one hour's move, % of price",
    "atr_pctile_100": "where ATR 14 % sits among the last 100 hours, 0 (calmest) to 1 (wildest)",
    "zscore_48h": "last 1h close minus its 48-hour average, in standard deviations",
    "bb_z_20": "last 1h close minus its 20-hour average, in 20-hour standard deviations (below -2 is a deep dip)",
    "trend_4h_pct": "4h EMA 20 above (+) or below (-) the 4h EMA 50, %: the slower trend",
    "rsi14_15m": "15-minute RSI 14, the short-term push",
    "ret_5m_pct": "price change over the last 5 minutes, %",
    "ret_30m_pct": "price change over the last 30 minutes, %",
    "ema9_vs_ema21_5m_pct": "5-minute EMA 9 above (+) or below (-) the EMA 21, %: the fast trend",
    "rsi14_5m": "5-minute RSI 14",
    "bb_z_5m": "last 5-minute close minus its 20-bar average, in standard deviations",
    "atr14_5m_pct": "5-minute ATR 14, the usual size of one 5-minute move, % of price",
    "vol_ratio_5m": "last 5 minutes' volume divided by the average 5 minutes of the last 4 hours",
    "vwap_4h_dev_pct": "price above (+) or below (-) the volume-weighted average price of the last 4 hours, %",
    "range_1h_pct": "high minus low of the last 60 minutes, % of the low",
    "pos_in_1h_range": "where the price sits in the last 60 minutes' range: 0 = low, 1 = high",
    "bb_pos_20": "last 1h close inside the Bollinger bands (20, 2): 0 = lower band, 1 = upper band",
    "donchian20_pos": "last 1h close inside the previous 20 hours' low-high range: 0 = low, 1 = high",
    "breakout_up": "true if the last 1h close is above the previous 20 hours' high",
    "vol_ratio_20": "last 1h volume divided by the average of the 20 hours before",
    "zero_volume_hours_24": "hours with no trades in the last 24",
    "regime": "trend_up / trend_down (ADX above 25), range (ADX below 20), or transition",
    "data_age_min": "minutes since the newest saved 1-minute candle started",
    "usdt_trend_up": "true if USDTTMN's 1h EMA 20 is above its EMA 50: the Toman is weakening (null if unknown)",
    "btc_ret_24h_pct": "BTCTMN's price change over the last 24 hours, %: the whole market's mood (null if unknown)",
    "setups": "buy setups whose rule holds now (see setup_meanings). A BUY must name one of these",
}


def closed_bars(candles: dict[int, list], seconds: int, now: int) -> list[list[float]]:
    """Candles that have closed by `now`, oldest first, as floats [t, o, h, l, c, v]."""
    return [[float(x) for x in candles[t]] for t in sorted(candles) if t + seconds <= now]


def pct(a: float | None, b: float | None, digits: int = 2) -> float | None:
    """a above b, in % of b."""
    if a is None or not b:
        return None
    return round((a / b - 1) * 100, digits)


def rnd(x: float | None, digits: int) -> float | None:
    return None if x is None else round(x, digits)


def fast_features(minutes: list[list[float]], price: float) -> dict:
    """Features from 1-minute candles for short-term trading: 5-minute bars, the last hour, the last 4 hours."""
    names = ("ret_5m_pct", "ret_30m_pct", "ema9_vs_ema21_5m_pct", "rsi14_5m", "bb_z_5m", "atr14_5m_pct",
             "vol_ratio_5m", "vwap_4h_dev_pct", "range_1h_pct", "pos_in_1h_range")
    if len(minutes) < 300:
        return dict.fromkeys(names)
    chunks = [minutes[i - 5:i] for i in range(len(minutes), 4, -5)][::-1]  # 5-minute bars, newest last
    c5 = [ch[-1][4] for ch in chunks]
    h5 = [max(m[2] for m in ch) for ch in chunks]
    l5 = [min(m[3] for m in ch) for ch in chunks]
    v5 = [sum(m[5] for m in ch) for ch in chunks]
    e9, e21 = ind.ema(c5, 9), ind.ema(c5, 21)
    atr5 = ind.atr(h5, l5, c5, 14)
    sd = ind.stdev(c5[-20:])
    hour, four = minutes[-60:], minutes[-240:]
    hi, lo = max(m[2] for m in hour), min(m[3] for m in hour)
    vol4 = sum(m[5] for m in four)
    vwap = sum(m[4] * m[5] for m in four) / vol4 if vol4 else None
    avg5 = sum(v5[-49:-1]) / 48 if len(v5) > 48 else None
    return {
        "ret_5m_pct": pct(price, minutes[-5][4]), "ret_30m_pct": pct(price, minutes[-30][4]),
        "ema9_vs_ema21_5m_pct": pct(e9[-1], e21[-1], 3),
        "rsi14_5m": rnd(ind.rsi(c5, 14)[-1], 1),
        "bb_z_5m": rnd((c5[-1] - sum(c5[-20:]) / 20) / sd, 2) if sd else 0.0,
        "atr14_5m_pct": rnd(atr5[-1] / c5[-1] * 100, 3) if atr5[-1] else None,
        "vol_ratio_5m": rnd(v5[-1] / avg5, 2) if avg5 else None,
        "vwap_4h_dev_pct": pct(price, vwap) if vwap else None,
        "range_1h_pct": pct(hi, lo), "pos_in_1h_range": rnd((price - lo) / (hi - lo), 2) if hi > lo else 0.5,
    }


def build_features(hours: list[list[float]], minutes: list[list[float]], bid: Decimal, ask: Decimal,
                   now: int, taker_fee: float | None = None) -> dict:
    """All FEATURES for one market.

    hours and minutes are closed candles, oldest first. Needs MIN_HOURS hours.
    """
    if len(hours) < MIN_HOURS:
        raise ValueError(f"need {MIN_HOURS} closed 1-hour candles, have {len(hours)}")
    if not minutes:
        raise ValueError("no closed 1-minute candles")
    hours = hours[-HOURS_USED:]
    _, _, highs, lows, closes, volumes = (list(col) for col in zip(*hours))
    last = closes[-1]
    mid = (bid + ask) / 2
    price = float(mid)
    spread_pct = float((ask - bid) / mid * 100)

    # Close of the last 1-minute candle that ended by `when`.
    starts = [m[0] for m in minutes]

    def close_at(when: float) -> float | None:
        i = bisect.bisect_right(starts, when - MINUTE)
        return minutes[i - 1][4] if i else None

    ema20, ema50, ema200 = ind.ema(closes, 20), ind.ema(closes, 50), ind.ema(closes, 200)
    adx, plus_di, minus_di = ind.adx(highs, lows, closes, 14)
    atr = ind.atr(highs, lows, closes, 14)
    atr_pct = [a / c * 100 for a, c in zip(atr, closes) if a is not None]
    sd20 = ind.stdev(closes[-20:])
    mean20 = sum(closes[-20:]) / 20
    band = 4 * sd20  # upper band minus lower band
    high20, low20 = max(highs[-21:-1]), min(lows[-21:-1])
    vol_avg20 = sum(volumes[-21:-1]) / 20
    slope = pct(ema20[-1], ema20[-6], 3)
    adx_now = adx[-1]
    if adx_now > 25:
        regime = "trend_up" if slope > 0 else "trend_down"
    elif adx_now < 20:
        regime = "range"
    else:
        regime = "transition"

    # Slower and faster views: every 4th hourly close, and every 15th minute close, ending with the newest.
    closes_4h = closes[::-4][::-1]
    ema20_4h, ema50_4h = ind.ema(closes_4h, 20), ind.ema(closes_4h, 50)
    rsi_15m = ind.rsi([m[4] for m in minutes[::-15]][::-1], 14)
    fast = fast_features(minutes[-1500:], price)

    features = {
        "price": price,
        "spread_pct": round(spread_pct, 3),
        "round_trip_cost_pct": None if taker_fee is None else round(2 * taker_fee * 100 + spread_pct, 3),
        "ret_15m_pct": pct(price, close_at(now - 15 * MINUTE)),
        "ret_1h_pct": pct(price, close_at(now - HOUR)),
        "ret_4h_pct": pct(price, close_at(now - 4 * HOUR)),
        "ret_24h_pct": pct(price, close_at(now - 24 * HOUR)),
        "ret_72h_pct": pct(price, close_at(now - 72 * HOUR)),
        "typical_24h_move_pct": rnd(median(abs(closes[i] / closes[i - 24] - 1) * 100
                                           for i in range(len(closes) - 720, len(closes))), 2),
        "ema20_vs_ema50_pct": pct(ema20[-1], ema50[-1]),
        "price_vs_ema200_pct": pct(last, ema200[-1]),
        "ema20_slope_5h_pct": slope,
        "rsi14": rnd(ind.rsi(closes, 14)[-1], 1),
        "macd_hist_pct": rnd(ind.macd_hist(closes)[-1] / last * 100, 3),
        "adx14": rnd(adx_now, 1),
        "plus_di14": rnd(plus_di[-1], 1),
        "minus_di14": rnd(minus_di[-1], 1),
        "atr14_pct": rnd(atr_pct[-1], 3),
        "atr_pctile_100": rnd(ind.percent_rank(atr_pct, 100), 2),
        "zscore_48h": rnd(ind.zscore(closes, 48), 2),
        "bb_z_20": rnd((last - mean20) / sd20, 2) if sd20 else 0.0,
        "trend_4h_pct": pct(ema20_4h[-1], ema50_4h[-1]) if ema50_4h[-1] else None,
        "rsi14_15m": rnd(rsi_15m[-1], 1),
        **fast,
        "bb_pos_20": rnd((last - (mean20 - 2 * sd20)) / band, 2) if band else 0.5,
        "donchian20_pos": rnd((last - low20) / (high20 - low20), 2) if high20 > low20 else 0.5,
        "breakout_up": last > high20,
        "vol_ratio_20": rnd(volumes[-1] / vol_avg20, 2) if vol_avg20 else None,
        "zero_volume_hours_24": sum(v == 0 for v in volumes[-24:]),
        "regime": regime,
        "data_age_min": round((now - minutes[-1][0]) / 60, 1),
        "usdt_trend_up": None,
        "btc_ret_24h_pct": None,
    }
    features["setups"] = active(features)
    return features


def add_context(table: dict[str, dict]) -> dict[str, dict]:
    """Copy the whole-market facts into every market, then check the setups again.

    The Toman's own trend (USDTTMN) and BTC's day tell every market something:
    coin trend buys did worse while the Toman was getting stronger (F41).
    """
    usdt, btc = table.get("USDTTMN"), table.get("BTCTMN")
    for f in table.values():
        if usdt and usdt.get("ema20_vs_ema50_pct") is not None:
            f["usdt_trend_up"] = usdt["ema20_vs_ema50_pct"] > 0
        if btc:
            f["btc_ret_24h_pct"] = btc.get("ret_24h_pct")
        f["setups"] = active(f)
    return table


def market_features(symbol: str, data_dir: Path, taker_fee: float | None = None, now: int | None = None) -> dict:
    """Bring the saved candles up to date, read the live book, and build the features."""
    for size in SIZES:
        update_candles(symbol, size, data_dir, LIVE_DAYS[size])
    bid, ask = fetch_best_prices(symbol)
    now = now or int(time.time())
    hours = closed_bars(load_candles(candle_path(data_dir, symbol, "1h")), HOUR, now)
    minutes = closed_bars(load_candles(candle_path(data_dir, symbol, "1m")), MINUTE, now)
    return build_features(hours, minutes[-5000:], bid, ask, now, taker_fee)
