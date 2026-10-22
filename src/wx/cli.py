import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from wx import __version__
from wx.account import fee_groups, nonzero_balances, save_account
from wx.beat import every
from wx.candles import DEFAULT_SYMBOLS, KEEP_DAYS, SIZES, update_candles
from wx.config import KEYS, Settings
from wx.decide import code_version, decide, holdings, log_decision
from wx.features import FEATURES, market_features
from wx.llm import LLMError, chat, parse_json
from wx.markets import allowed_markets, load_inactive, save_snapshot, tmn_volume, top_by_volume
from wx.prices import watch
from wx.replay import History, run_replay, sample_times, summary
from wx.rules import MarketRules
from wx.wallex import WallexError, fetch_balances, fetch_best_prices, fetch_fees, fetch_markets

DATA_DIR = Path("data")

# Seconds between decisions in `wx run`. See DECISIONS D19.
DECIDE_EVERY = 900


def status(settings: Settings) -> str:
    lines = [f"wx {__version__}"]
    for name in KEYS:
        lines.append(f"  {name}: {'set' if settings.is_set(name) else 'missing'}")
    return "\n".join(lines)


def markets_report(markets: dict[str, dict], allowed: dict[str, dict], top: int = 10) -> str:
    lines = [
        f"Wallex lists {len(markets)} markets.",
        f"Allowed: {len(allowed)}. Forbidden: {len(markets) - len(allowed)}.",
        f"Top {top} allowed by 24h volume (million Toman):",
    ]
    for symbol in top_by_volume(allowed, top):
        lines.append(f"  {symbol:<12} {tmn_volume(allowed[symbol]) / 1_000_000:>12,.0f}")
    return "\n".join(lines)


def run_markets() -> int:
    try:
        markets = fetch_markets()
    except WallexError as error:
        print(f"Could not read markets: {error}")
        return 1
    allowed = allowed_markets(markets, load_inactive())
    print(markets_report(markets, allowed))
    print(f"Saved: {save_snapshot(markets, DATA_DIR)}")
    return 0


def pick_markets(symbols: list[str]) -> dict[str, dict] | None:
    """Wallex info for the symbols (default list if empty), in order.

    None if Wallex can't be read or any symbol is refused.
    """
    symbols = [s.upper() for s in symbols] or list(DEFAULT_SYMBOLS)
    try:
        allowed = allowed_markets(fetch_markets(), load_inactive())
    except WallexError as error:
        print(f"Could not read markets: {error}")
        return None
    refused = [s for s in symbols if s not in allowed]
    if refused:
        print(f"Not allowed or not on Wallex: {', '.join(refused)}")
        return None
    return {s: allowed[s] for s in symbols}


def run_candles(symbols: list[str], days: int) -> int:
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    symbols = list(markets)
    failed = 0
    for symbol in symbols:
        for size in SIZES:
            try:
                added = update_candles(symbol, size, DATA_DIR, days)
                print(f"  {symbol:<10} {size}: {added:>6} new candles")
            except WallexError as error:
                failed += 1
                print(f"  {symbol:<10} {size}: failed, kept what we had. {error}")
    print(f"Saved in {DATA_DIR / 'candles'}")
    return 1 if failed else 0


def account_report(held: dict[str, dict], fees: dict[str, dict]) -> str:
    lines = ["Balances (not zero):"]
    for asset, b in held.items():
        lines.append(f"  {asset:<8} value {b['value']:>14}  locked {b['locked']:>10}  free {b['free']:>14}")
    if not held:
        lines.append("  none")
    lines.append("Fees (maker / taker):")
    for (quote, maker, taker), count in sorted(fee_groups(fees).items()):
        lines.append(f"  {quote:<5} markets: {maker * 100:.2f}% / {taker * 100:.2f}%  ({count} markets)")
    return "\n".join(lines)


def run_account(settings: Settings) -> int:
    key = settings.get("WALLEX_API_KEY")
    if not key:
        print("WALLEX_API_KEY is missing. Put it in .env.")
        return 1
    try:
        held = nonzero_balances(fetch_balances(key))
        fees = fetch_fees(key)
    except WallexError as error:
        print(f"Could not read the account: {error}")
        return 1
    print(account_report(held, fees))
    print(f"Saved: {save_account(held, fees, DATA_DIR)}")
    return 0


