"""Live-run health check: the agent process, its log, the hash chain, and the book against Wallex.

Prints a PROBLEM line for each problem, then status lines. Read-only: no orders, no AI calls.
    uv run python scripts/live_health.py
"""
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, "src")
from wx.config import Settings  # noqa: E402
from wx.decide import verify_chain  # noqa: E402
from wx.orders import Trader  # noqa: E402
from wx.wallex import fetch_balances  # noqa: E402

DATA = Path("data")
problems, notes = [], []
now = time.time()

# 1. the agent is alive and its log moves
log = DATA / "brain" / "live_run.log"
age = (now - log.stat().st_mtime) / 60 if log.is_file() else 1e9
if age > 18:  # a cycle every 15 minutes (5 in the last 8 hours), plus its own time
    problems.append(f"live_run.log not written for {age:.0f} min")
procs = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object "
                        "{ $_.CommandLine -match 'wx.cli agent --live' }).Count"],
                       capture_output=True, text=True).stdout.strip()
if procs not in ("1", "2"):  # a venv launcher plus the real process
    problems.append(f"live agent processes: {procs or 0} (expected 1 agent, shown as 1 or 2)")

# 2. the hash chain of today's live decision log
day = datetime.now(UTC).strftime("%Y-%m-%d")
path = DATA / "live" / "decisions" / f"{day}.jsonl"
if path.is_file():
    checked, bad = verify_chain(path)
    if bad:
        problems.append(f"decision log chain: {len(bad)} problems in {checked} records: {bad[:2]}")
    last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    ai = last.get("ai") or {}
    if ai.get("error") or last.get("error"):
        problems.append(f"last cycle failed: {(ai.get('error') or last.get('error'))[:200]}")
    for p in last.get("problems") or []:
        problems.append(f"last cycle problem: {str(p)[:200]}")
    notes.append(f"cycle {last.get('cycle')} tokens {ai.get('tokens')} cached {ai.get('cached_tokens')} "
                 f"tools {len(ai.get('steps') or [])} today {last.get('tokens_today')}")

# 3. the book against Wallex
book = json.loads((DATA / "live" / "book.json").read_text(encoding="utf-8"))
active = [p for p in book["positions"] if p["status"] in ("buying", "open", "selling")]
key = Settings.load().get("WALLEX_API_KEY")
try:
    bal = fetch_balances(key)
    orders = Trader(key).open_orders()
except Exception as error:  # noqa: BLE001
    problems.append(f"Wallex read failed: {error}")
    bal, orders = {}, []
held = {}
for p in active:
    base = p["symbol"][:-3]
    held[base] = held.get(base, Decimal(0)) + Decimal(p["qty"] or "0")
for asset, b in bal.items():
    if asset == "TMN":
        continue
    value = Decimal(str(b.get("value") or 0))
    mine = held.get(asset, Decimal(0))
    if value > 0 and mine == 0:
        notes.append(f"{asset} {value} on Wallex, not in the book (dust or a fill not booked yet)")
    if mine > value * Decimal("1.001"):
        problems.append(f"book holds {mine} {asset}, Wallex only {value}")
ours = {p["buy_id"] for p in active if p["status"] == "buying"} | {p["sell_id"] for p in active if p["status"] == "selling"}
for o in orders:
    if o.client_id not in ours:
        problems.append(f"open order on Wallex not in the book: {o.client_id} {o.symbol} {o.side} {o.status}")
for cid in ours:
    if cid and cid not in {o.client_id for o in orders}:
        notes.append(f"book order {cid} not open on Wallex (filled or cancelled; next sync books it)")
tmn = Decimal(str((bal.get("TMN") or {}).get("value") or 0))
closed = [p for p in book["positions"] if p["status"] == "closed"]
notes.append(f"TMN {tmn:,.0f}, active {[(p['symbol'], p['status']) for p in active]}, closed {len(closed)}")

stamp = datetime.now(UTC).strftime("%H:%M")
if problems:
    for p in problems:
        print(f"[health {stamp}] PROBLEM {p}", flush=True)
for n in notes:
    print(f"[health {stamp}] {n}", flush=True)
