import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from wx import __version__
from wx.account import fee_groups, nonzero_balances, save_account
from wx.agent import review_tools
from wx.backtest import scenarios, short_scenarios
from wx.beat import every
from wx.candles import DEFAULT_SYMBOLS, KEEP_DAYS, SIZES, candle_path, last_close, update_candles
from wx.config import KEYS, Settings
from wx.cycle import Context, collect_features, run_cycle, taker_fees
from wx.cycle import report as cycle_report
from wx.decide import DEFAULT_ROLE, ROLES, code_version, log_decision
from wx.features import FEATURES
from wx.llm import LLMError, Reply, chat, chat_with_tools, parse_json
from wx.markets import allowed_markets, load_inactive, save_snapshot, tmn_volume, top_by_volume
from wx.prices import watch
from wx.replay import pick_times, run_replay, sample_times, summary
from wx.rules import MarketRules
from wx.shadow import Book
from wx.shadow import report as shadow_report
from wx.study import SetupRecord, lookup_from, scan
from wx.study import report as study_report
from wx.tradelog import table as trade_table
from wx.tradelog import trades
from wx.trades import History, typical_spreads
from wx.wallex import WallexError, fetch_balances, fetch_fees, fetch_markets

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


def run_features(symbols: list[str], settings: Settings) -> int:
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    table, errors = collect_features(markets, settings, DATA_DIR)
    if table:
        print(features_report(table))
    return 1 if errors else 0


def missing_ai_settings(settings: Settings) -> bool:
    missing = [k for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY") if not settings.is_set(k)]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}")
    return bool(missing)


def run_decide(symbols: list[str], settings: Settings, role: str, shadow: bool) -> int:
    if missing_ai_settings(settings):
        return 1
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    record = run_cycle(Context(markets, settings, DATA_DIR, role, shadow))
    print(cycle_report(record))
    return 0 if record["driver"] in ("ai", "rules") and not record["feature_errors"] else 1


def run_loop(symbols: list[str], settings: Settings, interval: int, cycles: int | None, role: str,
             shadow: bool) -> int:
    """`wx run`: a decision on every beat. Every cycle is logged, even a failed one. No real orders."""
    if missing_ai_settings(settings):
        return 1
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    ctx = Context(markets, settings, DATA_DIR, role, shadow)

    def step(cycle: int) -> None:
        print(f"--- cycle {cycle} at {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC")
        try:
            print(cycle_report(run_cycle(ctx, cycle)))
        except Exception as error:  # log it, then let the beat report it and go on
            log_decision(DATA_DIR, {"cycle": cycle, "version": code_version(), "driver": "none",
                                    "error": f"{type(error).__name__}: {error}", "ai": None, "decisions": []})
            raise

    mode = f"shadow book {ctx.book_path}" if shadow else "no orders"
    print(f"Deciding on {' '.join(markets)} every {interval} s, role {role}, {mode}. "
          f"Log: {DATA_DIR / 'decisions'}. Ctrl+C stops.")
    try:
        every(interval, step, cycles)
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


def live_executor(markets: dict[str, dict], settings: Settings, end_at: int | None = None):
    """The real-order executor, or None without a Wallex key."""
    from wx.live import LiveExecutor
    from wx.orders import Trader
    key = settings.get("WALLEX_API_KEY")
    if not key:
        print("Missing in .env: WALLEX_API_KEY")
        return None
    rules = {s: MarketRules.from_wallex(info) for s, info in markets.items()}
    return LiveExecutor(Trader(key), key, rules, DATA_DIR, end_at=end_at)


