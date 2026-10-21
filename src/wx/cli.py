import argparse
from pathlib import Path

from wx import __version__
from wx.config import KEYS, Settings
from wx.markets import allowed_markets, load_inactive, save_snapshot, tmn_volume, top_by_volume
from wx.wallex import WallexError, fetch_markets

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wx", description="Wallex trading bot.")
    parser.add_argument("--version", action="version", version=f"wx {__version__}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("markets", help="list allowed markets and save a snapshot")
    args = parser.parse_args(argv)
    if args.command == "markets":
        return run_markets()
    print(status(Settings.load()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
