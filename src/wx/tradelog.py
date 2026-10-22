"""The per-trade decision log: why each shadow order was placed, and how it ended.

It joins the order events (data/shadow/orders.jsonl) with the decisions that
placed them (data/decisions/). An order carries the time of its decision
(`decided_at`). Older decisions without it are matched to the first decision
logged within 10 minutes after the order.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

MATCH_WINDOW = 600


def read_jsonl(paths) -> list[dict]:
    rows = []
    for path in paths:
        rows += [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
    return rows


def seconds(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp())


def decision_for(t: int, decisions: list[dict]) -> dict | None:
    exact = [r for r in decisions if r.get("decided_at") == t]
    if exact:
        return exact[0]
    later = [r for r in decisions if 0 <= seconds(r["time"]) - t <= MATCH_WINDOW]
    return min(later, key=lambda r: r["time"]) if later else None


def trades(data_dir: Path) -> list[dict]:
    """One row per order, with its last known state and the AI's view when it was placed."""
    log = data_dir / "shadow" / "orders.jsonl"
    events = read_jsonl([log]) if log.is_file() else []
    decisions = read_jsonl(sorted((data_dir / "decisions").glob("*.jsonl")))
    by_order = {}
    for e in events:  # every event carries the order's fields, so t is when the order was placed
        by_order.setdefault((e["symbol"], e["t"]), []).append(e)
    rows = []
    for (symbol, t), history in sorted(by_order.items(), key=lambda kv: kv[0][1]):
        placed, last = history[0], history[-1]
        record = decision_for(t, decisions)
        d = next((d for d in (record or {}).get("decisions", []) if d["symbol"] == symbol), {})
        rows.append({
            "placed": datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M"),
            "symbol": symbol, "setup": placed["setup"], "tmn": placed["tmn"], "rule": placed.get("rule", ""),
            "confidence": d.get("confidence"), "reason": d.get("reason", ""),
            "status": last["status"], "entry": last.get("entry"), "exit": last.get("reason", ""),
            "net_pct": last.get("net_pct"),
        })
    return rows


def table(rows: list[dict]) -> str:
    """The trade log as a Markdown table."""
    columns = ["Placed (UTC)", "Market", "Setup", "TMN", "Risk check", "AI confidence", "AI reason", "Status", "Exit",
               "Result"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for r in rows:
        conf = f"{r['confidence']:.2f}" if r["confidence"] is not None else "-"
        result = f"{r['net_pct']:+.2f}%" if r["net_pct"] is not None else "-"
        reason = r["reason"].replace("|", "/")
        lines.append(f"| {r['placed']} | {r['symbol']} | {r['setup']} | {r['tmn']:,.0f} | {r['rule']} | {conf} | "
                     f"{reason} | {r['status']} | {r['exit'] or '-'} | {result} |")
    return "\n".join(lines)