def run_agent(symbols: list[str], settings: Settings, live: bool, end_at: str | None, interval: int,
              cycles: int | None, officer: bool) -> int:
    """`wx agent`: the LangGraph agent on a beat, with a fake book (--shadow) or real orders (--live)."""
    from wx.execution import ShadowExecutor
    from wx.runner import log_dir, make_brain, open_memory, parse_end, run
    if missing_ai_settings(settings):
        return 1
    universe = not symbols  # no markets named: every liquid allowed TMN market, picked again each cycle
    if universe:
        from wx.universe import liquid, tradable_tmn
        try:
            markets = tradable_tmn()
        except WallexError as error:
            print(f"Could not read markets: {error}")
            return 1
        print(f"{len(markets)} allowed TMN markets; {len(liquid(markets))} liquid now (>= 5 B TMN a day).")
    else:
        markets = pick_markets(symbols)
        if markets is None:
            return 1
    end = parse_end(end_at)
    executor = live_executor(markets, settings, end) if live else ShadowExecutor(DATA_DIR)
    if executor is None:
        return 1
    name = "live" if live else "shadow"
    saver, store = open_memory(DATA_DIR, name)
    brain = make_brain(markets, settings, DATA_DIR, executor, end, store, officer, universe=universe)
    ends = datetime.fromtimestamp(end, UTC).strftime("%Y-%m-%d %H:%M UTC") if end else "never"
    where = "every liquid allowed TMN market" if universe else " ".join(markets)
    from wx.horizon import profile
    pace = profile(None if end is None else (end - time.time()) / 3600)
    print(f"Agent on {where}, {name.upper()} orders, trading ends {ends}. Pace now: {pace.name}, a decision every "
          f"{min(interval, pace.cycle_seconds)} s (it speeds up as the end comes closer). "
          f"Log: {log_dir(DATA_DIR, name) / 'decisions'}. Ctrl+C stops.")
    return run(brain, DATA_DIR, name, interval, cycles, saver)


