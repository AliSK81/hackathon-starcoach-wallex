"""The live trade report for judges, rebuilt after every agent cycle (D55).

It joins every live order event (data/live/orders.jsonl) with the decision record that placed it
(data/live/decisions/): the signal code saw, the AI's reason and plan, the judge, the code's risk check,
the fill, the exit and the result. It is written to data/live/trade_report.md.
"""

from datetime import UTC, datetime
from pathlib import Path

from wx.tradelog import decision_for, read_jsonl

START_TMN = 5_000_000
SIGNAL_KEYS = ("ret_24h_pct", "ret_1h_pct", "rsi14", "bb_z_20", "ema20_vs_ema50_pct", "adx14", "regime",
               "round_trip_cost_pct")


def _when(t) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M") if t else "-"


def _num(x, digits: int = 0) -> str:
    return "-" if x is None else f"{x:,.{digits}f}"


def _cell(text) -> str:
    return str(text or "-").replace("|", "/").replace("\n", " ")


def live_trades(data_dir: Path) -> list[dict]:
    """Every live buy order, with the decision that placed it and how it ended."""
    log = data_dir / "live" / "orders.jsonl"
    events = [e for e in read_jsonl([log]) if e.get("setup")] if log.is_file() else []
    decisions = read_jsonl(sorted((data_dir / "live" / "decisions").glob("*.jsonl")))
    by_order: dict = {}
    for e in events:  # every event carries the position's fields, so t is when its buy was decided
        by_order.setdefault((e["symbol"], e["t"]), []).append(e)
    out = []
    for (symbol, t), history in sorted(by_order.items(), key=lambda kv: kv[0][1]):
        record = decision_for(t, decisions) or {}
        d = next((x for x in record.get("decisions", []) if x.get("symbol") == symbol and x.get("action") == "BUY"),
                 {})
        f = (record.get("markets") or {}).get(symbol) or {}
        out.append({"symbol": symbol, "t": t, "placed": history[0], "last": history[-1],
                    "bought": next((e for e in history if e["event"] == "bought"), None), "decision": d,
                    "signals": f.get("setups") or [], "numbers": {k: f.get(k) for k in SIGNAL_KEYS if k in f},
                    "version": record.get("version", ""), "events": [e["event"] for e in history]})
    return out


def real_net(x: dict) -> float | None:
    """The result counting the coin left after the sell (too small to sell, still in the account) at the exit
    price. The book's net_pct counts it as lost. Without a saved exit price, it is estimated from the proceeds."""
    last, bought = x["last"], x["bought"]
    if last.get("status") != "closed" or not last.get("cost_tmn"):
        return None
    left = float(last.get("qty") or 0)
    price = last.get("exit_price")
    if not price and bought and left:
        sold = float(bought.get("qty") or 0) - left
        price = last["proceeds_tmn"] / 0.997 / sold if sold > 0 else 0
    value = left * (price or 0) * 0.997
    return round(((last["proceeds_tmn"] + value) / last["cost_tmn"] - 1) * 100, 3)


def _plan(d: dict, last: dict) -> str:
    target = d.get("target_pct") or last.get("target_pct")
    return (f"risk {d.get('risk_pct', '-')}% of equity, stop {d.get('stop_pct', last.get('stop_pct'))}% under the "
            f"entry, target {f'{target}%' if target else 'none'}, hold at most {last.get('max_hours') or '-'} h, "
            f"sell when the trend turns: {'yes' if last.get('trend_exit') else 'no'}, {d.get('order', '-')} order")


def _summary(trades: list[dict], cycles: list[dict]) -> list[str]:
    acc = next((r.get("account") for r in reversed(cycles) if r.get("account")), None) or {}
    equity = acc.get("equity")
    closed = [x for x in trades if x["last"]["status"] == "closed"]
    nets = [r for r in (real_net(x) for x in closed) if r is not None]
    active = [x for x in trades if x["last"]["status"] in ("buying", "open", "selling")]
    cancelled = sum(1 for x in trades if x["last"]["status"] == "cancelled")
    dust = [f"{x['last']['qty']} {x['symbol'][:-3]}" for x in closed if float(x["last"].get("qty") or 0) > 0]
    versions = sorted({r.get("version", "") for r in cycles} - {""})
    return [
        "| Item | Value |",
        "|---|---|",
        f"| Start | {START_TMN:,} TMN |",
        f"| Equity at the last cycle | {_num(equity)} TMN |",
        f"| Return | {(equity / START_TMN - 1) * 100:+.2f}% |" if equity else "| Return | - |",
        f"| Decision cycles | {len(cycles)}, each one logged, also those with no trade |",
        f"| Buy orders | {len(trades)}: {len(closed)} closed, {len(active)} active, {cancelled} cancelled unfilled |",
        (f"| Closed trades (counting coin left after the sell) | {len(nets)}, {sum(n > 0 for n in nets)} won, "
         f"average {sum(nets) / len(nets):+.2f}% |"
         if nets else "| Closed trades | none yet |"),
        f"| Coin left after sells (below the minimum order) | {', '.join(dust) or 'none'} |",
        f"| Code versions (git commit) | {', '.join(versions) or '-'} |",
    ]


