import argparse

from wx import __version__
from wx.config import KEYS, Settings


def status(settings: Settings) -> str:
    lines = [f"wx {__version__}"]
    for name in KEYS:
        lines.append(f"  {name}: {'set' if settings.is_set(name) else 'missing'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wx", description="Wallex trading bot.")
    parser.add_argument("--version", action="version", version=f"wx {__version__}")
    parser.parse_args(argv)
    print(status(Settings.load()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