def run_agent_replay(symbols: list[str], settings: Settings, moments: int, days: int, seed: int, workers: int,
                     saved: Path | None) -> int:
    """`wx agent-replay`: the agent graph on past moments, against the rules alone."""
    from wx import agent_replay
    if saved:
        records = [json.loads(line) for line in saved.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(agent_replay.summary(records))
        return 0
    if missing_ai_settings(settings):
        return 1
    from wx.runner import chat_model
    symbols = [s.upper() for s in symbols] or list(DEFAULT_SYMBOLS)
    print("Rebuilding the features at every past hour (cached for 6 hours) ...")
    rows, histories = agent_replay.load_rows(symbols, DATA_DIR, int(time.time()))
    out = DATA_DIR / "replay" / f"agent_graph_{datetime.now(UTC):%Y%m%d_%H%M}.jsonl"
    print(f"Replaying {moments} moments with the full graph. Log: {out}")
    records = agent_replay.run(rows, histories, chat_model(settings, DATA_DIR), moments, days, seed, out, workers)
    print(agent_replay.summary(records))
    return 0


def run_verify_log(day: str | None, live: bool) -> int:
    """Check the hash chain of the agent's decision log for one UTC day (default: today)."""
    from wx.decide import verify_chain
    base = DATA_DIR / "live" if live else DATA_DIR
    path = base / "decisions" / f"{day or f'{datetime.now(UTC):%Y-%m-%d}'}.jsonl"
    if not path.is_file():
        print(f"No log at {path}")
        return 1
    checked, problems = verify_chain(path)
    print(f"{path}: {checked} chained records, {'no problems' if not problems else len(problems)} problems")
    for p in problems:
        print("  " + p)
    return 1 if problems else 0


def run_live_report() -> int:
    """The live book from data/live/book.json, without calling Wallex."""
    path = DATA_DIR / "live" / "book.json"
    if not path.is_file():
        print("No live book yet.")
        return 0
    book = json.loads(path.read_text(encoding="utf-8"))
    for p in book["positions"]:
        print(f"  {p['status']:<9} {p['symbol']:<9} {p['setup']:<15} {p['tmn']:>12,.0f} TMN  entry {p['entry']}  "
              f"net {p['net_pct']}  {p['sell_reason']} {p['note']}")
    print(f"Peak equity {book.get('peak')}. Positions: {len(book['positions'])}.")
    return 0


def run_kill(symbols: list[str], settings: Settings) -> int:
    """The kill switch: cancel every open order and sell every position of the live book.

    With no markets named it knows every allowed TMN market, like the agent, so no position is left unsold."""
    if symbols:
        markets = pick_markets(symbols)
    else:
        from wx.universe import tradable_tmn
        try:
            markets = tradable_tmn()
        except WallexError as error:
            print(f"Could not read markets: {error}")
            return 1
    executor = live_executor(markets, settings) if markets else None
    if executor is None:
        return 1
    result = executor.kill(int(time.time()))
    print(json.dumps(result, indent=1, default=str))
    return 0 if not result["still_active"] else 1


def run_order_test(symbol: str, settings: Settings) -> int:
    """Check real order placement without buying: a minimum buy 20% under the price, read back, then cancelled.

    Every step is also saved in data/live/order_test.jsonl, so the result can be read later."""
    from decimal import Decimal

    from wx.orders import Trader, new_client_id
    from wx.prices import append_log
    log = DATA_DIR / "live" / "order_test.jsonl"

    def step(name: str, **extra) -> None:
        append_log(log, {"time": datetime.now(UTC).isoformat(timespec="seconds"), "version": code_version(),
                         "step": name, **{k: str(v) for k, v in extra.items()}})
    from wx.wallex import fetch_best_prices
    markets = pick_markets([symbol])
    key = settings.get("WALLEX_API_KEY")
    if not markets or not key:
        print("Need an allowed market and WALLEX_API_KEY.")
        return 1
    rules = MarketRules.from_wallex(markets[symbol.upper()])
    bid, _ = fetch_best_prices(rules.symbol)
    price = rules.round_price(bid * Decimal("0.8"), "BUY")
    qty = rules.round_qty(rules.min_notional * Decimal("1.2") / price) + rules.min_qty
    trader, cid = Trader(key), new_client_id("test")
    print(f"Placing LIMIT BUY {qty} {rules.symbol} at {price} (20% under the bid, so it should not fill), id {cid}")
    step("placing", symbol=rules.symbol, quantity=qty, price=price, bid=bid, client_id=cid)
    try:
        placed = trader.place(rules.symbol, "BUY", qty, price, cid)
        print(f"  placed: status {placed.status}, active {placed.active}")
        step("placed", state=placed)
        read = trader.get(cid)
        print(f"  read back: {read}")
        step("read back", state=read)
        open_ids = [o.client_id for o in trader.open_orders()]
        print(f"  open orders: {open_ids}")
        step("open orders", ids=open_ids)
    except WallexError as error:
        print(f"  failed: {error}")
        step("failed", error=error)
        return 1
    finally:
        try:
            cancelled = trader.cancel(cid)
            print(f"  cancelled: {cancelled}")
            step("cancelled", state=cancelled)
        except WallexError as error:
            print(f"  cancel failed, cancel it on the website: {error}")
            step("cancel failed", error=error)
    return 0


# Taker fee on TMN markets (DECISIONS F3), used by `wx replay` if fees can't be read.
TMN_TAKER_FEE = 0.003


def past_inputs(markets: dict[str, dict], settings: Settings):
    """Saved history, the typical spread and the taker fee for each market, for tests on the past."""
    now = int(time.time())
    histories = {s: History.load(DATA_DIR, s, now) for s in markets}
    fees = taker_fees(settings) or {s: TMN_TAKER_FEE for s in markets}
    return histories, typical_spreads(markets), fees


def run_study(symbols: list[str], settings: Settings, stops: list[float]) -> int:
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    histories, spreads, fees = past_inputs(markets, settings)
    print(f"Rebuilding the features at every past hour for {' '.join(markets)} ...")
    print(study_report(scan(histories, spreads, fees), histories, stops))
    return 0


def run_backtest(symbols: list[str], settings: Settings, hours: int | None = None) -> int:
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    histories, spreads, fees = past_inputs(markets, settings)
    print("Rebuilding the features at every past hour ...")
    rows = scan(histories, spreads, fees)
    print(short_scenarios(rows, histories, spreads, hours) if hours else scenarios(rows, histories))
    return 0


def run_replay_cmd(symbols: list[str], settings: Settings, moments: int, days: int, seed: int, workers: int,
                   any_time: bool, role: str, saved: Path | None = None) -> int:
    if saved:  # summarize a saved replay: the AI's answers and the outcomes are in the log
        print(summary([json.loads(line) for line in saved.read_text(encoding="utf-8").splitlines() if line]))
        return 0
    if missing_ai_settings(settings):
        return 1
    markets = pick_markets(symbols)
    if markets is None:
        return 1
    histories, spreads, fees = past_inputs(markets, settings)
    newest = int(min(h.minutes[-1][0] for h in histories.values() if h.minutes))
    start, end = newest - days * 86400, newest - 86400
    allowed = ROLES[role].setups
    print("Rebuilding the features at every past hour ...")
    rows = scan(histories, spreads, fees)
    if any_time:
        times = sample_times(start, end, moments, seed)
        kind = "moments"
    else:
        candidates = sorted({r["t"] for r in rows if any(s in allowed for s in r["features"]["setups"])})
        times = pick_times([t for t in candidates if start <= t <= end], moments, seed)
        kind = f"moments with a setup the {role} role may take (of {len(candidates)})"
    base_url, model, key = settings.get("LLM_BASE_URL"), settings.get("LLM_MODEL"), settings.get("LLM_API_KEY")
    record = SetupRecord(rows, histories) if role in ("informed", "agent") else None

    def ask(messages: list[dict], t: int, table: dict) -> Reply:
        if not ROLES[role].tools:
            return chat(base_url, model, key, messages, json_mode=True)
        tools = review_tools(table, lambda s, n: histories[s].hourly_closes(t, n), lambda: record.at(t))
        return chat_with_tools(base_url, model, key, messages, tools)

    log = DATA_DIR / "replay" / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.jsonl"
    print(f"Replaying {len(times)} {kind} from the last {days} days (seed {seed}), {workers} at a time. Log: {log}")
    results = run_replay(times, histories, spreads, fees, ask, lookup_from(rows), log, workers, role,
                         record.at if role == "informed" else None)
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


def run_shadow_report() -> int:
    """The shadow book, with open positions valued at the last saved 1-minute closes."""
    book = Book.load(DATA_DIR / "shadow" / "book.json")
    prices = {o.symbol: last_close(candle_path(DATA_DIR, o.symbol, "1m")) for o in book.active()}
    print(shadow_report(book, {s: p for s, p in prices.items() if p}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wx", description="Wallex trading bot.")
    parser.add_argument("--version", action="version", version=f"wx {__version__}")
    commands = parser.add_subparsers(dest="command")

    def command(name: str, help_: str, symbols: bool = True) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_)
        if symbols:
            sub.add_argument("symbols", nargs="*", help=f"default: {' '.join(DEFAULT_SYMBOLS)}")
        return sub

    def ai_role(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--role", choices=list(ROLES), default=DEFAULT_ROLE,
                         help=f"what the AI is asked to do (default {DEFAULT_ROLE})")

    def beat(sub: argparse.ArgumentParser, interval: int) -> None:
        sub.add_argument("--interval", type=int, default=interval, help=f"seconds between cycles (default {interval})")
        sub.add_argument("--cycles", type=int, default=None, help="stop after this many cycles (default: never)")

    command("markets", "list allowed markets and save a snapshot", symbols=False)
    command("account", "read balances and fees (needs WALLEX_API_KEY)", symbols=False)
    command("ai", "check the AI settings with one small call", symbols=False)
    command("shadow", "show the shadow book: cash, open orders, closed trades", symbols=False)
    command("tradelog", "the per-trade decision log, as a Markdown table", symbols=False).add_argument(
        "--live", action="store_true", help="the live book (default: the shadow book)")
    command("rules", "show decimals and minimum order size per market")
    command("features", "indicators per market, from candles and the live book")
    command("backtest", "trade 5,000,000 TMN over the saved history, rules only").add_argument(
        "--hours", type=int, default=None, help="instead: short windows of this many hours (the agent's setups), "
        "each sold into Toman at its end, e.g. --hours 12")
    command("candles", "save 1-minute and 1-hour candles").add_argument(
        "--days", type=int, default=KEEP_DAYS, help=f"how far back to keep (default {KEEP_DAYS})")
    beat(command("watch", "read live prices on a fixed beat and log them"), 60)
    command("study", "how each buy setup did in the past, without the AI").add_argument(
        "--stops", type=float, nargs="*", default=[2.0, 3.0, 4.0],
        help="stop-losses to try, in 1h ATRs below the entry (default 2 3 4)")
    for name, help_ in (("decide", "one AI decision per market, checked and logged (no real orders)"),
                        ("run", "decide on a fixed beat and log every cycle (no real orders)")):
        sub = command(name, help_)
        ai_role(sub)
        sub.add_argument("--shadow", action="store_true", help="trade a fake book with the risk check")
        if name == "run":
            beat(sub, DECIDE_EVERY)
    agent = command("agent", "the LangGraph trading agent on a beat: tools, skills, memory, risk check, orders")
    mode = agent.add_mutually_exclusive_group(required=True)
    mode.add_argument("--shadow", action="store_true", help="trade a fake book on live data")
    mode.add_argument("--live", action="store_true", help="place REAL orders on Wallex")
    agent.add_argument("--end-at", default=None, help="when trading ends, e.g. 2026-10-23T00:30 (UTC unless a zone "
                       "is given). No new buys in the last 3 hours, everything sold 30 minutes before.")
    agent.add_argument("--no-officer", action="store_true", help="skip the risk officer AI (faster cycles)")
    beat(agent, DECIDE_EVERY)
    command("live", "show the live book (no Wallex call)", symbols=False)
    areplay = command("agent-replay", "the agent graph on past moments, against the rules alone")
    areplay.add_argument("--moments", type=int, default=20, help="how many past moments (default 20)")
    areplay.add_argument("--days", type=int, default=60, help="pick moments from the last N days (default 60)")
    areplay.add_argument("--seed", type=int, default=7, help="picks the same moments again (default 7)")
    areplay.add_argument("--workers", type=int, default=3, help="moments at the same time (default 3)")
    areplay.add_argument("--from", dest="saved", type=Path, default=None, help="summarize a saved replay log")
    verify = command("verify-log", "check the hash chain of the agent's decision log", symbols=False)
    verify.add_argument("day", nargs="?", default=None, help="UTC day, e.g. 2026-10-22 (default today)")
    verify.add_argument("--live", action="store_true", help="the live log (default: the shadow log)")
    command("kill", "KILL SWITCH: cancel every open order and sell every live position")
    command("order-test", "place a minimum buy 20%% under the price, read it back, cancel it", symbols=False
            ).add_argument("symbol", nargs="?", default="USDTTMN")
    replayer = command("replay", "ask the AI about past moments and see what happened next")
    ai_role(replayer)
    replayer.add_argument("--moments", type=int, default=40, help="how many past moments (default 40)")
    replayer.add_argument("--days", type=int, default=60, help="pick moments from the last N days (default 60)")
    replayer.add_argument("--seed", type=int, default=7, help="picks the same moments again (default 7)")
    replayer.add_argument("--workers", type=int, default=3, help="AI calls at the same time (default 3)")
    replayer.add_argument("--any-time", action="store_true", help="pick any moments, not only ones with a setup")
    replayer.add_argument("--from", dest="saved", type=Path, default=None,
                          help="summarize a saved replay log instead of asking the AI")
    args = parser.parse_args(argv)
    # Wallex messages can be in Persian. Never crash on a console that can't show them.
    # Print each line at once, so a long run's output is never held back.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace", line_buffering=True)
    a = args
    actions = {
        "markets": lambda: run_markets(),
        "account": lambda: run_account(Settings.load()),
        "ai": lambda: run_ai(Settings.load()),
        "shadow": lambda: run_shadow_report(),
        "tradelog": lambda: print(trade_table(trades(DATA_DIR, a.live))) or 0,
        "rules": lambda: run_rules(a.symbols),
        "features": lambda: run_features(a.symbols, Settings.load()),
        "backtest": lambda: run_backtest(a.symbols, Settings.load(), a.hours),
        "candles": lambda: run_candles(a.symbols, a.days),
        "watch": lambda: run_watch(a.symbols, a.interval, a.cycles),
        "study": lambda: run_study(a.symbols, Settings.load(), a.stops),
        "decide": lambda: run_decide(a.symbols, Settings.load(), a.role, a.shadow),
        "run": lambda: run_loop(a.symbols, Settings.load(), a.interval, a.cycles, a.role, a.shadow),
        "agent": lambda: run_agent(a.symbols, Settings.load(), a.live, a.end_at, a.interval, a.cycles,
                                   not a.no_officer),
        "live": lambda: run_live_report(),
        "verify-log": lambda: run_verify_log(a.day, a.live),
        "agent-replay": lambda: run_agent_replay(a.symbols, Settings.load(), a.moments, a.days, a.seed, a.workers,
                                                 a.saved),
        "kill": lambda: run_kill(a.symbols, Settings.load()),
        "order-test": lambda: run_order_test(a.symbol, Settings.load()),
        "replay": lambda: run_replay_cmd(a.symbols, Settings.load(), a.moments, a.days, a.seed, a.workers,
                                         a.any_time, a.role, a.saved),
    }
    if a.command in actions:
        return actions[a.command]()
    print(status(Settings.load()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
