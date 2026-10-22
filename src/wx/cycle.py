"""One live decision cycle: features, account, the AI's decision, the risk check, shadow orders.

`wx decide` runs one cycle, and `wx run` runs one on every beat. With a
shadow book, the risk check sizes each BUY and approved buys become fake
orders (shadow.py). Without one, the account is read from Wallex and the
decision is only logged. No real order is ever placed here.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

from wx.agent import review_tools
from wx.candles import candle_path, load_candles
from wx.config import Settings
from wx.decide import DEFAULT_ROLE, ROLES, code_version, decide, holdings, log_decision
from wx.features import HOUR, closed_bars, market_features
from wx.llm import Reply, chat, chat_with_tools
from wx.replay import History
from wx.risk import check_buy
from wx.rules import MarketRules
from wx.shadow import Book
from wx.study import SetupRecord, scan
from wx.wallex import WallexError, fetch_balances, fetch_best_prices, fetch_fees

SETUP_RECORD_HOURS = 24  # how often the agent's setup record is rebuilt


@dataclass
class Context:
    markets: dict[str, dict]  # Wallex info per market, from pick_markets
    settings: Settings
    data_dir: Path
    role: str = DEFAULT_ROLE
    shadow: bool = False  # trade a fake book in data/shadow/
    record: SetupRecord | None = field(default=None, repr=False)
    record_t: int = 0

    @property
    def book_path(self) -> Path:
        return self.data_dir / "shadow" / "book.json"

    @property
    def orders_log(self) -> Path:
        return self.data_dir / "shadow" / "orders.jsonl"


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


def collect_features(symbols, settings: Settings, data_dir: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """Features and errors, each keyed by market. One bad market never stops the rest."""
    fees = taker_fees(settings)
    table, errors = {}, {}
    for symbol in symbols:
        try:
            table[symbol] = market_features(symbol, data_dir, fees.get(symbol))
        except (WallexError, ValueError) as error:
            errors[symbol] = str(error)
            print(f"  {symbol}: failed. {error}")
    return table, errors


def live_spreads(symbols, fallback: float = 0.3) -> dict[str, float]:
    """Today's spread per market in %, from the live book. `fallback` if the book can't be read."""
    spreads = {}
    for s in symbols:
        try:
            bid, ask = fetch_best_prices(s)
            spreads[s] = float((ask - bid) / ((ask + bid) / 2) * 100)
        except WallexError:
            spreads[s] = fallback
            print(f"  {s}: could not read the book, so the spread is taken as {fallback}%")
    return spreads


def setup_record(ctx: Context, now: int) -> dict:
    """Each setup's record up to now, rebuilt from the saved history once a day (it takes about 30 s)."""
    if ctx.record is None or now - ctx.record_t >= SETUP_RECORD_HOURS * HOUR:
        histories = {s: History.load(ctx.data_dir, s, now) for s in ctx.markets}
        rows = scan(histories, live_spreads(ctx.markets), {})
        ctx.record, ctx.record_t = SetupRecord(rows, histories), now
    return ctx.record.at(now)


def asker(ctx: Context, table: dict[str, dict], now: int):
    """The AI call for this cycle: one answer, or the agent's tool loop if the role has tools."""
    s = ctx.settings
    base_url, model, key = s.get("LLM_BASE_URL"), s.get("LLM_MODEL"), s.get("LLM_API_KEY")
    if not ROLES[ctx.role].tools:
        return lambda messages: chat(base_url, model, key, messages, json_mode=True)

    def closes(symbol: str, hours: int) -> list[float]:
        bars = closed_bars(load_candles(candle_path(ctx.data_dir, symbol, "1h")), HOUR, now)
        return [b[4] for b in bars[-hours:]]

    def ask(messages: list[dict]) -> Reply:
        tools = review_tools(table, closes, lambda: setup_record(ctx, now))
        return chat_with_tools(base_url, model, key, messages, tools)
    return ask


def wallex_account(ctx: Context, table: dict[str, dict], record: dict) -> None:
    """Cash and holdings from the real account, for a cycle without a shadow book."""
    key = ctx.settings.get("WALLEX_API_KEY")
    try:
        if not key:
            raise WallexError("no WALLEX_API_KEY")
        rules = {s: MarketRules.from_wallex(info) for s, info in ctx.markets.items()}
        record["cash_tmn"], record["held"] = holdings(fetch_balances(key), rules, table)
    except WallexError as error:
        record["account_error"] = str(error)
        print(f"Could not read the account, so the AI is told cash is unknown and we hold nothing: {error}")