def rules_report(rules: list[MarketRules]) -> str:
    lines = [f"{'Market':<10} {'Qty dec':>7} {'Price dec':>9} {'Min qty':>10} {'Min order':>10}  MARKET flag"]
    for r in rules:
        min_order = f"{r.min_notional} {r.quote}"
        lines.append(
            f"{r.symbol:<10} {r.qty_decimals:>7} {r.price_decimals:>9} {r.min_qty:>10f} {min_order:>10}  "
            f"{'on' if r.market_orders else 'off'}"
        )
    return "\n".join(lines)


def run_rules(symbols: list[str]) -> int:
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    print(rules_report([MarketRules.from_wallex(info) for info in markets.values()]))
    return 0


def features_report(table: dict[str, dict]) -> str:
    """One row per feature, one column per market."""
    symbols = list(table)
    lines = [f"{'':<22}" + "".join(f"{s:>14}" for s in symbols)]
    for name in FEATURES:
        cells = []
        for s in symbols:
            value = table[s][name]
            if isinstance(value, float) and name == "price":
                value = f"{value:,.0f}" if value >= 1000 else f"{value:g}"
            cells.append(f"{'-' if value is None else str(value):>14}")
        lines.append(f"{name:<22}" + "".join(cells))
    return "\n".join(lines)


def taker_fees(settings: Settings) -> dict[str, float]:
    """Taker fee per market, or nothing if the key is missing or Wallex fails."""
    key = settings.get("WALLEX_API_KEY")
    if not key:
        print("No WALLEX_API_KEY, so no round-trip cost.")
        return {}
    try:
        return {s: float(r["takerFeeRate"]) for s, r in fetch_fees(key).items()}
    except WallexError as error:
        print(f"Could not read fees, so no round-trip cost: {error}")
        return {}


def collect_features(symbols, settings: Settings) -> tuple[dict[str, dict], dict[str, str]]:
    """Features and errors, each keyed by market. One bad market never stops the rest."""
    fees = taker_fees(settings)
    table, errors = {}, {}
    for symbol in symbols:
        try:
            table[symbol] = market_features(symbol, DATA_DIR, fees.get(symbol))
        except (WallexError, ValueError) as error:
            errors[symbol] = str(error)
            print(f"  {symbol}: failed. {error}")
    return table, errors


def run_features(symbols: list[str], settings: Settings) -> int:
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    table, errors = collect_features(markets, settings)
    if table:
        print(features_report(table))
    return 1 if errors else 0


def missing_ai_settings(settings: Settings) -> bool:
    missing = [k for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY") if not settings.is_set(k)]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}")
    return bool(missing)


def decision_report(record: dict) -> str:
    lines = []
    if record["error"]:
        lines.append(f"The AI failed, so every market is HOLD: {record['error']}")
    if record["ai"]:
        ai = record["ai"]
        lines.append(f"Model {ai['model']} answered in {ai['seconds']} s. Tokens: {ai['usage'].get('total_tokens', 'unknown')}.")
    if record["market_view"]:
        lines.append(f"Market view: {record['market_view']}")
    for d in record["decisions"]:
        lines.append(f"  {d['symbol']:<9} {d['action']:<4} {d['confidence']:.2f}  {d['reason']}")
        if d["cited"]:
            lines.append("            cited: " + ", ".join(f"{k}={v}" for k, v in d["cited"].items()))
        for problem in d["problems"]:
            lines.append(f"            problem: {problem}")
    for problem in record["problems"]:
        lines.append(f"Problem: {problem}")
    return "\n".join(lines)


def decision_cycle(markets: dict[str, dict], settings: Settings, cycle: int | None = None) -> dict:
    """Features, account, one AI decision, and the log line. Returns the record."""
    table, feature_errors = collect_features(markets, settings)
    record = {"cycle": cycle, "version": code_version(), "markets": table, "feature_errors": feature_errors,
              "cash_tmn": None, "held": {}, "account_error": None}
    if not table:
        record.update(driver="none", error="no market has features", ai=None, decisions=[])
        path = log_decision(DATA_DIR, record)
        print(f"No market has features, so no decision. Logged: {path}")
        return record
    key = settings.get("WALLEX_API_KEY")
    try:
        if not key:
            raise WallexError("no WALLEX_API_KEY")
        rules = {s: MarketRules.from_wallex(info) for s, info in markets.items()}
        record["cash_tmn"], record["held"] = holdings(fetch_balances(key), rules, table)
    except WallexError as error:
        record["account_error"] = str(error)
        print(f"Could not read the account, so the AI is told cash is unknown and we hold nothing: {error}")
    base_url, model = settings.get("LLM_BASE_URL"), settings.get("LLM_MODEL")
    print(f"Asking {model} about {len(table)} markets ...")
    record.update(decide(table, record["cash_tmn"], record["held"],
                         lambda messages: chat(base_url, model, settings.get("LLM_API_KEY"), messages, json_mode=True)))
    path = log_decision(DATA_DIR, record)
    print(decision_report(record))
    print(f"Logged: {path}")
    return record


