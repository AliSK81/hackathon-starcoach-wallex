import argparse
import sys
from pathlib import Path

from wx import __version__
from wx.account import fee_groups, nonzero_balances, save_account
from wx.candles import DEFAULT_SYMBOLS, SIZES, update_candles
from wx.config import KEYS, Settings
from wx.markets import allowed_markets, load_inactive, save_snapshot, tmn_volume, top_by_volume
from wx.prices import watch
from wx.wallex import WallexError, fetch_balances, fetch_fees, fetch_markets

DATA_DIR = Path("data")


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


def check_symbols(symbols: list[str]) -> list[str] | None:
    """The symbols in upper case (default list if empty), or None if any is refused."""
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
    return symbols


def run_candles(symbols: list[str], days: int) -> int:
    symbols = check_symbols(symbols)
    if symbols is None:
        return 1
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


def run_watch(symbols: list[str], interval: int, cycles: int | None) -> int:
    symbols = check_symbols(symbols)
    if symbols is None:
        return 1
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
    candles.add_argument("--days", type=int, default=30, help="how far back on the first run (default 30)")
    watcher = commands.add_parser("watch", help="read live prices on a fixed beat and log them")
    watcher.add_argument("symbols", nargs="*", help=f"default: {' '.join(DEFAULT_SYMBOLS)}")
    watcher.add_argument("--interval", type=int, default=60, help="seconds between cycles (default 60)")
    watcher.add_argument("--cycles", type=int, default=None, help="stop after this many cycles (default: never)")
    commands.add_parser("account", help="read balances and fees (needs WALLEX_API_KEY)")
    args = parser.parse_args(argv)
    # Wallex messages can be in Persian. Never crash on a console that can't show them.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    if args.command == "account":
        return run_account(Settings.load())
    if args.command == "markets":
        return run_markets()
    if args.command == "candles":
        return run_candles(args.symbols, args.days)
    if args.command == "watch":
        return run_watch(args.symbols, args.interval, args.cycles)
    print(status(Settings.load()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