def _detail(i: int, x: dict) -> list[str]:
    last, d, placed, bought = x["last"], x["decision"], x["placed"], x["bought"]
    verdict = d.get("verdict") or {}
    nums = ", ".join(f"{k} {v}" for k, v in x["numbers"].items())
    real = real_net(x)
    result = f", {real:+.2f}%" if real is not None else ""
    if bought:
        buy = (f"limit {placed.get('price', '-')} for {placed.get('quantity', '-')}; filled at "
               f"{_num(bought.get('entry'))}, got {bought.get('qty')} after the fee, paid "
               f"{_num(bought.get('cost_tmn'))} TMN.")
    else:
        buy = f"limit {placed.get('price', '-')} for {placed.get('quantity', '-')}; not filled."
    if last["status"] == "closed":
        at = f" at {_num(last.get('exit_price'))}" if last.get("exit_price") else ""
        exit_ = (f"{_when(last.get('exit_t'))} UTC, reason: {last.get('sell_reason') or '-'}; received "
                 f"{_num(last.get('proceeds_tmn'))} TMN{at} after the fee.")
    else:
        exit_ = f"not yet ({last['status']})."
    return [
        f"### {i}. {x['symbol']}, {last['status']}{result}",
        "",
        f"- **Decided:** {_when(x['t'])} UTC, code version `{x['version'] or '-'}`, order `{placed.get('buy_id')}`.",
        f"- **Signal seen by code:** {', '.join(x['signals']) or 'none'}. Numbers: {nums or '-'}.",
        f"- **AI decision:** {d.get('strategy') or placed.get('setup')}, conviction {d.get('conviction', '-')}. "
        f"Reason: {d.get('reason') or '-'}",
        f"- **What would prove it wrong (AI):** {d.get('invalidation') or '-'}",
        f"- **Plan (AI):** {_plan(d, last)}.",
        f"- **Judge (AI):** {d.get('judge') or 'no review'}",
        f"- **Risk check (code):** {verdict.get('reason') or placed.get('rule', '-')}, "
        f"{_num(verdict.get('tmn') or placed.get('tmn'))} TMN.",
        f"- **Buy:** {buy}",
        f"- **Exit:** {exit_}",
        f"- **Order events:** {' -> '.join(x['events'])}.",
        "",
    ]


def live_report(data_dir: Path, now: int | None = None) -> str:
    """The per-trade decision log for judges, as Markdown: a summary, a table, and every trade in full."""
    trades = live_trades(data_dir)
    decisions = read_jsonl(sorted((data_dir / "live" / "decisions").glob("*.jsonl")))
    cycles = [r for r in decisions if r.get("role") == "brain" and r.get("plan") is not None]
    stamp = _when(now or int(datetime.now(UTC).timestamp()))
    lines = [
        "# Live trade log",
        "",
        f"Rebuilt automatically after every agent cycle; this copy at {stamp} UTC. Sources: `data/live/orders.jsonl` "
        "(every order event) and `data/live/decisions/` (every cycle, hash-chained, check with "
        "`uv run wx verify-log --live`). Every buy and sell was decided by the AI agent and checked by code; none was "
        "placed by hand. Rebuild it any time with `uv run wx tradelog --live`.",
        "",
        "## Summary",
        "",
        *_summary(trades, cycles),
        "",
        "## Trades",
        "",
        "| # | Decided (UTC) | Market | Signal seen by code | AI strategy | Size TMN | Status | Entry | Exit | "
        "Exit reason | Result | Result with coin left |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, x in enumerate(trades, 1):
        last, d = x["last"], x["decision"]
        result = f"{last['net_pct']:+.2f}%" if last.get("net_pct") is not None else "-"
        real = real_net(x)
        lines.append(f"| {i} | {_when(x['t'])} | {x['symbol']} | {_cell(', '.join(x['signals']))} | "
                     f"{_cell(d.get('strategy') or x['placed'].get('setup'))} | {_num(x['placed'].get('tmn'))} | "
                     f"{last['status']} | {_num(last.get('entry'))} | {_num(last.get('exit_price'))} | "
                     f"{_cell(last.get('sell_reason'))[:80]} | {result} | "
                     f"{f'{real:+.2f}%' if real is not None else '-'} |")
    lines += ["", "## Each trade", ""]
    for i, x in enumerate(trades, 1):
        lines += _detail(i, x)
    return "\n".join(lines)


def write_live_report(data_dir: Path) -> Path:
    path = data_dir / "live" / "trade_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(live_report(data_dir), encoding="utf-8")
    tmp.replace(path)
    return path