def run_decide(symbols: list[str], settings: Settings) -> int:
    if missing_ai_settings(settings):
        return 1
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    record = decision_cycle(markets, settings)
    return 0 if record["driver"] == "ai" and not record["feature_errors"] else 1


def run_loop(symbols: list[str], settings: Settings, interval: int, cycles: int | None) -> int:
    """`wx run`: a decision on every beat. No orders. Every cycle is logged, even a failed one."""
    if missing_ai_settings(settings):
        return 1
    markets = pick_markets(symbols)
    if markets is None:
        return 1

    def step(cycle: int) -> None:
        print(f"--- cycle {cycle} at {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
        try:
            decision_cycle(markets, settings, cycle)
        except Exception as error:  # log it, then let the beat report it and go on
            log_decision(DATA_DIR, {"cycle": cycle, "version": code_version(), "driver": "none",
                                    "error": f"{type(error).__name__}: {error}", "ai": None, "decisions": []})
            raise

    print(f"Deciding on {' '.join(markets)} every {interval} s. No orders. "
          f"Log: {DATA_DIR / 'decisions'}. Ctrl+C stops.")
    try:
        every(interval, step, cycles)
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


# Taker fee on TMN markets (DECISIONS F3), used by `wx replay` if fees can't be read.
TMN_TAKER_FEE = 0.003


def run_replay_cmd(symbols: list[str], settings: Settings, moments: int, days: int, seed: int, workers: int) -> int:
    if missing_ai_settings(settings):
        return 1
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    now = int(time.time())
    histories = {s: History.load(DATA_DIR, s, now) for s in markets}
    newest = int(min(h.minutes[-1][0] for h in histories.values() if h.minutes))
    times = sample_times(newest - days * 86400, newest - 86400, moments, seed)
    spreads = {}
    for s in markets:
        try:
            bid, ask = fetch_best_prices(s)
            spreads[s] = float((ask - bid) / ((ask + bid) / 2) * 100)
        except WallexError:
            spreads[s] = 0.3
            print(f"  {s}: could not read the book, so the spread is taken as 0.3%")
    fees = taker_fees(settings) or {s: TMN_TAKER_FEE for s in markets}
    base_url, model = settings.get("LLM_BASE_URL"), settings.get("LLM_MODEL")
    log = DATA_DIR / "replay" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
    print(f"Replaying {len(times)} moments from the last {days} days (seed {seed}), {workers} at a time. Log: {log}")
    results = run_replay(times, histories, spreads, fees,
                         lambda messages: chat(base_url, model, settings.get("LLM_API_KEY"), messages, json_mode=True),
                         log, workers)
    print(summary(results))
    return 0


AI_CHECK = [
    {"role": "system", "content": "You are a trading assistant. Reply only with one JSON object."},
    {
        "role": "user",
        "content": 'BTC rose 2% in the last hour and RSI(14) is 72. '
        'Reply with {"action": "BUY" or "SELL" or "HOLD", "reason": "<one sentence>"}.',
    },
]


def run_ai(settings: Settings) -> int:
    if missing_ai_settings(settings):
        return 1
    base_url = settings.get("LLM_BASE_URL")
    print(f"Asking {settings.get('LLM_MODEL')} at {urlparse(base_url).netloc} ...")
    try:
        reply = chat(base_url, settings.get("LLM_MODEL"), settings.get("LLM_API_KEY"), AI_CHECK, json_mode=True)
        answer = parse_json(reply.text)
    except LLMError as error:
        print(f"The AI check failed: {error}")
        return 1
    tokens = reply.usage.get("total_tokens", "unknown")
    print(f"Model: {reply.model}. Answered in {reply.seconds} s. Tokens: {tokens}.")
    print(f"Answer: {json.dumps(answer, ensure_ascii=False)}")
    print(f"Reasoning sent: {'yes, ' + str(len(reply.reasoning)) + ' characters' if reply.reasoning else 'no'}")
    return 0


def run_watch(symbols: list[str], interval: int, cycles: int | None) -> int:
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    symbols = list(markets)
    print(f"Watching {' '.join(symbols)} every {interval} s. Log: {DATA_DIR / 'prices'}. Ctrl+C stops.")
    try:
        watch(symbols, DATA_DIR, interval, cycles)
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wx", description="Wallex trading bot.")
    parser.add_argument("--version", action="version", version=f"wx {__version__}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("markets", help="list allowed markets and save a snapshot")
    candles = commands.add_parser("candles", help="save 1-minute and 1-hour candles")
    candles.add_argument("symbols", nargs="*", help=f"default: {' '.join(DEFAULT_SYMBOLS)}")
    candles.add_argument("--days", type=int, default=KEEP_DAYS, help=f"how far back to keep (default {KEEP_DAYS})")
    watcher = commands.add_parser("watch", help="read live prices on a fixed beat and log them")
    watcher.add_argument("symbols", nargs="*", help=f"default: {' '.join(DEFAULT_SYMBOLS)}")
    watcher.add_argument("--interval", type=int, default=60, help="seconds between cycles (default 60)")
    watcher.add_argument("--cycles", type=int, default=None, help="stop after this many cycles (default: never)")
    commands.add_parser("account", help="read balances and fees (needs WALLEX_API_KEY)")
    rules = commands.add_parser("rules", help="show decimals and minimum order size per market")
    rules.add_argument("symbols", nargs="*", help=f"default: {' '.join(DEFAULT_SYMBOLS)}")
    commands.add_parser("ai", help="check the AI settings with one small call")
    decider = commands.add_parser("decide", help="one AI decision per market, checked and logged (no orders)")
    decider.add_argument("symbols", nargs="*", help=f"default: {' '.join(DEFAULT_SYMBOLS)}")
    replayer = commands.add_parser("replay", help="ask the AI about past moments and see what happened next")
    replayer.add_argument("symbols", nargs="*", help=f"default: {' '.join(DEFAULT_SYMBOLS)}")
    replayer.add_argument("--moments", type=int, default=40, help="how many past moments (default 40)")
    replayer.add_argument("--days", type=int, default=60, help="pick moments from the last N days (default 60)")
    replayer.add_argument("--seed", type=int, default=7, help="picks the same moments again (default 7)")
    replayer.add_argument("--workers", type=int, default=4, help="AI calls at the same time (default 4)")
    runner = commands.add_parser("run", help="decide on a fixed beat and log every cycle (no orders)")
    runner.add_argument("symbols", nargs="*", help=f"default: {' '.join(DEFAULT_SYMBOLS)}")
    runner.add_argument("--interval", type=int, default=DECIDE_EVERY,
                        help=f"seconds between cycles (default {DECIDE_EVERY})")
    runner.add_argument("--cycles", type=int, default=None, help="stop after this many cycles (default: never)")
    features = commands.add_parser("features", help="indicators per market, from candles and the live book")
    features.add_argument("symbols", nargs="*", help=f"default: {' '.join(DEFAULT_SYMBOLS)}")
    args = parser.parse_args(argv)
    # Wallex messages can be in Persian. Never crash on a console that can't show them.
    # Print each line at once, so a long run's output is never held back.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace", line_buffering=True)
    if args.command == "account":
        return run_account(Settings.load())
    if args.command == "ai":
        return run_ai(Settings.load())
    if args.command == "replay":
        return run_replay_cmd(args.symbols, Settings.load(), args.moments, args.days, args.seed, args.workers)
    if args.command == "run":
        return run_loop(args.symbols, Settings.load(), args.interval, args.cycles)
    if args.command == "decide":
        return run_decide(args.symbols, Settings.load())
    if args.command == "features":
        return run_features(args.symbols, Settings.load())
    if args.command == "markets":
        return run_markets()
    if args.command == "candles":
        return run_candles(args.symbols, args.days)
    if args.command == "watch":
        return run_watch(args.symbols, args.interval, args.cycles)
    if args.command == "rules":
        return run_rules(args.symbols)
    print(status(Settings.load()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