def run_cycle(ctx: Context, cycle: int | None = None) -> dict:
    """One cycle. Logs one line in data/decisions/ and returns it."""
    table, feature_errors = collect_features(ctx.markets, ctx.settings, ctx.data_dir)
    now = int(time.time())
    record = {"cycle": cycle, "version": code_version(), "role": ctx.role, "markets": table,
              "feature_errors": feature_errors, "cash_tmn": None, "held": {}, "account_error": None}
    if not table:
        record.update(driver="none", error="no market has features", ai=None, decisions=[])
        log_decision(ctx.data_dir, record)
        return record
    book = None
    if ctx.shadow:
        book = Book.load(ctx.book_path)
        histories = {s: History.load(ctx.data_dir, s, now) for s in book.held()}
        book.update(histories, now, ctx.orders_log)
        account = book.account({s: f["price"] for s, f in table.items()}, now)
        record["cash_tmn"], record["held"] = int(account.cash), book.positions(table, now)
    else:
        wallex_account(ctx, table, record)
    record.update(decide(table, record["cash_tmn"], record["held"], asker(ctx, table, now), ctx.role))
    if book is not None:
        record["shadow"] = act(book, record["decisions"], table, account, now, ctx.orders_log)
        book.save(ctx.book_path)
    log_decision(ctx.data_dir, record)
    return record


def act(book: Book, decisions: list[dict], table: dict[str, dict], account, now: int, log: Path) -> dict:
    """Turn checked decisions into fake orders: the risk check sizes each BUY, a SELL closes now."""
    verdicts = {}
    for d in decisions:
        symbol, f = d["symbol"], table[d["symbol"]]
        if d["action"] == "SELL":
            book.sell_now(symbol, f, now, log)
        elif d["action"] == "BUY":
            if symbol in book.held():
                verdicts[symbol] = {"tmn": 0, "rule": "already held", "reason": "rejected: already held"}
                continue
            v = check_buy(f, account)
            verdicts[symbol] = {"tmn": v.tmn, "rule": v.rule, "reason": v.reason}
            if v.tmn:
                book.place(symbol, d["setup"], f, v, now, log)
                account = book.account({s: g["price"] for s, g in table.items()}, now)
    return {"equity": round(account.equity), "cash": round(book.cash), "verdicts": verdicts,
            "active": [o.symbol + ":" + o.status for o in book.active()]}


def report(record: dict) -> str:
    """The cycle in a few lines, for the console."""
    lines = []
    if record.get("error"):
        lines.append(f"The AI failed, so every market is HOLD: {record['error']}")
    if record.get("ai"):
        ai = record["ai"]
        steps = len(ai.get("steps") or [])
        lines.append(f"Model {ai['model']} answered in {ai['seconds']} s. Tokens: "
                     f"{ai['usage'].get('total_tokens', 'unknown')}." + (f" Tool calls: {steps}." if steps else ""))
    if record.get("driver") == "rules":
        lines.append("No setup the AI may take, and nothing held: every market is HOLD without asking the AI.")
    if record.get("market_view"):
        lines.append(f"Market view: {record['market_view']}")
    for d in record["decisions"]:
        if d["action"] != "HOLD" or d["reason"] or d["problems"]:
            lines.append(f"  {d['symbol']:<9} {d['action']:<4} {d['confidence']:.2f}  {d['reason']}")
        if d["cited"]:
            lines.append("            cited: " + ", ".join(f"{k}={v}" for k, v in d["cited"].items()))
        for problem in d["problems"]:
            lines.append(f"            problem: {problem}")
    for problem in record.get("problems", []):
        lines.append(f"Problem: {problem}")
    if "shadow" in record:
        sh = record["shadow"]
        lines.append(f"Shadow book: equity {sh['equity']:,} TMN, cash {sh['cash']:,}, active {sh['active'] or 'none'}")
        for symbol, v in sh["verdicts"].items():
            lines.append(f"  risk check {symbol}: {v['reason']}" + (f", {v['tmn']:,} TMN" if v["tmn"] else ""))
    return "\n".join(lines)
